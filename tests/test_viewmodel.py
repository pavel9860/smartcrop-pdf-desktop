"""Tests for core.viewmodel — output-page navigation math (committed splits expand to N)."""
from __future__ import annotations

from core.geometry import Box
from core.viewmodel import flat_to_page_box, page_box_count, view_position, view_total


def _b():
    return Box(0, 0, 1, 1)


def test_uncommitted_page_is_one_view():
    assert page_box_count({}, 0) == 1


def test_committed_split_counts_its_boxes():
    applied = {0: [_b(), _b()]}                      # a 2-split committed page
    assert page_box_count(applied, 0) == 2


def test_view_total_mixes_committed_and_uncommitted():
    applied = {0: [_b(), _b()], 2: [_b(), _b(), _b(), _b()]}   # pages 1 & 3 split, page 2 plain
    assert view_total(applied, 4) == 2 + 1 + 4 + 1             # = 8


def test_view_position_is_flat_index():
    applied = {0: [_b(), _b()], 1: [_b(), _b()]}
    assert view_position(applied, 0, 0) == 0
    assert view_position(applied, 0, 1) == 1
    assert view_position(applied, 1, 0) == 2
    assert view_position(applied, 1, 1) == 3


def test_view_position_clamps_view_box():
    applied = {0: [_b()]}                            # only one box but view_box stale at 3
    assert view_position(applied, 0, 3) == 0


def test_flat_to_page_box_roundtrips():
    applied = {0: [_b(), _b()], 1: [_b(), _b()], 2: [_b(), _b()]}
    seq = [flat_to_page_box(applied, 3, k) for k in range(view_total(applied, 3))]
    assert seq == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]


def test_flat_to_page_box_out_of_range_clamps_to_last():
    applied = {0: [_b(), _b()]}
    assert flat_to_page_box(applied, 1, 99) == (0, 1)
