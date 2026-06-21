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
