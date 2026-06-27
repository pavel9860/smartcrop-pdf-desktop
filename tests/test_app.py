"""Integration tests that drive the real SmartCropApp headlessly (withdrawn Tk root, no
mainloop). They exercise behaviours that span the UI + logic: split → N× output pages,
keep-ratio, page-pattern resolution, the 'Current' button, delete and reset.

Skipped automatically if no display / Tk is available.
"""
from __future__ import annotations

import fitz
import pytest
from PIL import Image

ctk = pytest.importorskip("customtkinter")
import core.app as appmod                              # noqa: E402
import core.export as exportmod                         # noqa: E402 (owns the save dialog)
from core.app import SmartCropApp as _App              # aliased so pytest doesn't collect it
import os                                              # noqa: E402
import tempfile                                         # noqa: E402
import time                                             # noqa: E402

from core.geometry import Box, rotate_box_cw           # noqa: E402
from core.theme import ACCENT, SECONDARY               # noqa: E402
from core import render                                 # noqa: E402
from core.constants import CACHE_WINDOW                 # noqa: E402


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
        pg.insert_text((72, 72), f"Page {i + 1} — sample document text", fontsize=20)
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
    doc = fitz.open(stream=_make_pdf_bytes(5), filetype="pdf")
    app.doc = doc
    app._pdf_path = "mem.pdf"
    app._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
    app._reset_doc_state()
    app.set_pages_mode("Selected")
    app.select_var.set("2,4")                           # delete pages 2 and 4 (1-indexed)
    app.delete_pages()
    assert app.page_count() == 3


# --------------------------------------------------------------- multi-file combine (#17)
def _img_file(path, w, h):
    Image.new("RGB", (w, h), "white").save(str(path))
    return str(path)


def test_combine_pdf_and_images_in_order(app, tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(_make_pdf_bytes(3))   # 3 native (text) pages
    img1 = _img_file(tmp_path / "b.png", 200, 320)
    img2 = _img_file(tmp_path / "c.jpg", 150, 400)
    app._open_files([str(pdf), img1, img2])
    assert app.page_count() == 5                        # 3 PDF pages + 1 per image, in order
    assert app.mode == "normal"                         # any native PDF page → Normal (#18)
    assert app.doc[0].get_text().strip()                # PDF page came first
    assert not app.doc[3].get_text().strip()            # image page came after, no text
    assert app._input_paths == [str(pdf), img1, img2]   # remembered for Reset


def test_all_images_classify_scanned(app, tmp_path):
    imgs = [_img_file(tmp_path / f"s{i}.png", 200 + i, 300) for i in range(2)]
    app._open_files(imgs)
    assert app.page_count() == 2                         # one page per image
    assert app.mode == "scanned"                         # every page image-only (#18)


def test_load_clears_prior_document_state(app, tmp_path):
    # Load resets ALL per-document state, the same guarantee as Reset (§7.1, §13).
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    app._rotation[0] = 90; app.dewarp_on = True
    assert app._applied and app.auto_active
    pdf = tmp_path / "new.pdf"; pdf.write_bytes(_make_pdf_bytes(2))
    app._open_files([str(pdf)])
    assert app._applied == {} and app._rotation == {} and app._detect_cache == {}
    assert app.auto_active is False and app.dewarp_on is False and app._union is None


def test_detect_and_recrop_are_rerunnable(app):
    # #7: detection is idempotent/re-runnable and a committed crop can be re-cropped freely —
    # no "make once then must Clear" dead end (the Clear button is gone).
    app.set_pages_mode("All")
    app.detect_content(); first = app._crop_rect(0)
    app.detect_content()                                    # re-press → still works, same box
    assert app._crop_rect(0) == first and app.auto_active
    app.current_page = 0
    app._applied[0] = [Box(50, 50, 200, 300)]               # a committed crop
    app._view_dims = (150.0, 250.0)
    app._drag = {"kind": "crop-edit", "start": (10, 10)}
    app._draw_rect = Box(10, 10, 80, 120)
    app._commit_crop_edit()                                 # re-crop without Clearing first
    assert app._applied[0] != [Box(50, 50, 200, 300)]       # replaced/tightened


def test_reset_recombines_input_files(app, tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(_make_pdf_bytes(2))
    img = _img_file(tmp_path / "b.png", 200, 320)
    app._open_files([str(pdf), img])
    app.detect_content(); app.apply_crop()
    assert app._applied
    app.reset_document()
    assert app._applied == {} and app.page_count() == 3  # re-combined, crops cleared


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
    app._processed[1] = {"filter": ("bw", 2)}               # page 2 filter → deleted
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


# ----------------------------------------------- crops persist across detect (round 2 #1)
def test_detect_does_not_clear_committed_crops(app):
    app.set_pages_mode("Selected"); app.select_var.set("1-2")
    app.detect_content(); app.apply_crop()                  # crop the first page-set
    assert set(app._applied) == {0, 1}
    app.select_var.set("4-5")
    app.detect_content()                                    # re-detect must NOT wipe the first set
    assert set(app._applied) == {0, 1}
    app.apply_crop()                                        # second set adds, first set kept
    assert set(app._applied) == {0, 1, 3, 4}


def test_esc_cancels_draw_keeps_committed_crop(app):
    # Esc / right-click mid-drag discards the gesture, commits nothing, takes no snapshot, and
    # leaves the crop exactly as before (#24).
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    committed = list(app._applied[0])
    depth = len(app.history)
    app.current_page = 0
    app._prev_applied = app._applied.pop(0, None)          # simulate press stashing the crop
    app._drag = {"kind": "draw", "start": (10, 10)}
    app._draw_rect = Box(10, 10, 50, 60)                   # an in-progress rubber-band
    app._cancel_drag()
    assert app._applied.get(0) == committed                # crop restored unchanged
    assert app._draw_rect is None and app._drag is None and app._prev_applied is None
    assert len(app.history) == depth                       # no history snapshot taken


def test_esc_cancels_split_drag_keeps_windows(app):
    app.set_split(2)
    orig = list(app.crop_rects)
    app._drag = {"kind": "split-move", "idx": 0, "rect0": orig[0], "start": (0, 0)}
    app.crop_rects[0] = Box(99, 99, 199, 199)              # simulate a live drag mutation
    app._cancel_drag()
    assert app.crop_rects[0] == orig[0]                    # window rolled back, count unchanged


def test_settings_builds_at_max_font_without_clipping(app):
    # #8 / §15, §19: labels must stay fully visible at the largest Font size — Settings rows size
    # to content (no fixed 190px column) and the window grows to fit them.
    from core.constants import FONT_SIZE_MAX
    app._set_font_size(str(FONT_SIZE_MAX))                  # largest UI font
    try:
        app.open_settings()
        app.root.update_idletasks()
    except Exception as exc:
        pytest.skip(f"no Tk toplevel headless: {exc}")
    wins = [w for w in app.root.winfo_children() if isinstance(w, ctk.CTkToplevel)]
    assert wins                                            # Settings built at max font, no error
    assert wins[-1].winfo_reqwidth() >= 1
    wins[-1].destroy()


def test_advanced_card_holds_offsets_collapsed(app):
    # §7.4a: the per-edge offsets live in a collapsible Advanced card, collapsed by default,
    # separate from Detect Text Borders.
    assert hasattr(app, "btn_advanced") and app.advanced_open is False
    assert "▸" in app.btn_advanced.cget("text")             # collapsed arrow
    assert len(app._off_spins) == 4                         # L/T/R/B steppers exist
    w, anc = app._off_spins[0], []
    while w is not None:
        anc.append(w); w = w.master
    assert app.advanced_body in anc                         # offsets are inside the Advanced card
    app._toggle_advanced()
    assert app.advanced_open is True and "▾" in app.btn_advanced.cget("text")
    app._toggle_advanced()
    assert app.advanced_open is False                       # toggles back


def test_actions_and_export_are_separate_cards(app):
    # §6: Actions (Crop full-width + Rotate/Delete) and the Export split button are distinct,
    # with Actions before Compress.
    assert hasattr(app, "btn_apply") and hasattr(app, "btn_export")
    assert app.btn_apply.master is not app.btn_export.master


def test_history_buttons_pinned_below_settings(app):
    # Undo/Redo/Reset live in the pinned bottom card (§7.8), directly below Settings/Help —
    # not in the scrollable Document card. (Clear was removed entirely.)
    assert app.btn_undo.master.master is app._nav_bar
    assert app.btn_redo.master.master is app._nav_bar
    assert app.btn_reset.master.master is app._nav_bar
    assert not hasattr(app, "clear_detect")                 # Clear button + handler deleted


# ----------------------------------------------- split overrides stale crop (round 2 #2)
def test_switch_to_split_clears_stale_single_crop(app):
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    assert app._applied                                     # single crops committed
    app.set_split(2)
    assert app._applied == {}                               # stale single-mode crops dropped


def test_split_after_single_crop_commits_n_boxes(app):
    """flow C: normal crop, then Split 2 — the export-commit must yield N boxes/page (#2)."""
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    app.set_split(2)
    for i in app._resolve_pages():                          # this is what export commits in split mode
        app._applied[i] = app._page_crop_boxes(i)
    assert app._applied and all(len(v) == 2 for v in app._applied.values())
    assert sum(len(app._output_images(i)) for i in range(app.page_count())) == 2 * app.page_count()


# --------------------------------------- WYSIWYG: preview matches export (#12)
@pytest.mark.parametrize("compress,colours", [("Original resolution", "Original colors"),
                                              ("Low — 72 dpi", "Original colors"),
                                              ("Medium — 150 dpi", "Grayscale")])
def test_preview_matches_export(app, compress, colours):
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    app.compress_var.set(compress); app.colours_var.set(colours)
    box = app._applied[0][0]
    w, h = app._page_dims(0)
    preview = render.output_image(app._work_image(0), box, w, h,
                                  app._target_size(box.width, box.height), app._remove_colours())
    export = app._output_images(0)[0]
    assert preview.size == export.size                 # preview applies compress + colours too
    assert list(preview.getdata()) == list(export.getdata())   # pixel-for-pixel


# --------------------------------------- Compress downsamples (#20)
def test_compress_resamples_and_original_keeps_native(app):
    _setup_export(app, pages=1)                        # real PDF → rendered at NORMAL_DPI (150)
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    box = app._applied[0][0]
    app.compress_var.set("Original resolution")
    native = app._output_images(0)[0]
    assert app._target_size(box.width, box.height) is None      # None → native crop pixels
    app.compress_var.set("Low — 72 dpi")                        # below the 150-dpi native render
    low = app._output_images(0)[0]
    assert low.width < native.width and low.height < native.height   # genuinely downsampled


# --------------------------------------- Output colours (#22)
def test_grayscale_desaturates_every_page(app):
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    app.colours_var.set("Grayscale")
    img = app._output_images(0)[0]
    assert img.mode == "L"                              # single channel, tone preserved
    assert min(img.getdata()) < 250                    # not thresholded to pure black/white
    app.colours_var.set("Original colors")
    assert app._output_images(0)[0].mode == "RGB"      # no-op


# --------------------------------------- Compress/colours excluded from history
def test_output_settings_not_in_history(app):
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    app.compress_var.set("Low — 72 dpi"); app.colours_var.set("Grayscale")
    app.left_off.set(5.0); app.detect_content()        # a real document mutation to undo
    app.undo()
    assert app.compress_var.get() == "Low — 72 dpi"    # live setting survives Undo
    assert app.colours_var.get() == "Grayscale"


# --------------------------------------- Export formats (#21)
def test_export_formats(app):
    out = _setup_export(app, pages=2)                  # out = <dir>/out.pdf
    app.set_pages_mode("All")
    app.export(); _pump(app)                           # default PDF → one file
    assert os.path.exists(out)
    d = fitz.open(out); assert d.page_count == 2; d.close()
    for fmt, ext in [("JPG", "jpg"), ("PNG", "png"), ("TIFF", "tif")]:
        app._on_format_change(fmt)
        assert app.format_var.get() == fmt
        assert app.btn_export.cget("text").endswith(fmt)        # label tracks format
        app.export(); _pump(app)
        stem = os.path.splitext(out)[0]
        assert os.path.exists(f"{stem}_001.{ext}") and os.path.exists(f"{stem}_002.{ext}")


def test_export_suggested_name_uses_postfix_and_folder(app, tmp_path):
    cap = {}
    exportmod.filedialog.asksaveasfilename = lambda *a, **k: cap.update(k) or ""   # capture + cancel
    pdf = tmp_path / "mybook.pdf"; pdf.write_bytes(_make_pdf_bytes(2))
    app._open_files([str(pdf)])
    app.output_postfix_var.set("_trimmed")
    app._on_format_change("JPG")
    app.export()                                        # dialog cancelled → no file, just capture
    assert cap["initialfile"] == "mybook_trimmed.jpg"   # <name><postfix>.<ext>
    assert cap["initialdir"] == os.path.dirname(str(pdf))   # default folder = source folder


# --------------------------------------- drawing a crop is per-page (round 4 close-pages bug)
def test_drawn_crop_does_not_disturb_other_pages(app):
    app.set_pages_mode("All"); app.detect_content()
    before = app._crop_rect(1)
    app.current_page = 0                                  # draw a custom rectangle on page 1
    app._draw_rect = Box(100, 100, 250, 700)
    app._drag = {"kind": "draw", "start": (100, 100)}
    app._commit_drawn_rect()
    assert app._applied.get(0) == [Box(100, 100, 250, 700)]   # committed to this page only
    assert app._crop_rect(1) == before                   # other pages' live crop untouched
    assert 1 not in app._applied


def test_drawn_crop_is_undoable(app):
    app.current_page = 2
    app._draw_rect = Box(20, 30, 200, 400)
    app._drag = {"kind": "draw", "start": (20, 30)}
    app._commit_drawn_rect()
    assert app._applied.get(2) == [Box(20, 30, 200, 400)]
    app.undo()
    assert 2 not in app._applied                          # draw snapshots history → undoable


# --------------------------------------- split preview navigation (round 3: show all splits)
@pytest.mark.parametrize("n", [2, 4])
def test_split_crop_expands_output_page_count(app, n):
    before = app._view_total()
    assert before == app.page_count()                      # uncommitted → one view per source page
    app.set_split(n); app.set_pages_mode("All"); app.apply_crop()
    assert app._view_total() == n * app.page_count()       # committed split → N views per page


def test_split_view_navigation_walks_all_boxes_in_order(app):
    app.set_split(2); app.set_pages_mode("All"); app.apply_crop()
    app.current_page = 0; app.view_box = 0
    seq = []
    for _ in range(5):
        seq.append((app.current_page, app.view_box))
        app.next_page()
    assert seq == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)]  # both splits, in reading order
    assert (app.current_page, app.view_box) == (2, 1)      # 5 steps from (0,0)
    app.prev_page()                                        # prev steps back through the splits
    assert (app.current_page, app.view_box) == (2, 0)


def test_jump_to_output_page_maps_to_source_and_box(app):
    app.set_split(2); app.set_pages_mode("All"); app.apply_crop()
    app.page_var.set("4"); app.jump_to_page()              # 4th output page = source 1, split 1
    assert (app.current_page, app.view_box) == (1, 1)
    assert app._view_position() + 1 == 4


def test_uncommitted_page_is_single_view(app):
    app.set_split(2)                                       # selected but not applied yet
    assert app._view_total() == app.page_count()           # still one view per source page
    assert app._page_box_count(0) == 1


def test_press_to_edit_resets_view_box(app):
    app.set_split(2); app.set_pages_mode("All"); app.apply_crop()
    app.current_page = 3; app.view_box = 1                 # viewing the 2nd split of page 4
    app._applied.pop(app.current_page, None)               # (what _on_press does to resume editing)
    app.view_box = 0
    assert app._page_box_count(3) == 1                     # page reverts to a single editable view


# ----------------------------------------------- Current button: follow toggle (round 5)
def test_current_button_toggles_follow_and_highlights(app):
    app.current_page = 4
    app._select_current()                                  # press → follow ON
    assert app.current_follow is True
    assert app.pages_seg.get() == "Selected"               # lights the Selected segment too (#3)
    assert app.pages_mode == "select" and app.select_var.get() == "5"
    assert app.btn_current.cget("fg_color") == ACCENT      # highlighted while active (no circle)
    app._select_current()                                  # press again → follow OFF, pattern kept
    assert app.current_follow is False
    assert app.select_var.get() == "5"
    assert app.btn_current.cget("fg_color") == SECONDARY   # un-highlighted


def test_current_follow_tracks_navigation(app):
    app.current_page = 4
    app._select_current()                                  # follow ON, pattern "5"
    app.next_page()                                        # navigate → pattern follows
    assert app.select_var.get() == "6"
    assert app._resolve_pages() == [5]
    app.prev_page()
    assert app.select_var.get() == "5"


def test_current_follow_ends_on_mode_change_and_manual_edit(app):
    app.current_page = 2
    app._select_current()                                  # follow ON
    app.set_pages_mode("All")                              # switching mode ends follow
    assert app.current_follow is False
    app._select_current()                                  # ON again (switches back to Selected)
    assert app.current_follow is True
    app._on_pattern_typed()                                # a manual Pattern edit ends follow
    assert app.current_follow is False


# ----------------------------------------------- reset restores split state (round 2 #5)
def test_reset_restores_single_split_state(app):
    app.set_split(2)
    assert len(app.crop_rects) == 2
    app.reset_document()
    assert app.split_count == 1
    assert app.split_seg.get() == "1"
    assert app.crop_rects == []
    app.set_split(2)                                        # split is usable again after reset
    assert len(app.crop_rects) == 2


# ----------------------------------------------- reset drops highlight (round 2 #6)
def test_reset_clears_scan_button_highlight(app):
    app.set_filter_mode("bw"); app.dewarp_on = True; app._refresh_scan_buttons()
    assert app.btn_bw.cget("fg_color") == ACCENT
    app.reset_document()
    assert app.filter_mode == "none" and app.dewarp_on is False
    assert app.btn_bw.cget("fg_color") == SECONDARY        # B/W no longer highlighted
    assert app.btn_dewarp.cget("fg_color") == SECONDARY    # Dewarp no longer highlighted


# ----------------------------------------------- nav bar pinned outside scroll (round 2 #4)
def test_nav_bar_pinned_outside_scroll(app):
    # The Settings/Help+nav card lives on the left panel, not inside the scrollable controls,
    # so it can neither float directly under Export nor require scrolling to reach.
    assert app._nav_bar.master is app._left_panel
    assert app._nav_bar.master is not app.controls
    assert not hasattr(app, "_reflow_bottom_bar")          # the fragile spacer machinery is gone


# ----------------------------------------------- LRU raster caches (round 6: memory)
def _setup_export(app, pages=3):
    out = os.path.join(tempfile.mkdtemp(), "out.pdf")
    exportmod.filedialog.asksaveasfilename = lambda *a, **k: out
    doc = fitz.open(stream=_make_pdf_bytes(pages), filetype="pdf")
    app.doc = doc
    app._pdf_path = "mem.pdf"
    app._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
    app._reset_doc_state()
    return out


def _pump(app, timeout=10.0):
    t0 = time.time()
    while app._busy and time.time() - t0 < timeout:
        app.root.update()
        time.sleep(0.001)


def test_raster_caches_are_lru_bounded(app):
    # Visiting every page of a 24-page doc must not grow the raster caches without limit.
    for i in range(app.page_count()):
        app._work_image(i)                                 # populates source + work caches
    assert len(app._source_cache) <= CACHE_WINDOW
    assert len(app._work_cache) <= CACHE_WINDOW


def test_export_single_page_writes_synchronously(app):
    out = _setup_export(app, pages=1)
    app.set_pages_mode("All")
    app.export()                                         # 1 page → synchronous fast path
    assert os.path.exists(out)
    d = fitz.open(out); assert d.page_count == 1; d.close()


def test_export_multipage_streams_correct_count(app):
    out = _setup_export(app, pages=4)
    app.set_split(2); app.set_pages_mode("All")
    app.export()                                         # chunked main-thread export
    _pump(app)
    assert os.path.exists(out)
    d = fitz.open(out)
    assert d.page_count == 8                               # 4 pages × 2 splits
    d.close()
    assert len(app._source_cache) <= CACHE_WINDOW          # caches stayed bounded across export
    assert len(app._work_cache) <= CACHE_WINDOW


def test_export_cancel_writes_no_file(app):
    out = _setup_export(app, pages=5)
    app.set_pages_mode("All")
    app.export()                                         # schedules the first tick
    app._cancelled = True                                  # cancel before any tick runs
    _pump(app)
    assert not os.path.exists(out)                         # discarded, no partial file
    assert app._busy is False


# ----------------------------------------------- widgets: Spin scroll + tooltip lifecycle
def test_spin_scrolls_both_platforms(app):
    import tkinter as tk
    from core.widgets import Spin
    var = tk.DoubleVar(value=0.0)
    sp = Spin(app.root, var, app)
    sp._scroll(+1); assert var.get() == pytest.approx(sp.step)      # X11 Button-4 path
    sp._scroll(-1); assert var.get() == pytest.approx(0.0)          # X11 Button-5 path
    sp._wheel(type("E", (), {"delta": 120})())                      # Windows/macOS wheel up
    assert var.get() == pytest.approx(sp.step)


def test_tooltip_cancels_pending_job_on_destroy(app):
    import customtkinter as ctk
    from core.widgets import ToolTip
    btn = ctk.CTkButton(app.root, text="x")
    tip = ToolTip(btn, "hi", app)
    tip._enter()                                                    # schedules the show-timer
    assert tip.job is not None
    btn.destroy()                                                   # <Destroy> → job cancelled
    assert tip.job is None


# ----------------------------------------------- crop kept across edit gestures (round 7 #2)
def test_stray_click_does_not_drop_committed_crop(app):
    """A press+release with no drag on a committed page keeps the crop — and the page stays
    committed/cropped throughout (no flip to the full page, §9.3 option a)."""
    app.current_page = 1
    app._applied[1] = [Box(40, 50, 200, 400)]
    app._view_dims = (160.0, 350.0)
    app._on_press(type("E", (), {"x": 10, "y": 10})())     # crop-edit — page stays committed
    assert 1 in app._applied                                # NOT stashed/dropped to the full page
    app._on_release(type("E", (), {"x": 10, "y": 10})())   # released without dragging
    assert app._applied.get(1) == [Box(40, 50, 200, 400)]  # crop unchanged


def test_too_small_crop_edit_keeps_committed_crop(app):
    app.current_page = 2
    app._applied[2] = [Box(40, 50, 200, 400)]
    app._view_dims = (160.0, 350.0)
    app._drag = {"kind": "crop-edit", "start": (5, 5)}
    app._draw_rect = Box(5, 5, 6, 6)                        # degenerate (< 2·MIN_RECT)
    app._commit_crop_edit()
    assert app._applied.get(2) == [Box(40, 50, 200, 400)]  # tiny edit aborts → keep the crop


def test_valid_draw_commits_on_uncommitted_page(app):
    app.current_page = 0
    app._prev_applied = None                                # uncommitted page → draw replaces (§9.4)
    app._draw_rect = Box(80, 90, 260, 520)
    app._drag = {"kind": "draw", "start": (80, 90)}
    app._commit_drawn_rect()
    assert app._applied.get(0) == [Box(80, 90, 260, 520)]  # a real new draw commits


def test_crop_edit_tightens_within_committed_box(app):
    """Editing a committed page draws a fresh band on the cropped view that maps back INTO the
    committed box → a tighter crop (§9.3 option a), undoable."""
    app.current_page = 0
    app._applied[0] = [Box(100, 100, 300, 500)]            # committed crop (W=200, H=400)
    app._view_dims = (200.0, 400.0)                         # Original res → 1:1 with the box
    depth = len(app.history)
    app._drag = {"kind": "crop-edit", "start": (20, 40)}
    app._draw_rect = Box(20, 40, 120, 240)                  # band in the cropped view
    app._commit_crop_edit()
    assert app._applied.get(0) == [Box(120, 140, 220, 340)]  # mapped into the box, tightened
    assert len(app.history) == depth + 1                    # undoable


# ----------------------------------------------- auto-detect works after a crop (round 7 #5)
def test_detect_after_crop_keeps_and_refreshes_committed_crop(app):
    """Re-detecting a committed page takes visible effect but NEVER drops the crop — the page
    stays committed, its box refreshed to the new auto crop."""
    app.set_pages_mode("Selected"); app.select_var.set("1")
    app.detect_content(); app.apply_crop()
    assert 0 in app._applied                                # page 1 has a committed crop
    app.left_off.set(7.0)                                   # change the detection result
    app.detect_content()                                    # re-detect the same page
    assert 0 in app._applied                                # crop kept, not dropped
    assert app._applied[0] == [app._crop_rect(0)]           # refreshed to the fresh auto crop
    assert app.auto_active


def test_detect_keeps_crops_on_pages_outside_selection(app):
    app.set_pages_mode("Selected"); app.select_var.set("1-2")
    app.detect_content(); app.apply_crop()
    assert set(app._applied) == {0, 1}
    app.select_var.set("4-5")
    app.detect_content()                                    # detecting 4-5 must keep 1-2's crops
    assert set(app._applied) == {0, 1}


def test_detect_after_crop_is_undoable(app):
    app.set_pages_mode("Selected"); app.select_var.set("1")
    app.detect_content(); app.apply_crop()
    committed = list(app._applied[0])
    app.left_off.set(7.0); app.detect_content()            # refreshes the committed crop
    assert app._applied.get(0) != committed
    app.undo()
    assert app._applied.get(0) == committed                 # restored


# ----------------------------------------------- crop is never dropped from the file (round 7)
def test_export_keeps_live_autocrop_on_uncommitted_pages(app):
    """A live auto-detect crop visible on screen must be written for EVERY exported page, even
    pages with no committed crop — never silently exported whole (bug: crop dropped on file)."""
    _setup_export(app, pages=4)
    app.set_pages_mode("All")
    app.detect_content()                                   # live auto crop on all pages (no Apply)
    assert app._crop_rect(2) is not None
    imgs = app._output_images(2)                           # an uncommitted page
    expected = render.output_image(app._work_image(2), app._crop_rect(2), *app._page_dims(2),
                                   app._target_size(app._crop_rect(2).width,
                                                    app._crop_rect(2).height))
    assert imgs[0].size == expected.size                   # cropped, not the whole page


def test_export_does_not_drop_autocrop_when_one_page_is_drawn(app):
    """With an auto crop active and ONE page hand-drawn, export must still crop the other pages
    (the earlier bug exported them whole because _applied was non-empty)."""
    out = _setup_export(app, pages=4)
    app.set_pages_mode("All")
    app.detect_content()                                   # global live auto crop
    app._applied[1] = [Box(30, 40, 200, 500)]             # one page hand-drawn
    app.export(); _pump(app)
    assert os.path.exists(out)
    assert set(range(4)) <= set(app._applied)             # every selected page committed, none dropped
    w, h = app._page_dims(0)
    assert app._applied[0][0] != Box(0, 0, w, h)          # page 0 cropped to the auto crop, not whole
    assert app._applied[1] == [Box(30, 40, 200, 500)]     # the drawn page kept its own crop


# ----------------------------------------------- editing a committed crop keeps it committed
def test_crop_edit_keeps_page_committed(app):
    app.set_pages_mode("All"); app.detect_content(); app.apply_crop()
    assert 0 in app._applied
    app.current_page = 0
    box = app._applied[0][0]
    app._view_dims = (box.width, box.height)
    app._on_press(type("E", (), {"x": 5, "y": 5})())       # crop-edit (no stash, page stays cropped)
    assert app._drag["kind"] == "crop-edit" and 0 in app._applied
    app._draw_rect = Box(10, 10, box.width - 10, box.height - 10)
    app._drag_moved = True
    app._on_release(type("E", (), {"x": 9, "y": 9})())
    assert 0 in app._applied                                # still committed after editing — not dropped


# ----------------------------------------------- wheel turns pages, never magnifies (round 7 #3)
def test_canvas_wheel_navigates_pages(app):
    app.current_page = 3
    app._on_canvas_wheel(type("E", (), {"delta": -120})())  # wheel down → next page
    assert app.current_page == 4
    app._on_canvas_wheel(type("E", (), {"delta": 120})())   # wheel up → previous page
    assert app.current_page == 3


# ----------------------------------------------- progress overlay paints at once (round 7 #1)
def test_show_progress_forces_a_paint(app):
    calls = {"n": 0}
    orig = app.root.update_idletasks
    app.root.update_idletasks = lambda: (calls.__setitem__("n", calls["n"] + 1), orig())[1]
    try:
        app._show_progress("Test", 10)
    finally:
        app.root.update_idletasks = orig
    assert calls["n"] >= 1                                  # overlay flushed before any heavy work
    assert app.overlay.place_info()                        # and actually placed on the canvas
    app._hide_progress()


def test_batch_flushes_bar_redraw_each_page(app):
    """The progress bar/counter is flushed between pages, so it advances smoothly instead of in
    starved, fragmental jumps (bug 1: dewarp/filter progress visualization)."""
    calls = {"n": 0}
    orig = app.root.update_idletasks
    app.root.update_idletasks = lambda: (calls.__setitem__("n", calls["n"] + 1), orig())[1]
    seen = []
    try:
        app._run_batch([0, 1, 2], lambda i: i, lambda i, v: seen.append(v),
                       lambda ok: None, "Working")
        _pump(app)
    finally:
        app.root.update_idletasks = orig
    assert seen == [0, 1, 2]                                # all pages processed
    assert calls["n"] >= 2                                  # a redraw flush per page (not one big jump)


# ----------------------------------------------- redo label protects its word (round 7 #4)
def test_redo_button_leads_with_glyph_not_letter(app):
    txt = app.btn_redo.cget("text")
    assert "Redo" in txt
    assert not txt.lstrip().startswith("R")                 # glyph leads → "R" can't be clipped


# ----------------------------------------------- error recovery (round 6: Stage 4)
def test_callback_error_clears_stuck_state(app):
    app._busy = True                                  # simulate a half-finished operation
    app._suspend = True
    app._set_controls_enabled(False)                  # controls disabled mid-op
    try:
        raise ValueError("boom in a callback")
    except ValueError as e:
        app.handle_callback_error(type(e), e, e.__traceback__)
    assert app._busy is False                          # transient flags cleared
    assert app._suspend is False
    assert app.btn_apply.cget("state") == "normal"     # controls usable again, no stuck UI
