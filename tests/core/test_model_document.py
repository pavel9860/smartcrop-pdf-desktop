"""Load / combine / classify / reset through AppModel (spec §4, §7.1a, §13; inv 17, 18)."""
from __future__ import annotations

import fitz
import pytest
from PIL import Image

from core.enums import Mode
from core.errors import DocumentLoadError
from core.model import AppModel


def _img(path, w, h):
    Image.new("RGB", (w, h), "white").save(str(path))
    return str(path)


def test_synthetic_doc_is_usable(model):
    assert model.page_count() == 24
    assert model.has_document
    assert model.mode == Mode.NORMAL


def test_text_pdf_classifies_normal(loaded):
    m = loaded(3)
    assert m.page_count() == 3
    assert m.mode == Mode.NORMAL


def test_all_images_classify_scanned(scanned):
    m = scanned(2)
    assert m.page_count() == 2
    assert m.mode == Mode.SCANNED            # inv 18: every page image-only ⇒ Scanned


def test_combine_pdf_and_images_in_order(text_pdf, tmp_path):
    pdf = text_pdf(3)                         # 3 native text pages
    img1 = _img(tmp_path / "b.png", 200, 320)
    img2 = _img(tmp_path / "c.jpg", 150, 400)
    m = AppModel()
    m.load_files([pdf, img1, img2])
    assert m.page_count() == 5               # 3 PDF pages + 1 per image, in order (inv 17)
    assert m.mode == Mode.NORMAL             # any native page ⇒ Normal (inv 18)
    assert m.doc[0].get_text().strip()       # the PDF pages came first
    assert not m.doc[3].get_text().strip()   # image page after, no text
    assert m.input_paths == [pdf, img1, img2]


def test_all_image_files_classify_scanned(tmp_path):
    imgs = [_img(tmp_path / f"s{i}.png", 200 + i, 300) for i in range(3)]
    m = AppModel()
    m.load_files(imgs)
    assert m.page_count() == 3
    assert m.mode == Mode.SCANNED


def test_load_clears_prior_state(loaded, run_job, text_pdf):
    m = loaded(4)
    run_job(m.detect_content())
    m.apply_crop()
    m.rotate_pages()
    assert m.auto_active and m.can_undo
    m.load_files([text_pdf(2, name="new.pdf")])
    assert m.page_count() == 2
    assert m.auto_active is False             # same clearing as Reset (§7.1, §13)
    assert m.can_undo is False
    assert m.current_page == 0


def test_bad_path_raises_document_load_error():
    m = AppModel()
    with pytest.raises(DocumentLoadError):
        m.load_files(["does-not-exist.pdf"])


def test_reset_recombines_input_files(loaded, run_job):
    m = loaded(3)
    run_job(m.detect_content())
    m.apply_crop()
    assert m.auto_active
    m.reset()
    assert m.page_count() == 3
    assert m.auto_active is False             # re-opened, crops cleared (inv 4)
    assert m.can_undo is False


def test_reset_synthetic_returns_to_demo(model, run_job):
    run_job(model.detect_content())
    assert model.auto_active
    model.reset()
    assert model.page_count() == 24
    assert model.auto_active is False


def test_combined_doc_page_count_matches(text_pdf, tmp_path):
    pdf = text_pdf(2)
    combined = AppModel._combine_files([pdf, _img(tmp_path / "x.png", 100, 100)])
    try:
        assert combined.page_count == 3
    finally:
        combined.close()
    assert isinstance(combined, fitz.Document)
