import cv2
import time
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from skimage.filters import threshold_sauvola
from docuwarp.unwarp import Unwarp


# --------------------------------------------------------------- onnx int64 patch
def _force_int64_inputs(session):
    orig_run = session.run
    def run(output_names, input_feed, run_options=None):
        fixed = {k: (v.astype(np.int64) if isinstance(v, np.ndarray) and v.dtype == np.int32 else v)
                 for k, v in input_feed.items()}
        return orig_run(output_names, fixed, run_options)
    session.run = run


# ----------------------------------------------------------------------- step 1
def clean_document_bilevel(img_bgr, *, sauvola_window=51, sauvola_k=0.11,
                           bg_kernel=51, min_component_area=40,
                           upscale=2.0, stroke_close=0):
    """Bilevel clean: ink=0 / background=255. Lower k -> thicker strokes;
    upscale preserves anti-aliased stroke edges.
    min_component_area scales with upscale^2 -- raise if speckle survives."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        bg_kernel = int(round(bg_kernel * upscale)) | 1
        sauvola_window = int(round(sauvola_window * upscale)) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bg_kernel, bg_kernel))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, se)
    flat = np.clip(cv2.divide(gray.astype(np.float32), bg.astype(np.float32) + 1e-6) * 255.0,
                   0, 255).astype(np.uint8)
    thr = threshold_sauvola(flat, window_size=sauvola_window, k=sauvola_k)
    text = (flat < thr).astype(np.uint8)
    if stroke_close and stroke_close > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke_close, stroke_close))
        text = cv2.morphologyEx(text, cv2.MORPH_CLOSE, k)
    _, lbl, stats, _ = cv2.connectedComponentsWithStats(text, connectivity=8)
    areas = stats[:, cv2.CC_STAT_AREA].copy(); areas[0] = 0
    keep = np.isin(lbl, np.nonzero(areas >= min_component_area)[0])
    out_hi = np.full_like(gray, 255); out_hi[keep] = 0
    if upscale and upscale != 1.0:
        h, w = img_bgr.shape[:2]
        out = cv2.resize(out_hi, (w, h), interpolation=cv2.INTER_AREA)
        out = np.where(out < 128, 0, 255).astype(np.uint8)
    else:
        out = out_hi
    return out


# ----------------------------------------------------------------------- step 2
def unwarp_page(bgr, *, providers=("CPUExecutionProvider",), _cache={}):
    """Learned mesh dewarp (page curl/fold). In/out BGR uint8. Model cached
    across calls. NOTE: trained on photos -- feeding bilevel here is OOD and the
    predicted flow may be near-identity or noisy; for genuine curl, run this on
    GRAYSCALE before cleaning [high]."""
    if "u" not in _cache:
        u = Unwarp(providers=list(providers))
        _force_int64_inputs(u.bilinear_unwarping)
        _cache["u"] = u
    pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    out = _cache["u"].inference(pil)
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


# ----------------------------------------------------------------------- step 3
def detect_text_boxes(cleaned, *, level="line", min_w=8, min_h=8,
                      min_area=40, color=(0, 0, 255), thickness=2):
    """Text borders on a bilevel page. Returns (overlay_bgr, boxes Nx4 (x,y,w,h))."""
    ink = (cleaned < 128).astype(np.uint8)
    gap = {"word": 12, "line": 45}[level]
    se = cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 3))
    merged = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, se)
    n, _, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    overlay = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)
    boxes = []
    for i in range(1, n):
        x, y, w, h, a = stats[i, [cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                   cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT, cv2.CC_STAT_AREA]]
        if w < min_w or h < min_h or a < min_area:
            continue
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, thickness)
        boxes.append((x, y, w, h))
    return overlay, np.array(boxes, dtype=int).reshape(-1, 4)




# --------------------------------------------------------------------------- viz
def _show(img, title):
    """Blocking display — pauses until the window is closed."""
    disp = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img.ndim == 3 else img
    plt.figure(figsize=(8, 11))
    plt.imshow(disp, cmap=None if img.ndim == 3 else "gray")
    plt.title(title); plt.axis("off"); plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    INPUT, OUTPUT = "test_page_2.jpg", "perfect_flat_scanned_page.png"
    t0 = time.perf_counter()
    img = cv2.imread(INPUT)
    if img is None:
        raise FileNotFoundError(f"cannot read {INPUT}")

    # 1. clean photo
    cleaned0 = clean_document_bilevel(img)
    _show(cleaned0, "1. cleaned")                                  # <- delete to silence

    # 2. unwrap the text
    unwarped = unwarp_page(cv2.cvtColor(cleaned0, cv2.COLOR_GRAY2BGR))
    unwarped_bilevel = np.where(cv2.cvtColor(unwarped, cv2.COLOR_BGR2GRAY) < 128,
                                0, 255).astype(np.uint8)           # re-snap after resample
    _show(unwarped_bilevel, "2. unwarped")                        # <- delete to silence

    # 3. detect text borders
    overlay, boxes = detect_text_boxes(unwarped_bilevel, level="line")
    print(f"text regions: {len(boxes)}")
    _show(overlay, "3. text borders")                             # <- delete to silence

    # 4. calc trapezoid (from detected boxes) and delete it
    flat = delete_trapezoid(unwarped_bilevel, boxes)
    _show(flat, "4. trapezoid removed")                           # <- delete to silence

    cv2.imwrite(OUTPUT, flat)
    print(f"saved {OUTPUT}  ({(time.perf_counter() - t0)*1e3:.0f} ms total)")