"""Per-page content-box detection (spec §8) — pure, stateless helpers.

Extracted from `AppModel` so the model stays a facade: these take a document/raster and return a
`Box`; caching, aggregation into the union frame and history live in the model.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image

import core.imaging
from core.constants import DETECT_MAX_PX
from core.geometry import Box


def normal_page_box(doc: Any, idx: int, w: float, h: float) -> Box:
    """Union of the page's text blocks (§8 Normal); a page with no text → the full page rect."""
    blocks = [b for b in doc[idx].get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not blocks:
        return Box(0, 0, w, h)
    return Box(min(b[0] for b in blocks), min(b[1] for b in blocks),
               max(b[2] for b in blocks), max(b[3] for b in blocks))


def scanned_page_box(work: Image.Image, w: float, h: float) -> Box:
    """`content_box` over a Sauvola bilevel of the work raster, downscaled to `DETECT_MAX_PX`
    for speed (§8 Scanned); no ink → the full page rect."""
    bgr = cv2.cvtColor(np.array(work), cv2.COLOR_RGB2BGR)
    g0h, g0w = bgr.shape[:2]
    s = min(1.0, DETECT_MAX_PX / max(g0h, g0w))
    if s < 1.0:
        bgr = cv2.resize(bgr, (max(1, round(g0w * s)), max(1, round(g0h * s))),
                         interpolation=cv2.INTER_AREA)
    gh, gw = bgr.shape[:2]
    bw = core.imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
    t = core.imaging.content_box(bw)
    if t is None:
        return Box(0, 0, w, h)
    sx, sy = w / gw, h / gh
    return Box(t[0] * sx, t[1] * sy, t[2] * sx, t[3] * sy)
