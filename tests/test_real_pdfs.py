"""Integration tests against the real PDFs in tests/assets/ (provided by the user):
  - test_pdf_native.pdf : large vector book -> 'normal'
  - test_pdf_scan.pdf   : distorted scans   -> 'scanned' (dewarp/clean/detect)

Each test skips if its asset is absent so the suite stays portable. The big book is
only ever opened + a couple of pages touched — never the full render.
"""
from __future__ import annotations

import numpy as np
import pytest

import fitz

from helpers import ASSETS, render_page_bgr
import core.imaging as imaging

BOOK = ASSETS / "test_pdf_native.pdf"
DISTORTED = ASSETS / "test_pdf_scan.pdf"

MODE_TEXT_MIN = 8


def _classify(doc, idx):
    """Per-page classification by vector data (§4): native if text ≥ MODE_TEXT_MIN or a vector
    drawing path; image-only otherwise."""
    page = doc[idx]
    native = len(page.get_text().strip()) >= MODE_TEXT_MIN or bool(page.get_drawings())
    return "normal" if native else "scanned"


# --------------------------------------------------------------- normal book PDF
@pytest.mark.skipif(not BOOK.exists(), reason="book-main.pdf not present")
class TestNormalBook:
    def test_opens_with_many_pages(self):
        with fitz.open(str(BOOK)) as doc:
            assert doc.page_count > 1

    def test_early_pages_classify_normal(self):
        with fitz.open(str(BOOK)) as doc:
            n = min(3, doc.page_count)
            assert any(_classify(doc, i) == "normal" for i in range(n))

    def test_vector_content_box_from_text_blocks(self):
        with fitz.open(str(BOOK)) as doc:
            page = doc[0]
            blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
            assert blocks                                   # real vector text present
            x0 = min(b[0] for b in blocks); x1 = max(b[2] for b in blocks)
            assert 0 <= x0 < x1 <= page.rect.width + 1


# ------------------------------------------------------ distorted scanned PDF
@pytest.mark.skipif(not DISTORTED.exists(), reason="test_pdf_distorted.pdf not present")
class TestDistortedScan:
    def test_pages_classify_scanned(self):
        with fitz.open(str(DISTORTED)) as doc:
            assert _classify(doc, 0) == "scanned"           # image-only: no text, no vector path
            assert len(doc[0].get_text().strip()) < MODE_TEXT_MIN
            assert not doc[0].get_drawings()

    def test_estimate_skew_runs(self):
        with fitz.open(str(DISTORTED)) as doc:
            bgr = render_page_bgr(doc, 0, dpi=120)
            ang = imaging.estimate_skew(bgr)
            assert -15.0 <= ang <= 15.0                     # clamped, finite

    @pytest.mark.skipif(not imaging.unwarp_available(),
                        reason="docuwarp / onnxruntime not installed")
    def test_real_dewarp_preserves_shape(self):
        with fitz.open(str(DISTORTED)) as doc:
            bgr = render_page_bgr(doc, 0, dpi=120)
            out = imaging.unwarp_bgr(bgr)
            assert out.shape == bgr.shape and out.dtype == np.uint8

    def test_clean_then_content_box(self):
        with fitz.open(str(DISTORTED)) as doc:
            bgr = render_page_bgr(doc, 0, dpi=120)
            bilevel = imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
            assert set(np.unique(bilevel)).issubset({0, 255})
            box = imaging.content_box(bilevel)
            assert box is not None
            x0, y0, x1, y1 = box
            h, w = bilevel.shape
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h  # a valid sub-region

    def test_grayscale_filter_runs(self):
        with fitz.open(str(DISTORTED)) as doc:
            bgr = render_page_bgr(doc, 0, dpi=120)
            out = imaging.sharpen_grayscale(bgr, amount=1.1)
            assert out.dtype == np.uint8 and out.ndim == 2 and out.shape == bgr.shape[:2]

    def test_detection_does_not_hit_page_border(self):
        """#5 regression: Sauvola-based detect must trim the tinted margin, not return the
        whole page (a global Otsu does, giving a page-border box)."""
        for i in (0, 3):
            with fitz.open(str(DISTORTED)) as doc:
                bgr = render_page_bgr(doc, i, dpi=120)
                H, W = bgr.shape[:2]
                bw = imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
                box = imaging.content_box(bw)
                assert box is not None
                x0, y0, x1, y1 = box
                # at least one dimension is clearly inside the page (not the full sheet)
                assert (x1 - x0) < 0.95 * W or (y1 - y0) < 0.95 * H
