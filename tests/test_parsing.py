"""Tests for smartcrop.parsing — pure page-selection logic."""
from __future__ import annotations

import pytest

from core.parsing import pages_for_mode, parse_page_expr, parse_selection


class TestPagesForMode:
    def test_all(self):
        assert pages_for_mode("all", 5, 0) == [0, 1, 2, 3, 4]

    def test_odd_pages_are_1indexed(self):           # pages 1,3,5 -> idx 0,2,4
        assert pages_for_mode("odd", 6, 0) == [0, 2, 4]

    def test_even_pages_are_1indexed(self):          # pages 2,4,6 -> idx 1,3,5
        assert pages_for_mode("even", 6, 0) == [1, 3, 5]

    def test_select_expression(self):
        assert pages_for_mode("select", 12, 0, "1,3,5-9,12") == [0, 2, 4, 5, 6, 7, 8, 11]

    def test_empty_document(self):
        assert pages_for_mode("all", 0, 0) == []

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            pages_for_mode("sideways", 5, 0)


class TestParseSelection:
    def test_singletons_and_range(self):
        assert parse_selection("1,3,5-7", 10) == [0, 2, 4, 5, 6]

    def test_out_of_range_ignored(self):
        assert parse_selection("0,3,99", 5) == [2]      # 0 and 99 dropped, 3 -> idx 2

    def test_reversed_range_is_normalised(self):
        assert parse_selection("9-5", 10) == [4, 5, 6, 7, 8]

    def test_duplicates_collapse_and_sort(self):
        assert parse_selection("5,1,1,3", 10) == [0, 2, 4]

    def test_colon_range_inclusive(self):                 # 1:4 == 1-4 == pages 1,2,3,4
        assert parse_selection("1:4", 10) == [0, 1, 2, 3]

    def test_mixed_slices_ranges_and_singles(self):       # #7: '1:4, 10:30, 35, 37'
        got = parse_selection("1:4, 8-9, 12", 40)
        assert got == [0, 1, 2, 3, 7, 8, 11]

    def test_step_slice(self):                            # #4: python-style start:stop:step
        assert parse_selection("1:100:5", 100) == [0, 5, 10, 15, 20, 25, 30, 35, 40,
                                                    45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]

    def test_open_ended_slices(self):
        assert parse_selection("::2", 6) == [0, 2, 4]     # every odd page
        assert parse_selection("10:", 12) == [9, 10, 11]  # page 10 to the end
        assert parse_selection(":3", 10) == [0, 1, 2]     # start to page 3

    def test_negative_step_slice(self):
        assert parse_selection("100:1:-25", 100) == [24, 49, 74, 99]

    def test_too_many_colons_raises(self):
        with pytest.raises(ValueError):
            parse_selection("1:2:3:4", 10)

    def test_zero_step_raises(self):
        with pytest.raises(ValueError):
            parse_selection("1:5:0", 10)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_selection("   ", 10)


class TestParsePageExpr:
    def test_python_slice(self):
        assert parse_page_expr("0:3", 10) == [0, 1, 2]

    def test_negative_index_from_end(self):
        assert parse_page_expr("-1", 10) == [9]

    def test_step_slice(self):
        assert parse_page_expr("::2", 6) == [0, 2, 4]

    def test_zero_step_raises(self):
        with pytest.raises(ValueError):
            parse_page_expr("0:6:0", 10)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_page_expr("", 10)
