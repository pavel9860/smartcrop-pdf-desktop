"""Auto-detect, anchors, offsets, keep-ratio via AppModel (§8, §9; inv 1, 2, 7, 16, 19)."""
from __future__ import annotations

import pytest


def _box(model, page=None):
    """The current (or given) page's live auto-crop box from the paint snapshot, or None."""
    if page is not None:
        model.current_page = page
    ov = model.view_snapshot().overlay
    return ov[0].box if ov else None


def _committed(model, page):
    model.current_page = page
    return model.auto_active and not model.view_snapshot().overlay


def test_detect_activates_auto(model, run_job):
    run_job(model.detect_content())
    assert model.auto_active
    assert _box(model, 0) is not None


def test_constant_union_size_across_pages(model, run_job):
    run_job(model.detect_content())          # inv 1: one constant W×H across the selection
    widths = {round(_box(model, p).width, 3) for p in range(6)}
    heights = {round(_box(model, p).height, 3) for p in range(6)}
    assert len(widths) == 1 and len(heights) == 1


def test_every_crop_inside_the_page(model, run_job):
    run_job(model.detect_content())          # inv 7: never extends outside the page
    for p in range(6):
        snap = model.view_snapshot()
        b = snap.overlay[0].box
        assert 0 <= b.x0 <= b.x1 <= snap.page_w + 1e-6
        assert 0 <= b.y0 <= b.y1 <= snap.page_h + 1e-6


def test_left_offset_moves_only_left_edge(model, run_job):
    run_job(model.detect_content())
    base = _box(model, 0)
    model.set_offset("L", 6.0)
    moved = _box(model, 0)
    assert moved.x0 < base.x0                 # +L pushes the left edge outward
    assert moved.x1 == pytest.approx(base.x1)        # right unchanged (§9.2)
    assert moved.y0 == pytest.approx(base.y0)
    assert moved.y1 == pytest.approx(base.y1)


def test_drag_handle_keeps_other_edges_stable(model, run_job):
    run_job(model.detect_content())
    b = _box(model, 0)
    my = (b.y0 + b.y1) / 2
    model.begin_drag(b.x1, my, tol=3.0)       # grab the E (right-edge) handle
    model.update_drag(b.x1 + 20, my)
    model.end_drag()
    nb = _box(model, 0)
    assert nb.x1 > b.x1                        # dragged edge moved
    assert nb.x0 == pytest.approx(b.x0)        # inv 2: non-dragged edges pixel-stable
    assert nb.y0 == pytest.approx(b.y0)
    assert nb.y1 == pytest.approx(b.y1)


def test_keep_ratio_locks_height(model, run_job):
    run_job(model.detect_content())
    model.set_keep_ratio(True, 1.5)
    b = _box(model, 0)
    assert b.width / b.height == pytest.approx(1.5, abs=0.02)   # inv 19, live auto crop


def test_offsets_snap_into_range_on_commit(model, run_job):
    run_job(model.detect_content())
    model.set_offset("R", 100000.0)
    model.set_offset("L", -100000.0)
    model.commit_offsets()
    o = model.offsets
    assert all(-100.0 <= v <= 100.0 for v in (o.left, o.right, o.bottom))
    b = _box(model, 0)
    snap = model.view_snapshot()
    assert 0 <= b.x0 and b.x1 <= snap.page_w + 0.01


def test_commit_offsets_without_detection_bounds_to_hundred(model):
    model.set_offset("R", 5000.0)
    model.commit_offsets()
    assert model.offsets.right == 100.0


def test_anchors_off_disable_detect(model):
    model.set_anchor(left=False, top=False)
    assert model.can_detect is False
    model.set_anchor(left=True)
    assert model.can_detect is True


def test_redetect_refreshes_committed_crop_keeps_it(model, run_job, select):
    select(model, "1")
    run_job(model.detect_content())
    model.apply_crop()
    assert _committed(model, 0)
    before = model.view_snapshot().page_w     # committed → page_w is the crop width
    model.current_page = 0
    model.set_offset("R", 12.0)
    run_job(model.detect_content())           # re-detect the same page
    assert _committed(model, 0)               # inv 16: kept committed, not dropped
    assert model.view_snapshot().page_w != before     # and refreshed to the new crop


def test_redetect_keeps_crops_outside_selection(model, run_job, select):
    select(model, "1-2")
    run_job(model.detect_content())
    model.apply_crop()
    assert _committed(model, 0) and _committed(model, 1)
    select(model, "4-5")
    run_job(model.detect_content())           # detecting 4-5 must not wipe 1-2's crops
    assert _committed(model, 0) and _committed(model, 1)
    assert not _committed(model, 3)           # page 4 stayed uncommitted
