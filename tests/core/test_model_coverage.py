"""Remaining behaviour paths: split-window dragging, keep-ratio across every gesture, scan/export
error paths, navigation bounds and status (spec §9.6, §9.7, §11, §12, §20)."""
from __future__ import annotations

import fitz
import pytest

from core.batch import Cancelled
from core.enums import FilterMode
from core.errors import EmptySelectionError
from core.model import AppModel


def _overlay(model, page=0):
    model.current_page = page
    return [ob.box for ob in model.view_snapshot().overlay]


# ── split-window gestures (§9.6) ────────────────────────────────────────────────
def test_split_window_moves(model):
    model.set_split(2)
    b0 = _overlay(model)[0]
    model.begin_drag((b0.x0 + b0.x1) / 2, (b0.y0 + b0.y1) / 2, tol=3.0)
    model.update_drag((b0.x0 + b0.x1) / 2 + 15, (b0.y0 + b0.y1) / 2 + 15)
    model.end_drag()
    assert _overlay(model)[0] != b0


def test_split_window_resizes_by_handle(model):
    model.set_split(2)
    model.set_same_size(False)
    b0 = _overlay(model)[0]
    model.begin_drag(b0.x1, b0.y1, tol=3.0)          # SE corner
    model.update_drag(b0.x1 - 40, b0.y1 - 30)
    model.end_drag()
    assert _overlay(model)[0].width < b0.width


def test_split_same_size_propagates_on_release(model):
    model.set_split(4)                               # same_size defaults on
    b0 = _overlay(model)[0]
    model.begin_drag(b0.x1, b0.y1, tol=3.0)
    model.update_drag(b0.x1 - 30, b0.y1 - 20)
    model.end_drag()
    boxes = _overlay(model)
    assert all(b.width == pytest.approx(boxes[0].width) for b in boxes)
    assert all(b.height == pytest.approx(boxes[0].height) for b in boxes)


def test_split_keep_ratio_snaps_on_release(model):
    model.set_split(2)
    model.set_same_size(False)
    model.set_keep_ratio(True, 2.0)
    b0 = _overlay(model)[0]
    model.begin_drag((b0.x0 + b0.x1) / 2, (b0.y0 + b0.y1) / 2, tol=3.0)
    model.update_drag((b0.x0 + b0.x1) / 2 + 5, (b0.y0 + b0.y1) / 2 + 5)
    model.end_drag()
    nb = _overlay(model)[0]
    assert nb.width / nb.height == pytest.approx(2.0, abs=0.05)


# ── keep-ratio across the other crop sources (§9.7, inv 19) ─────────────────────
def test_keep_ratio_snaps_hand_drawn(model):
    model.set_keep_ratio(True, 2.0)
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    snap = model.view_snapshot()
    assert snap.page_w / snap.page_h == pytest.approx(2.0, abs=0.05)


def test_keep_ratio_snaps_crop_edit(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    model.current_page = 0
    model.set_keep_ratio(True, 1.5)
    snap = model.view_snapshot()
    model.begin_drag(2, 2, tol=3.0)
    model.update_drag(snap.page_w * 0.6, snap.page_h * 0.6)
    model.end_drag()
    out = model.view_snapshot()
    assert out.page_w / out.page_h == pytest.approx(1.5, abs=0.05)


def test_keep_ratio_defaults_to_detected_ratio(model, run_job):
    run_job(model.detect_content())
    model.set_keep_ratio(True)                       # no explicit ratio → use the detected W/H
    assert model.ratio is not None and model.ratio > 0


def test_commit_offsets_with_keep_ratio_runs(model, run_job):
    run_job(model.detect_content())
    model.set_keep_ratio(True, 1.5)
    model.set_offset("B", 20.0)
    model.commit_offsets()                           # bottom is derived/inert under the lock
    o = model.offsets
    assert all(-100.0 <= v <= 100.0 for v in (o.left, o.top, o.right, o.bottom))


# ── scan error / record paths (§20) ─────────────────────────────────────────────
def test_dewarp_empty_selection_raises(scanned, select):
    m = scanned(1)
    select(m, "99")
    with pytest.raises(EmptySelectionError):
        m.run_dewarp()


def test_filter_empty_selection_raises(scanned, select):
    m = scanned(1)
    select(m, "99")
    with pytest.raises(EmptySelectionError):
        m.set_filter_mode(FilterMode.BW)


def test_set_filter_strength_records_when_no_filter(scanned, run_job):
    m = scanned(1)
    run_job(m.set_filter_strength(3))                # filter NONE → the remember path
    assert m.filter_strength == 3


# ── export error / cancel paths (§12, §20) ──────────────────────────────────────
def test_export_empty_selection_raises(loaded, select, tmp_path):
    m = loaded(1)
    select(m, "99")
    with pytest.raises(EmptySelectionError):
        m.export(tmp_path / "x.pdf")


def test_export_pdf_cancel_writes_no_file(loaded, tmp_path):
    m = loaded(3)
    out = tmp_path / "c.pdf"
    job = m.export(out)
    job.cancel()                                     # cancel before any page is written
    assert isinstance(job.result(), Cancelled)
    assert not out.exists()


def test_export_images_cancel_deletes_partial(loaded, tmp_path):
    m = loaded(3)
    m.set_export_format("PNG")
    job = m.export(tmp_path / "p.png")
    job.step()                                       # write page 0 → p_001.png
    job.cancel()                                     # discard → delete what was written (FIX 13)
    assert not (tmp_path / "p_001.png").exists()


def test_suggested_name_on_synthetic_is_output(model):
    name, _folder = model.suggested_export_name()
    assert name.startswith("output")


# ── navigation bounds + status (§5, §12.3) ──────────────────────────────────────
def test_navigation_stops_at_both_ends(model):
    model.current_page, model.view_box = 0, 0
    model.prev_page()
    assert model.current_page == 0
    model.current_page = model.page_count() - 1
    model.next_page()
    assert model.current_page == model.page_count() - 1


def test_jump_out_of_range_is_noop(model):
    model.current_page = 5
    model.jump_to_output_page(99999)
    assert model.current_page == 5


def test_status_text_shows_split_index(model):
    model.set_split(2)
    model.apply_crop()
    model.current_page, model.view_box = 1, 1
    assert "split 2/2" in model.view_snapshot().status


# ── detection fallback on a vector page with no text (§8) ────────────────────────
def test_vector_only_page_detects_full_page(tmp_path, run_job):
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.draw_line((20, 20), (280, 380))             # vector drawing, no text → Normal
    path = tmp_path / "vec.pdf"
    doc.save(str(path))
    doc.close()
    m = AppModel()
    m.load_files([str(path)])
    run_job(m.detect_content())
    assert m.auto_active                             # detection ran; no-text page → full-page box
