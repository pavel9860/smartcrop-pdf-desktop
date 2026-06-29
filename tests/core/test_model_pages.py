"""Pages selection and the Current follow-toggle through AppModel (spec §11)."""
from __future__ import annotations

from core.enums import PagesMode


def test_selected_pattern_resolves(model, select):
    select(model, "1:3, 5")
    assert model.resolve_pages() == [0, 1, 2, 4]


def test_odd_even_all(model):
    model.set_pages_mode(PagesMode.ODD)
    assert model.resolve_pages() == list(range(0, 24, 2))
    model.set_pages_mode(PagesMode.EVEN)
    assert model.resolve_pages() == list(range(1, 24, 2))
    model.set_pages_mode(PagesMode.ALL)
    assert model.resolve_pages() == list(range(24))


def test_current_follow_selects_current_page(model):
    model.current_page = 6
    model.set_current_follow(True)
    assert model.pages_mode == PagesMode.SELECT
    assert model.select_pattern == "7"
    assert model.current_follow is True
    assert model.resolve_pages() == [6]


def test_current_follow_tracks_navigation(model):
    model.current_page = 4
    model.set_current_follow(True)
    model.next_page()
    assert model.select_pattern == "6"
    assert model.resolve_pages() == [5]
    model.prev_page()
    assert model.select_pattern == "5"


def test_follow_ends_on_mode_change(model):
    model.current_page = 2
    model.set_current_follow(True)
    model.set_pages_mode(PagesMode.ALL)
    assert model.current_follow is False


def test_follow_ends_on_manual_pattern_edit(model):
    model.current_page = 2
    model.set_current_follow(True)
    model.set_select_pattern("3")
    assert model.current_follow is False
    assert model.select_pattern == "3"           # the typed pattern is kept


def test_out_of_range_pattern_is_empty(model, select):
    select(model, "999")
    assert model.resolve_pages() == []
