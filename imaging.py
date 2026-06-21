"""
Pure raster-processing layer. No Tkinter / no PyMuPDF here — every function takes
and returns numpy arrays so the whole module is unit-testable headless.

Self-contained: depends only on cv2 + numpy (Sauvola binarization is implemented
locally via box filters — see `_sauvola_threshold`). docuwarp is imported lazily
inside `unwarp_bgr`; absence degrades gracefully.
"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np


def _sauvola_threshold(image: np.ndarray, window_size: int, k: float,
                       r: float = 127.5) -> np.ndarray:
    """Per-pixel Sauvola threshold T = m·(1 + k·(s/R − 1)), where m and s are the
    local mean and standard deviation over a `window_size`² window and R = `r` is
    the assumed dynamic range of s (127.5 for 8-bit). Computed with cv2 box filters
    (equivalent to the integral-image formulation) so no scikit-image is required.
    Returns a float threshold map the caller compares against (`ink = img < T`).
    """
    win = (int(window_size) | 1, int(window_size) | 1)
    img = image.astype(np.float64)
    mean = cv2.boxFilter(img, ddepth=-1, ksize=win, normalize=True,
                         borderType=cv2.BORDER_REFLECT_101)
    sq_mean = cv2.boxFilter(img * img, ddepth=-1, ksize=win, normalize=True,
                            borderType=cv2.BORDER_REFLECT_101)
    std = np.sqrt(np.clip(sq_mean - mean * mean, 0.0, None))
    return mean * (1.0 + k * ((std / r) - 1.0))

# Discrete clean strength → (sauvola_k, min_component_area_at_upscale1). Lower k = thicker
# strokes; higher min_area = more despeckle. Deliberately 3 levels (continuous = false
# precision, per spec §4.2).
_STRENGTH = {
    1: dict(k=0.060, min_area=20),   # cautious  — keep faint strokes, light despeckle
    2: dict(k=0.110, min_area=40),   # normal
    3: dict(k=0.180, min_area=90),   # aggressive — kill speckle, risk thinning
}


# --------------------------------------------------------------------------- onnx
def force_int64_inputs(session) -> None:
    """docuwarp's ONNX graph wants int64 grid inputs; some exports feed int32."""
    orig = session.run

    def run(output_names, input_feed, run_options=None):
        fixed = {k: (v.astype(np.int64) if isinstance(v, np.ndarray) and v.dtype == np.int32 else v)
                 for k, v in input_feed.items()}
        return orig(output_names, fixed, run_options)

    session.run = run


# ---------------------------------------------------------------------- DPI scale
def _dpi_scale(dpi: Optional[float]) -> float:
    """Scale pixel-defined kernels from the 150-DPI reference the defaults assume
    (spec §8.4). Clamped so extreme DPIs don't blow kernels up unboundedly."""
    if not dpi or dpi <= 0:
        return 1.0
    return float(np.clip(dpi / 150.0, 0.5, 4.0))


# -------------------------------------------------------------------------- clean
def clean_document_bilevel(
    img_bgr: np.ndarray,
    *,
    strength: int = 2,
    dpi: Optional[float] = None,
    sauvola_window: int = 51,
    bg_kernel: int = 51,
    upscale: float = 2.0,
    preserve_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Bilevel clean: ink=0 / background=255 (uint8, single channel).

    `strength` selects (k, min_component_area). `dpi`, if given, scales the
    pixel-defined kernels (window / bg / despeckle) so 150- and 600-DPI scans
    binarize comparably. `preserve_mask` (uint8, nonzero = keep as-is) protects
    photo/figure regions from global bilevel — those pixels are composited back
    as thresholded grayscale instead of being forced to pure ink/paper.
    """
    cfg = _STRENGTH[int(strength)]
    ds = _dpi_scale(dpi)
    sauvola_window = max(3, int(round(sauvola_window * ds))) | 1
    bg_kernel = max(3, int(round(bg_kernel * ds))) | 1
    min_area = int(round(cfg["min_area"] * ds * ds))

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        bg_kernel = int(round(bg_kernel * upscale)) | 1
        sauvola_window = int(round(sauvola_window * upscale)) | 1
        min_area = int(round(min_area * upscale * upscale))

    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bg_kernel, bg_kernel))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, se)
    flat = np.clip(cv2.divide(gray.astype(np.float32), bg.astype(np.float32) + 1e-6) * 255.0,
                   0, 255).astype(np.uint8)
    thr = _sauvola_threshold(flat, sauvola_window, cfg["k"])
    text = (flat < thr).astype(np.uint8)

    if min_area > 0:
        n, lbl, stats, _ = cv2.connectedComponentsWithStats(text, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA].copy()
        areas[0] = 0
        keep = np.isin(lbl, np.nonzero(areas >= min_area)[0])
    else:
        keep = text.astype(bool)

    hi = np.full_like(gray, 255)
    hi[keep] = 0

    if upscale and upscale != 1.0:
        h, w = img_bgr.shape[:2]
        out = cv2.resize(hi, (w, h), interpolation=cv2.INTER_AREA)
        out = np.where(out < 128, 0, 255).astype(np.uint8)
    else:
        out = hi

    if preserve_mask is not None:
        m = preserve_mask.astype(bool)
        if m.shape != out.shape:
            m = cv2.resize(preserve_mask, (out.shape[1], out.shape[0]),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
        out[m] = gray_resized_to(out, img_bgr)[m]
    return out


def gray_resized_to(ref: np.ndarray, img_bgr: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if g.shape != ref.shape:
        g = cv2.resize(g, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
    return g


# ------------------------------------------------------------- picture detection
def detect_picture_mask(img_bgr: np.ndarray, *, min_frac: float = 0.01) -> Optional[np.ndarray]:
    """Heuristic mask of photo/figure regions (continuous-tone or saturated colour),
    so `preserve_pictures` can exclude them from bilevel. Returns uint8 (255 = picture)
    or None if nothing substantial is found. Heuristic, not segmentation [low]."""
    h, w = img_bgr.shape[:2]
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # local std (texture) — pictures have mid-range continuous tone, text is bimodal
    blur = cv2.blur(gray.astype(np.float32), (15, 15))
    var = cv2.blur((gray.astype(np.float32) - blur) ** 2, (15, 15))
    texture = (var > 120).astype(np.uint8)
    colour = (sat > 60).astype(np.uint8)
    cand = cv2.max(texture, colour)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    out = np.zeros((h, w), np.uint8)
    thresh = min_frac * h * w
    found = False
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= thresh:
            out[lbl == i] = 255
            found = True
    return out if found else None


# ------------------------------------------------------------------------ deskew
def estimate_skew(gray: np.ndarray, *, max_deg: float = 15.0) -> float:
    """Correction angle (degrees) to pass straight to `deskew`. Sign convention is
    composed so `deskew(g, estimate_skew(g))` straightens the page (validated:
    +7.0 in → -7.01 correction). Clamped to ±max_deg."""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    inv = 255 - gray
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pts = cv2.findNonZero(bw)
    if pts is None or len(pts) < 50:
        return 0.0
    ang = cv2.minAreaRect(pts)[-1]
    if ang < -45:
        ang += 90
    elif ang > 45:
        ang -= 90
    return float(np.clip(ang, -max_deg, max_deg))


def deskew(img: np.ndarray, angle: float, *, border: int = 255) -> np.ndarray:
    if abs(angle) < 0.05:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def deskew_auto(img: np.ndarray) -> Tuple[np.ndarray, float]:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    ang = estimate_skew(g)
    return deskew(img, ang), ang


# ------------------------------------------------------------------- content box
def content_box(bilevel: np.ndarray, *, border_frac: float = 0.02,
                min_comp_frac: float = 2.5e-4) -> Optional[Tuple[int, int, int, int]]:
    """Tight (x0, y0, x1, y1) over the *text* region of a bilevel page (ink<128).

    Robust to scan artifacts that broke the naive min/max bound: connected
    components touching the outer `border_frac` margin (scan-edge lines, page
    shadows, hole-punches) are discarded, as is speckle below `min_comp_frac`
    of page area. The box is the bounds of the survivors. Returns None if
    nothing substantial remains.
    """
    if bilevel.ndim == 3:
        bilevel = cv2.cvtColor(bilevel, cv2.COLOR_BGR2GRAY)
    h, w = bilevel.shape[:2]
    ink = (bilevel < 128).astype(np.uint8)
    if ink.sum() == 0:
        return None
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    bm = int(round(border_frac * min(h, w)))
    min_area = max(8.0, min_comp_frac * h * w)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, ww, hh, area = stats[i, [cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                       cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT, cv2.CC_STAT_AREA]]
        touches = (x <= bm or y <= bm or x + ww >= w - bm or y + hh >= h - bm)
        if area >= min_area and not touches:
            keep[i] = True
    if not keep.any():
        # fallback: keep everything above min_area even if border-touching
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                keep[i] = True
        if not keep.any():
            return None
    mask = keep[lbl]
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def sharpen_grayscale(img_bgr: np.ndarray, *, amount: float = 1.1,
                      bg_kernel: int = 51, denoise: bool = True) -> np.ndarray:
    """Keep continuous-tone grayscale but flatten illumination, denoise, and
    unsharp-mask. For scans where bilevel would destroy photos/anti-aliasing.
    Returns single-channel uint8 (NOT bilevel)."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bg_kernel | 1, bg_kernel | 1))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, se)
    flat = np.clip(cv2.divide(gray.astype(np.float32), bg.astype(np.float32) + 1e-6) * 255.0,
                   0, 255).astype(np.uint8)
    if denoise:
        flat = cv2.bilateralFilter(flat, 5, 40, 40)
    blur = cv2.GaussianBlur(flat, (0, 0), 2.0)
    sharp = cv2.addWeighted(flat, 1.0 + amount, blur, -amount, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------ unwarp
_UNWARP_CACHE: dict = {}


def unwarp_available() -> bool:
    try:
        import docuwarp  # noqa: F401
        return True
    except Exception:
        return False


def unwarp_bgr(bgr: np.ndarray, *, providers=("CPUExecutionProvider",)) -> np.ndarray:
    """Learned mesh dewarp (page curl/fold) + incidental deskew. In/out BGR uint8.
    Model is cached process-wide. Raises RuntimeError if docuwarp is not installed —
    callers surface that to the user rather than crashing.

    NOTE: trained on photos; feed a grayscale/colour raster, NOT a bilevel image
    (bilevel is OOD and the predicted flow is near-identity/noisy) — spec §8.1 / doc1.
    """
    from PIL import Image
    try:
        from docuwarp.unwarp import Unwarp
    except Exception as exc:  # pragma: no cover - exercised only when dep missing
        raise RuntimeError("docuwarp not installed — run: pip install docuwarp") from exc

    if "u" not in _UNWARP_CACHE:
        u = Unwarp(providers=list(providers))
        force_int64_inputs(u.bilinear_unwarping)
        _UNWARP_CACHE["u"] = u
    pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    out = _UNWARP_CACHE["u"].inference(pil)
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
