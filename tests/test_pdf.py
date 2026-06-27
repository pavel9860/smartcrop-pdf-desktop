"""End-to-end check on a real generated PDF: classify pages, then run the scanned
pipeline (deskew → bilevel → content box) on a rendered raster page."""
from __future__ import annotations

import fitz

from helpers import make_sample_pdf, render_page_bgr
import core.imaging as imaging
from core.document import DocumentMixin

MODE_TEXT_MIN = 8


def _classify(doc, idx):
    """Per-page classification by vector data (§4): native (Normal) if the page has real text
    (≥ MODE_TEXT_MIN) or any vector drawing path; image-only (Scanned) otherwise."""
    page = doc[idx]
    native = len(page.get_text().strip()) >= MODE_TEXT_MIN or bool(page.get_drawings())
    return "normal" if native else "scanned"


def test_sample_pdf_written(sample_pdf_path):
    assert sample_pdf_path.exists()
    assert sample_pdf_path.stat().st_size > 1000
    with fitz.open(str(sample_pdf_path)) as doc:
        assert doc.page_count == 5                      # 3 normal + 2 scanned


def test_normal_pages_have_vector_text(sample_doc):
    for i in range(3):
        assert len(sample_doc[i].get_text().strip()) > 50
        assert _classify(sample_doc, i) == "normal"


def test_scanned_pages_classified_scanned(sample_doc):
    for i in (3, 4):                                     # image-only: no text, no vector path
        assert len(sample_doc[i].get_text().strip()) < MODE_TEXT_MIN
        assert not sample_doc[i].get_drawings()
        assert _classify(sample_doc, i) == "scanned"


def test_combine_pdf_and_images_builds_one_document(tmp_path):
    from PIL import Image
    pdf = make_sample_pdf(tmp_path / "doc.pdf", normal_pages=2, scanned_pages=0)
    png = tmp_path / "p.png"; Image.new("RGB", (200, 320), "white").save(png)
    jpg = tmp_path / "q.jpg"; Image.new("RGB", (150, 400), "white").save(jpg)
    combined = DocumentMixin._combine_files([str(pdf), str(png), str(jpg)])
    try:
        assert combined.page_count == 4                 # 2 PDF pages then 1 page per image
        assert combined[0].get_text().strip()           # PDF pages first (carry text)
        assert not combined[2].get_text().strip()       # image pages last (no text)
    finally:
        combined.close()


def test_scanned_page_deskews(sample_doc):
    bgr = render_page_bgr(sample_doc, 3)                # injected +7° rotation
    est = imaging.estimate_skew(bgr)
    assert abs(est) >= 1.0                              # skew is detected
    fixed = imaging.deskew(bgr, est)
    assert abs(imaging.estimate_skew(fixed)) <= abs(est)


def test_scanned_pipeline_produces_content_box(sample_doc):
    bgr = render_page_bgr(sample_doc, 4)
    fixed, _ = imaging.deskew_auto(bgr)
    bilevel = imaging.clean_document_bilevel(fixed, strength=2, upscale=1.0)
    assert set(__import__("numpy").unique(bilevel)).issubset({0, 255})
    box = imaging.content_box(bilevel)
    assert box is not None
    x0, y0, x1, y1 = box
    assert x1 > x0 and y1 > y0
    h, w = bilevel.shape
    assert (x1 - x0) < w and (y1 - y0) < h              # tighter than the full page
