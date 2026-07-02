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


# ── drawing creates a live per-page window — never a commit, never a zoom (§9.4, inv 13/28) ──
def test_draw_creates_window_without_commit_or_zoom(model):
    full_w = model.view_snapshot().page_w        # uncommitted → full page width
    total = model.view_total
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    snap = model.view_snapshot()
    assert snap.page_w == pytest.approx(full_w)  # inv 28: the page is NOT magnified
    assert model.view_total == total             # nothing committed
    assert model.can_undo is False               # a live window is setup, not history
    win = snap.overlay[0].box                    # shown as an adjustable window
    assert (win.x0, win.y0, win.x1, win.y1) == pytest.approx((50, 50, 250, 550))


def test_drawn_window_is_local_to_its_page(model, run_job):
    run_job(model.detect_content())
    before_other = _box(model, 1)
    model.current_page = 0
    model.begin_drag(5, 5, tol=3.0)              # outside the auto frame → draw a window
    model.update_drag(300, 500)
    model.end_drag()
    assert _box(model, 1) == before_other        # other pages' live crop unchanged (inv 13)
    assert not _committed(model, 0)              # still uncommitted


def test_crop_commits_the_drawn_window(model):
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    assert model.can_apply                       # the window is a crop source (§7.7)
    model.apply_crop()
    snap = model.view_snapshot()
    assert snap.overlay == ()                    # committed: shown as saved, no handles (§12.1)
    assert snap.page_w == pytest.approx(200)
    assert model.can_undo                        # the commit is one undoable step
    model.current_page = 1                       # sourceless page: skipped, still full (inv 25)
    other = model.view_snapshot()
    assert other.page_w > 500 and other.overlay == ()


def test_escape_drops_the_drawn_window(model):
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    assert model.view_snapshot().overlay         # window on screen
    model.cancel_drag()                          # Esc / right-click, no drag → drop (§9.4)
    assert model.view_snapshot().overlay == ()
    assert model.can_apply is False


def test_drawn_window_moves_and_resizes(model):
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    model.begin_drag(150, 300, tol=3.0)          # interior → move the window
    model.update_drag(170, 320)
    model.end_drag()
    win = model.view_snapshot().overlay[0].box
    assert (win.x0, win.y0) == pytest.approx((70, 70))
    model.begin_drag(win.x1, win.y1, tol=3.0)    # SE corner → resize
    model.update_drag(win.x1 - 30, win.y1 - 40)
    model.end_drag()
    win2 = model.view_snapshot().overlay[0].box
    assert win2.width == pytest.approx(win.width - 30)
    assert win2.height == pytest.approx(win.height - 40)


def test_cancel_window_drag_restores_it(model):
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    win = model.view_snapshot().overlay[0].box
    model.begin_drag(150, 300, tol=3.0)
    model.update_drag(400, 400)
    model.cancel_drag()                          # mid-drag cancel → window unchanged (inv 24)
    assert model.view_snapshot().overlay[0].box == win


def test_new_draw_replaces_the_window(model):
    model.begin_drag(50, 50, tol=3.0)
    model.update_drag(250, 550)
    model.end_drag()
    model.begin_drag(300, 600, tol=3.0)          # outside the window → new rubber-band
    model.update_drag(420, 700)
    model.end_drag()
    boxes = model.view_snapshot().overlay
    assert len(boxes) == 1
    assert boxes[0].box.x0 == pytest.approx(300)


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
    before = model.view_snapshot()
    model.cancel_drag()                          # right-click with no drag (inv 24) — no raise
    after = model.view_snapshot()
    assert (after.page_w, after.page_h, after.overlay) == (
        before.page_w, before.page_h, before.overlay)
    assert model.can_undo is False


# ── a committed split page ignores window gestures (inv 26) ─────────────────────
def _split_committed(model, n=2):
    model.set_split(n)
    layout = [ob.box for ob in model.view_snapshot().overlay]
    model.apply_crop()
    model.current_page, model.view_box = 0, 0
    return layout


def test_committed_split_degenerate_drag_changes_nothing(model):
    layout = _split_committed(model)
    total = model.view_total
    w = model.view_snapshot().page_w             # box units of output page 1
    model.begin_drag(10.0, 10.0, tol=12.0)       # would grab window 1 under the old coord bug
    model.update_drag(12.0, 12.0)                # degenerate band (< 2·MIN_RECT) → invalid draw
    model.end_drag()
    assert model.view_total == total             # still committed, still N views per page
    assert model.view_snapshot().page_w == pytest.approx(w)
    model.undo()                                 # undo the Apply → back to the window layout
    boxes = [ob.box for ob in model.view_snapshot().overlay]
    assert boxes == layout                       # split windows never crept (inv 26)


def test_committed_split_press_never_flips_to_full_page(model):
    _split_committed(model)
    box_w = model.view_snapshot().page_w         # committed output-page width (box units)
    model.begin_drag(10.0, 10.0, tol=12.0)       # press alone must not pop the committed view
    mid = model.view_snapshot()
    assert mid.page_w == pytest.approx(box_w)    # still the cropped output page, not the full page
    assert mid.overlay == ()                     # no split windows re-shown
    model.end_drag()                             # stray click: nothing committed, nothing dropped
    assert model.view_snapshot().page_w == pytest.approx(box_w)


def test_committed_split_draw_tightens_only_current_window(model):
    _split_committed(model)
    w0 = model.view_snapshot().page_w
    model.current_page, model.view_box = 0, 1    # look at output window 2
    w_other = model.view_snapshot().page_w
    model.current_page, model.view_box = 0, 0
    model.begin_drag(4.0, 4.0, tol=3.0)          # draw a new rectangle inside output page 1
    model.update_drag(w0 * 0.6, model.view_snapshot().page_h * 0.6)
    model.end_drag()
    assert model.view_snapshot().page_w < w0     # this window re-committed tightened
    assert model.view_total == 2 * model.page_count()   # still N output pages per source
    model.current_page, model.view_box = 0, 1
    assert model.view_snapshot().page_w == pytest.approx(w_other)  # other window untouched
    model.undo()
    model.current_page, model.view_box = 0, 0
    assert model.view_snapshot().page_w == pytest.approx(w0)       # undoable
