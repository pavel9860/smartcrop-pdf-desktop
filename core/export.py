"""Export job builders (spec §12.5–§12.7) — one page per `step()`, streaming (§14).

Extracted from `AppModel` so the model stays a facade. The builders take callables instead of the
model itself, so this module has no state and no model import: `render_outputs(i)` returns page
i's output image(s) through the one render path (§12.1), `is_bilevel(i)` says whether the page
carries the B/W filter (it decides the PDF embed encoder, §12.6).
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Callable

import fitz
from PIL import Image

from core.batch import PageJob
from core.constants import JPEG_QUALITY
from core.errors import ImagingError

FMT_EXT = {"PDF": "pdf", "JPG": "jpg", "PNG": "png", "TIFF": "tif"}

RenderOutputs = Callable[[int], list[Image.Image]]


def encode_pdf_stream(img: Image.Image, bilevel: bool) -> bytes:
    """Bytes for one embedded PDF page image: PNG for bilevel pages (lossless — JPEG rings on
    two-tone text), JPEG at `JPEG_QUALITY` for continuous tone (smaller, much faster) (§12.6)."""
    buf = io.BytesIO()
    if bilevel:
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def pdf_job(path: Path, pages: list[int], render_outputs: RenderOutputs,
            is_bilevel: Callable[[int], bool]) -> PageJob:
    """One PDF; each output page an embedded image page; garbage-collected + deflated on save."""
    out_doc = fitz.open()

    def step(i: int) -> None:                 # one page of pixels resident at a time (§12.5)
        for img in render_outputs(i):
            pg = out_doc.new_page(width=img.width, height=img.height)
            pg.insert_image(pg.rect, stream=encode_pdf_stream(img, is_bilevel(i)))

    def save() -> None:
        try:
            out_doc.save(str(path), garbage=4, deflate=True)
        except (OSError, RuntimeError) as exc:      # disk full / bad path → routed via Failed
            raise ImagingError(f"Export failed: {exc}") from exc
        finally:
            out_doc.close()

    def discard() -> None:                    # cancel before save → drop the in-progress doc
        if not out_doc.is_closed:
            out_doc.close()

    return PageJob("Exporting pages", pages, step, save, discard)


def images_job(path: Path, pages: list[int], fmt: str,
               render_outputs: RenderOutputs) -> PageJob:
    """One file per output page with an index suffix (§12.7); cancel deletes what was written."""
    stem, ext = os.path.splitext(str(path))[0], FMT_EXT[fmt]
    count = 0
    written: list[str] = []

    def step(i: int) -> None:
        nonlocal count
        for img in render_outputs(i):
            count += 1
            p = f"{stem}_{count:03d}.{ext}"
            if fmt == "JPG":
                img.save(p, "JPEG", quality=JPEG_QUALITY)
            elif fmt == "PNG":
                img.save(p, "PNG")
            else:
                img.save(p, "TIFF", compression="tiff_deflate")
            written.append(p)

    def discard() -> None:                    # cancel/failure → delete the files already written
        for p in written:
            try:
                os.remove(p)
            except OSError:
                pass

    return PageJob(f"Exporting {fmt}", pages, step, on_abort=discard)
