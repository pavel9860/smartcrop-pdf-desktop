"""Split → N output pages, apply and navigation through AppModel (spec §7.3, §12.3; inv 11)."""
from __future__ import annotations

import pytest

from core.errors import EmptySelectionError, InvalidSplitError


def _overlay(model, page=0):
    model.current_page = page
    return model.view_snapshot().overlay


def _committed(model, page):
    model.current_page = page
    return model.auto_active and not model.view_snapshot().overlay


@pytest.mark.parametrize("n", [2, 4])
def test_split_creates_n_windows(model, n):
    model.set_split(n)
    assert len(_overlay(model, 0)) == n
    assert all(ob.kind == "split" for ob in _overlay(model, 0))
    assert model.can_apply                       # exactly N rectangles exist


@pytest.mark.parametrize("n", [2, 4])
def test_apply_split_multiplies_output_pages(model, n):
    assert model.view_total == model.page_count()        # uncommitted → one view per page
    model.set_split(n)
    model.apply_crop()
    assert model.view_total == n * model.page_count()    # inv 11: N output pages per source page


def test_split_navigation_walks_boxes_in_order(model):
    model.set_split(2)
    model.apply_crop()
    model.current_page, model.view_box = 0, 0
    seq = []
    for _ in range(5):
        seq.append((model.current_page, model.view_box))
        model.next_page()
    assert seq == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)]
    model.prev_page()
    assert (model.current_page, model.view_box) == (2, 0)


def test_jump_to_output_page_maps_to_source_and_box(model):
    model.set_split(2)
    model.apply_crop()
    model.jump_to_output_page(4)                  # 4th output page = source 1, split 1
    assert (model.current_page, model.view_box) == (1, 1)
    assert model.view_position + 1 == 4


def test_switch_to_split_clears_stale_single_crop(model, run_job):
    run_job(model.detect_content())
    model.apply_crop()
    assert _committed(model, 0)
    model.set_split(2)
    assert not _committed(model, 0)              # stale single-mode crop dropped (§7.3)
    assert model.view_total == model.page_count()


def test_same_size_relayouts_split(model):
    model.set_split(2)
    model.set_same_size(False)
    model.set_same_size(True)                    # re-lays out to the even grid
    boxes = [ob.box for ob in _overlay(model, 0)]
    assert boxes[0].width == pytest.approx(boxes[1].width)


def test_apply_with_wrong_rect_count_raises(model):
    model.set_split(2)
    model.document.crop_rects.pop()              # force a desynced count (defensive guard)
    assert model.can_apply is False
    with pytest.raises(InvalidSplitError):
        model.apply_crop()


def test_apply_empty_selection_raises(model, select):
    select(model, "999")                         # out of range → empty
    with pytest.raises(EmptySelectionError):
        model.apply_crop()
