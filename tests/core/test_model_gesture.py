"""Mouse gestures: draw, crop-edit, split drag and cancel (spec §9; inv 13, 15, 24)."""
from __future__ import annotations

import pytest


def _box(model, page=None):
    if page is not None:
        model.current_page = page
    ov = model.view_snapshot().overlay
    return ov[0].box if ov else None


def _committed(model, page):
    model.current_page = page
    return model.auto_active and not model.view_snapshot().overlay


# ── drawing a crop is per-page and local (inv 13) ───────────────────────────────
def test_draw_commits_only_this_page(model, run_job):
    run_job(model.detect_content())
    before_other = _box(model, 1)
    model.current_page = 0
    model.begin_drag(5, 5, tol=3.0)              # empty corner → rubber-band a new crop
    model.update_drag(300, 500)
    model.end_drag()
    assert _committed(model, 0)                  # this page committed to the drawn rect
    assert _box(model, 1) == before_other        # other pages' live crop unchanged (§9.4)


def test_draw_on_uncommitted_page_commits(model):
    full_w = model.view_snapshot().page_w        # uncommitted → full page width
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    snap = model.view_snapshot()
    assert snap.page_w == pytest.approx(200)     # shown cropped to the drawn box
    assert snap.page_w < full_w


def test_draw_is_undoable(model):
    model.begin_drag(40, 40, tol=3.0)
    model.update_drag(240, 540)
    model.end_drag()
    assert model.can_undo
    cropped_w = model.view_snapshot().page_w
    model.undo()
    assert model.view_snapshot().page_w != cropped_w   # back to the full page


# ── a crop is never dropped except by undo / valid replace (inv 15) ─────────────
def test_stray_click_keeps_committed_crop(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    model.current_page = 0
    page_w = model.view_snapshot().page_w
    model.begin_drag(3, 3, tol=3.0)              # press on the committed view
    model.end_drag()                             # released without dragging
    assert _committed(model, 0)                  # still committed
    assert model.view_snapshot().page_w == pytest.approx(page_w)


def test_tiny_crop_edit_keeps_committed_crop(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    model.current_page = 0
    page_w = model.view_snapshot().page_w
    model.begin_drag(3, 3, tol=3.0)
    model.update_drag(5, 5)                      # degenerate band (< 2·MIN_RECT)
    model.end_drag()
    assert _committed(model, 0)
    assert model.view_snapshot().page_w == pytest.approx(page_w)


def test_crop_edit_tightens_and_is_undoable(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    model.current_page = 0
    snap = model.view_snapshot()
    w, h = snap.page_w, snap.page_h
    undo_before = model.can_undo
    model.begin_drag(2, 2, tol=3.0)              # rubber-band inside the committed view
    model.update_drag(w * 0.5, h * 0.5)
    model.end_drag()
    assert _committed(model, 0)                  # stays committed (§9.3 option a)
    assert model.view_snapshot().page_w < w      # tightened
    assert model.can_undo and (undo_before or True)


# ── cancel a drag (inv 24) ──────────────────────────────────────────────────────
def test_cancel_split_drag_restores_window(model):
    model.set_split(2)
    box0 = _box(model, 0)
    undo_before = model.can_undo
    model.begin_drag((box0.x0 + box0.x1) / 2, (box0.y0 + box0.y1) / 2, tol=3.0)   # move window 0
    model.update_drag(box0.x0 + 30, box0.y0 + 30)
    model.cancel_drag()
    assert _box(model, 0) == box0                # rolled back
    assert model.can_undo == undo_before         # no snapshot taken


def test_cancel_auto_drag_restores_offsets(model, run_job):
    run_job(model.detect_content())
    b = _box(model, 0)
    o0 = model.offsets
    model.begin_drag(b.x1, (b.y0 + b.y1) / 2, tol=3.0)
    model.update_drag(b.x1 + 25, (b.y0 + b.y1) / 2)
    assert model.offsets != o0                   # live edit changed offsets
    model.cancel_drag()
    assert model.offsets == o0                   # restored exactly (inv 24)


def test_cancel_with_nothing_in_progress_is_noop(model):
    model.cancel_drag()                          # must not raise
    assert model.drag is None
