"""Undo/redo, rotate and delete through AppModel (spec §13; inv 4, 5)."""
from __future__ import annotations

import pytest

from core.enums import FilterMode
from core.errors import DeleteAllPagesError, EmptySelectionError, NoDocumentError


def _committed(model, page):
    model.current_page = page
    return model.auto_active and not model.view_snapshot().overlay


# ── undo reverts crop / draw / rotate / filter (inv 4) ──────────────────────────
def test_undo_reverts_apply(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    assert _committed(model, 0)
    model.undo()
    assert not _committed(model, 0)              # back to the uncommitted live crop
    assert model.can_redo
    model.redo()
    assert _committed(model, 0)


def test_undo_reverts_draw(model):
    model.begin_drag(40, 40, tol=3.0)
    model.update_drag(240, 540)
    model.end_drag()
    cropped = model.view_snapshot().page_w
    model.undo()
    assert model.view_snapshot().page_w != cropped


def test_undo_reverts_filter(scanned, run_job):
    m = scanned(1)
    m.current_page = 0
    plain = m.view_snapshot().image.tobytes()
    run_job(m.set_filter_mode(FilterMode.BW))
    assert m.view_snapshot().image.tobytes() != plain
    m.undo()
    assert m.view_snapshot().image.tobytes() == plain      # filter reverted


# ── rotate preserves the committed crop; undo restores (inv 5) ──────────────────
def test_rotate_preserves_committed_crop_and_is_undoable(model, run_job, select):
    select(model, "1")
    run_job(model.detect_content())
    model.apply_crop()
    assert _committed(model, 0)
    model.current_page = 0
    w0, h0 = model.view_snapshot().page_w, model.view_snapshot().page_h
    model.rotate_pages()
    assert _committed(model, 0)                  # crop carried through the turn (not dropped)
    model.undo()
    assert _committed(model, 0)
    assert (model.view_snapshot().page_w, model.view_snapshot().page_h) == (w0, h0)


# ── delete reindexes, preserving kept-page adjustments (inv 5) ───────────────────
def test_delete_preserves_kept_page_crops(loaded, run_job, select):
    m = loaded(5)
    run_job(m.detect_content())
    select(m, "1")
    m.apply_crop()                               # commit page 0
    select(m, "4")
    m.apply_crop()                               # commit page 3
    assert _committed(m, 0) and _committed(m, 3)
    select(m, "2")
    m.delete_pages()                             # remove page 2 (idx 1)
    assert m.page_count() == 4
    assert _committed(m, 0)                      # page 0 unchanged
    assert _committed(m, 2)                      # old page 4 shifted down to idx 2, still committed


def test_delete_all_pages_refused(loaded, select):
    m = loaded(3)
    select(m, "1-3")
    with pytest.raises(DeleteAllPagesError):
        m.delete_pages()
    assert m.page_count() == 3


def test_delete_empty_selection_raises(loaded, select):
    m = loaded(4)
    select(m, "99")
    with pytest.raises(EmptySelectionError):
        m.delete_pages()


def test_delete_on_synthetic_refused(model, select):
    select(model, "1")
    with pytest.raises(NoDocumentError):         # the demo doc can't be edited
        model.delete_pages()


# ── undo depth bound (spec §13, default 4) ──────────────────────────────────────
def test_undo_depth_bounds_history(model):
    model.set_undo_depth(2)
    for _ in range(3):                           # three undoable rotates (one snapshot each)
        model.rotate_pages()
    model.undo()
    model.undo()
    assert model.can_undo is False               # only 2 snapshots retained, both consumed
