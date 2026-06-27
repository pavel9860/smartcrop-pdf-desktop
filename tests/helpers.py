"""Test helpers: build a real sample PDF (vector + scanned pages) and render pages.

Kept dependency-light (fitz + PIL + numpy + cv2) and deterministic (fixed seeds) so the
generated PDF and rendered rasters are stable across runs.
"""
from __future__ import annotations

import io
import pathlib

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw

ASSETS = pathlib.Path(__file__).parent / "assets"


def text_image(w: int = 1240, h: int = 1754, lines: int = 32, angle: float = 0.0,
               noise: float = 0.0, seed: int = 0) -> np.ndarray:
    """A grayscale 'scanned page': glyph-like black bars on white, optionally rotated
    (to exercise deskew) and with additive Gaussian noise (to exercise cleaning)."""
    rng = np.random.default_rng(seed)
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    mx, my = int(w * 0.12), int(h * 0.10)
    step = (h - 2 * my) // lines
    for i in range(lines):
        x, y = mx, my + i * step
        for _ in range(int(rng.integers(6, 12))):
            wlen = int(rng.integers(30, 90))
            if x + wlen > w - mx:
                break
            draw.rectangle([x, y, x + wlen, y + int(step * 0.45)], fill=0)
            x += wlen + int(rng.integers(12, 28))
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    arr = np.array(img).astype(np.float32)
    if noise:
        arr = arr + rng.normal(0.0, noise, arr.shape)
    return np.clip(arr, 0, 255).astype(np.uint8)


def make_sample_pdf(path: pathlib.Path, normal_pages: int = 3,
                    scanned_pages: int = 2) -> pathlib.Path:
    """Write a multi-page PDF: `normal_pages` vector/text pages followed by
    `scanned_pages` raster pages (rotated, noisy). Returns the path."""
    doc = fitz.open()
    for i in range(normal_pages):
        page = doc.new_page(width=595, height=842)            # A4 in points
        page.insert_text((72, 80), f"SmartCrop test - normal page {i + 1}", fontsize=15)
        y = 120                                               # line-by-line: never clips
        for ln in range(40):
            page.insert_text((72, y), f"Line {ln + 1}: lorem ipsum dolor sit amet, "
                             "consectetur adipiscing elit.", fontsize=11)
            y += 16
    for j in range(scanned_pages):
        arr = text_image(angle=(7.0 if j == 0 else -4.0), noise=8.0, seed=100 + j)
        buf = io.BytesIO()
        Image.fromarray(arr).convert("RGB").save(buf, format="PNG")
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()
    return path


def render_page_bgr(doc: fitz.Document, idx: int, dpi: int = 150) -> np.ndarray:
    """Render a PDF page to an OpenCV BGR uint8 array."""
    pm = doc[idx].get_pixmap(dpi=int(dpi), alpha=False)
    rgb = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
