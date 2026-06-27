"""Pure page-rendering helpers shared by the on-screen preview and the PDF export, so
**what you see is what you save** (WYSIWYG). No Tk — PIL only, fully unit-testable.
"""
from __future__ import annotations

import io
from typing import Optional, Tuple

from PIL import Image

from core.geometry import Box


def pil_to_png_bytes(img: Image.Image) -> bytes:
    """Encode a PIL image as PNG bytes (for embedding into an exported PDF page)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def crop_to_box(img: Image.Image, box: Box, page_w: float, page_h: float) -> Image.Image:
    """Crop `img` (rendered from a page sized page_w×page_h) to `box`, given in page units."""
    sx, sy = img.width / page_w, img.height / page_h
    return img.crop((round(box.x0 * sx), round(box.y0 * sy),
                     round(box.x1 * sx), round(box.y1 * sy)))


def resize_to(img: Image.Image, target: Optional[Tuple[float, float]]) -> Image.Image:
    """Resample `img` to `target` (w, h) if given and different; otherwise return it as-is."""
    if target is None:
        return img
    tw, th = max(1, round(target[0])), max(1, round(target[1]))
    if (tw, th) == (img.width, img.height):
        return img
    return img.resize((tw, th), Image.LANCZOS)


def desaturate(img: Image.Image) -> Image.Image:
    """Drop colour but keep the full tonal range — grayscale ('L'), NOT a bilevel threshold
    (Output colours = Grayscale, §7.6). Already-grayscale images pass through unchanged."""
    return img if img.mode == "L" else img.convert("L")


def output_image(work: Image.Image, box: Box, page_w: float, page_h: float,
                 target: Optional[Tuple[float, float]] = None,
                 remove_colours: bool = False) -> Image.Image:
    """The exact image one output page becomes: crop `work` to `box`, resize to `target`
    (Compress, §12.6), then optionally desaturate (Output colours, applied last, §12.1).
    Called by BOTH the preview and the exporter so the two never diverge (WYSIWYG)."""
    out = resize_to(crop_to_box(work, box, page_w, page_h), target)
    return desaturate(out) if remove_colours else out


def fit_scale(content_w: float, content_h: float, canvas_w: int, canvas_h: int,
              margin: int) -> float:
    """Largest scale fitting content_w×content_h into the canvas (minus margin), aspect kept."""
    return min((canvas_w - margin) / content_w, (canvas_h - margin) / content_h)
