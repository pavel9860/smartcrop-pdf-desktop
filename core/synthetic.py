"""The synthetic placeholder document (spec §1) — pure helpers, deterministic per page index.

With no file open the app shows this demo so every control is usable immediately. Extracted from
`AppModel`: these functions own the fake page sizes, the fake text box detection reads, and the
fake page rasters; the model just calls them.
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw

from core.constants import SYNTH_PAGES
from core.geometry import Box


def page_sizes() -> list[tuple[float, float]]:
    rnd = random.Random(7)
    return [(600 + rnd.uniform(-15, 15), 820 + rnd.uniform(-20, 20))
            for _ in range(SYNTH_PAGES)]


def text_box(idx: int, w: float, h: float) -> Box:
    rnd = random.Random(idx * 17 + 3)
    return Box(w * (0.09 + rnd.uniform(-0.02, 0.03)), h * (0.10 + rnd.uniform(-0.02, 0.03)),
               w * (1 - 0.09 - rnd.uniform(-0.02, 0.03)),
               h * (1 - 0.13 - rnd.uniform(-0.03, 0.03)))


def page_image(idx: int, w: float, h: float, scanned: bool) -> Image.Image:
    img = Image.new("RGB", (int(w), int(h)), "white")
    dr = ImageDraw.Draw(img)
    rnd = random.Random(idx * 31 + 1)
    box = text_box(idx, w, h)
    if not scanned:
        y = box.y0
        while y < box.y1 - 10:
            dr.line([(box.x0, y), (box.x1 - rnd.uniform(0, w * 0.18), y)],
                    fill=(70, 70, 75), width=2)
            y += rnd.uniform(14, 20)
        dr.rectangle([box.x0, box.y0, box.x1, box.y1], outline=(210, 210, 215))
        return img
    dr.rectangle([box.x0, box.y0, box.x1, box.y1], fill=(60, 60, 65))
    for _ in range(40):
        x, yy = rnd.uniform(box.x0, box.x1), rnd.uniform(box.y0, box.y1)
        dr.ellipse([x, yy, x + 3, yy + 3], fill=(230, 230, 225))
    return img.rotate(rnd.uniform(-5, 5), fillcolor="white", resample=Image.Resampling.BICUBIC)
