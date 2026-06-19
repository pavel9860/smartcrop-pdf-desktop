import cv2
import time
import numpy as np
from PIL import Image
from docuwarp.unwarp import Unwarp


def _force_int64_inputs(session):
    orig_run = session.run

    def run(output_names, input_feed, run_options=None):
        fixed = {
            k: (v.astype(np.int64) if isinstance(v, np.ndarray) and v.dtype == np.int32 else v)
            for k, v in input_feed.items()
        }
        return orig_run(output_names, fixed, run_options)

    session.run = run


def _fit_margin_line(ys, xs):
    a, b = np.polyfit(ys, xs, 1)
    for _ in range(3):
        resid = xs - (a * ys + b)
        s = np.median(np.abs(resid)) + 1e-6
        keep = np.abs(resid) < 3.0 * s
        if keep.sum() < 0.5 * len(xs):
            break
        a, b = np.polyfit(ys[keep], xs[keep], 1)
    return a, b


def _devertical_trapezoid(bgr):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, 41), np.uint8))

    ys, lefts, rights = [], [], []
    for y in range(h):
        cols = np.flatnonzero(ink[y])
        if cols.size >= 5:
            ys.append(y)
            lefts.append(cols[0])
            rights.append(cols[-1])
    if len(ys) < 0.2 * h:
        return bgr
    ys = np.asarray(ys, np.float64)
    lefts = np.asarray(lefts, np.float64)
    rights = np.asarray(rights, np.float64)

    al, bl = _fit_margin_line(ys, lefts)
    ar, br = _fit_margin_line(ys, rights)

    yv = np.arange(h, dtype=np.float64)
    L = al * yv + bl
    R = ar * yv + br
    tgtL = float(np.median(L))
    tgtR = float(np.median(R))
    width = R - L
    width[width < 1.0] = 1.0
    scale = (tgtR - tgtL) / width

    xv = np.arange(w, dtype=np.float64)
    map_x = (tgtL + (xv[None, :] - L[:, None]) * scale[:, None]).astype(np.float32)
    map_y = np.repeat(yv[:, None], w, axis=1).astype(np.float32)
    return cv2.remap(bgr, map_x, map_y, interpolation=cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def dewarp_and_clean_pipeline(input_path, output_path):
    times = {}

    t = time.perf_counter()
    pil_img = Image.open(input_path).convert("RGB")
    times["load_image"] = time.perf_counter() - t

    t = time.perf_counter()
    unwarp = Unwarp(providers=["CPUExecutionProvider"])
    _force_int64_inputs(unwarp.bilinear_unwarping)
    times["model_load"] = time.perf_counter() - t

    t = time.perf_counter()
    unwarped = unwarp.inference(pil_img)
    times["inference"] = time.perf_counter() - t

    t = time.perf_counter()
    dewarped_bgr = cv2.cvtColor(np.array(unwarped), cv2.COLOR_RGB2BGR)
    dewarped_bgr = _devertical_trapezoid(dewarped_bgr)
    times["devertical"] = time.perf_counter() - t

    t = time.perf_counter()
    gray = cv2.cvtColor(dewarped_bgr, cv2.COLOR_BGR2GRAY)
    cleaned = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 115, 15)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cv2.imwrite(output_path, cleaned)
    times["cleanup_save"] = time.perf_counter() - t

    for k, dt in times.items():
        print(f"{k:14s}: {dt * 1e3:9.1f} ms")


if __name__ == "__main__":
    dewarp_and_clean_pipeline("wraped_page.jpg", "perfect_flat_scanned_page.jpg")