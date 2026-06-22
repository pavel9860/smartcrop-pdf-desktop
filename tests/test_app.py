"""Integration tests that drive the real TestUIApp headlessly (withdrawn Tk root, no
mainloop). They exercise behaviours that span the UI + logic: split → N× output pages,
keep-ratio, page-pattern resolution, the 'Current' button, delete and reset.

Skipped automatically if no display / Tk is available.
"""
from __future__ import annotations

import fitz
import pytest

ctk = pytest.importorskip("customtkinter")
import app as appmod                                   # noqa: E402
from app import TestUIApp as _App                      # aliased so pytest doesn't collect it
from geometry import Box, rotate_box_cw                # noqa: E402
from theme import SECONDARY                            # noqa: E402


@pytest.fixture()
def app(monkeypatch):
    # Dialogs must never block a headless run.
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(appmod.messagebox, name, lambda *a, **k: None)
    monkeypatch.setattr(appmod.messagebox, "askyesno", lambda *a, **k: True)
    try:
        root = ctk.CTk()
    except Exception as exc:                            # no display
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    a = _App(root)                                 # loads the 24-page synthetic doc
    yield a
    try:
        root.destroy()
    except Exception:
        pass


def _make_pdf_bytes(pages=5):
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((72, 72), f"page {i + 1}", fontsize=20)
    data = doc.tobytes()
    doc.close()
    return data


# --------------------------------------------------------------- split → N× pages (#4)
class TestSplitMultiplies:
    @pytest.mark.parametrize("n", [2, 4])
    def test_apply_commits_n_boxes_per_page(self, app, n):
        app.set_split(n)
        app.set_pages_mode("All")
        app.apply_crop()
        assert app._applied, "apply should commit crop state"
        assert all(len(v) == n for v in app._applied.values())
        assert len(app._applied) == app.page_count()

    @pytest.mark.parametrize("n", [2, 4])
    def test_output_images_yield_n_per_page(self, app, n):
        app.set_split(n)
        app.set_pages_mode("All")
        app.apply_crop()
        assert len(app._output_images(0)) == n         # N output images for one source page
        total = sum(len(app._output_images(i)) for i in range(app.page_count()))
        assert total == n * app.page_count()           # N× the source page count


# --------------------------------------------------------------- keep ratio (#14)
def test_keep_ratio_locks_height(app):
    app.set_pages_mode("All")
    app.detect_content()                               # synthetic/normal → synchronous
    assert app.auto_active
    app.keep_ratio_var.set(True)
    app.ratio_var.set("1.5")
    rect = app._crop_rect(0)
    assert rect is not None
    assert rect.width / rect.height == pytest.approx(1.5, abs=0.02)


# --------------------------------------------------------------- page pattern (#7, #9)
def test_pattern_slice_resolves(app):
    app.set_pages_mode("Selected")
    app.select_var.set("1:3, 5")
    assert app._resolve_pages() == [0, 1, 2, 4]

def test_current_button_selects_current_page(app):
    app.current_page = 6
    app._select_current()
    assert app.pages_mode == "select"
    assert app.select_var.get() == "7"
    assert app._resolve_pages() == [6]


# --------------------------------------------------------------- delete (#10)
def test_delete_pages_removes_them(app):
    app._open_path_bytes = None
    doc = fitz.open(stream=_make_pdf_bytes(5), filetype="pdf")
    app.doc = doc
    app._pdf_path = "mem.pdf"
    app._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
    app._reset_doc_state()
    app.set_pages_mode("Selected")
    app.select_var.set("2,4")                           # delete pages 2 and 4 (1-indexed)
    app.delete_pages()
    assert app.page_count() == 3


# --------------------------------------------------------------- reset (#11) / undo (#13)
def test_reset_document_clears_state(app):
    app.set_pages_mode("All")
    app.detect_content()
    assert app.auto_active
    app.reset_document()
    assert app.auto_active is False
    assert app._applied == {}

def test_default_undo_depth_is_four(app):
    assert app.undo_depth_var.get() == "4"


def _load_real(app, pages=5):
    doc = fitz.open(stream=_make_pdf_bytes(pages), filetype="pdf")
    app.doc = doc
    app._pdf_path = "mem.pdf"
    app._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
    app._reset_doc_state()
    return doc


# --------------------------------------------------------------- split keeps order/count (#1)
@pytest.mark.parametrize("n", [2, 4])
def test_split_output_pages_are_distinct_in_order(app, n):
    app.set_split(n)
    app.set_pages_mode("All")
    app.apply_crop()
    boxes = app._applied[0]
    assert boxes == list(app.crop_rects)                # committed in reading order, unaltered
    assert len(boxes) == n


# --------------------------------------------------------------- auto-detect not stuck (#2)
def test_autodetect_button_never_highlighted_and_repressable(app):
    app.set_pages_mode("All")
    app.detect_content()
    assert app.auto_active
    assert app.btn_detect.cget("fg_color") == SECONDARY     # neutral, not the active accent
    assert app.btn_detect.cget("state") == "normal"
    app.left_off.set(5.0)                                   # edit the crop, then re-detect
    app.detect_content()
    assert app.btn_detect.cget("state") == "normal"         # still available


# --------------------------------------------------------------- rotate preserves crop (#6)
def test_rotate_keeps_committed_crop_transformed(app):
    w, h = app._page_dims(0)
    app._applied[0] = [Box(50, 60, 200, 400)]
    app.set_pages_mode("Selected"); app.select_var.set("1")
    app.rotate_pages()
    assert 0 in app._applied                                # crop survives the turn
    assert app._applied[0] == [rotate_box_cw(Box(50, 60, 200, 400), w, h)]
    nw, nh = app._page_dims(0)
    b = app._applied[0][0]
    assert 0 <= b.x0 <= b.x1 <= nw and 0 <= b.y0 <= b.y1 <= nh


def test_rotate_then_undo_restores_crop(app):
    app._applied[0] = [Box(50, 60, 200, 400)]
    app.set_pages_mode("Selected"); app.select_var.set("1")
    app.rotate_pages()
    app.undo()
    assert app._rotation.get(0, 0) == 0
    assert app._applied[0] == [Box(50, 60, 200, 400)]


# --------------------------------------------------------------- offset clamp (#7)
def test_offsets_clamp_to_page_limits(app):
    app.set_pages_mode("All")
    app.detect_content()
    app.right_off.set(100000.0); app.bottom_off.set(100000.0); app.left_off.set(-100000.0)
    app._clamp_offsets()
    for v in (app.left_off.get(), app.right_off.get(), app.bottom_off.get()):
        assert -100.0 <= v <= 100.0                         # snapped back into range
    w, h = app._page_dims(0)
    rect = app._crop_rect(0)
    assert 0 <= rect.x0 and rect.x1 <= w + 0.01             # crop never leaves the page
    assert 0 <= rect.y0 and rect.y1 <= h + 0.01


def test_clamp_offsets_no_detection_bounds_to_hundred(app):
    app.right_off.set(5000.0)
    app._clamp_offsets()
    assert app.right_off.get() == 100.0


# --------------------------------------------------------------- delete reindex (#8)
def test_delete_preserves_kept_page_adjustments(app):
    _load_real(app, pages=5)
    app._applied[0] = [Box(1, 2, 3, 4)]                     # page 1 crop  → stays index 0
    app._applied[3] = [Box(5, 6, 7, 8)]                     # page 4 crop  → shifts to index 2
    app._rotation[4] = 90                                   # page 5 turn  → shifts to index 3
    app._processed[1] = {"clean": ("bw", 2)}                # page 2 filter → deleted
    app.set_pages_mode("Selected"); app.select_var.set("2")  # delete page 2 (idx 1)
    app.delete_pages()
    assert app.page_count() == 4
    assert app._applied == {0: [Box(1, 2, 3, 4)], 2: [Box(5, 6, 7, 8)]}
    assert app._rotation == {3: 90}
    assert 1 not in app._processed                          # the deleted page's filter is gone


# --------------------------------------------------------------- failure paths (#8)
def test_delete_all_pages_refused(app):
    _load_real(app, pages=3)
    app.set_pages_mode("All")
    app.delete_pages()
    assert app.page_count() == 3                            # refused to empty the document


def test_delete_empty_selection_is_noop(app):
    _load_real(app, pages=4)
    app.set_pages_mode("Selected"); app.select_var.set("99")  # out of range → empty
    app.delete_pages()
    assert app.page_count() == 4


def test_apply_split_requires_n_rectangles(app):
    app.set_split(2)
    app.crop_rects.clear()                                  # fewer than N → apply must refuse
    app.set_pages_mode("All")
    app.apply_crop()
    assert app._applied == {}
