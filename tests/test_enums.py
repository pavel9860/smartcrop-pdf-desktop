"""Tests for core.enums — formalised states that still compare like their old strings."""
from __future__ import annotations

from core.enums import Mode, FilterMode, PagesMode
from core.parsing import pages_for_mode


def test_str_backed_values():
    assert Mode.SCANNED == "scanned" and Mode.NORMAL == "normal"
    assert FilterMode.BW == "bw" and FilterMode.SHARPEN == "sharpen" and FilterMode.NONE == "none"
    assert [m.value for m in PagesMode] == ["all", "odd", "even", "select"]


def test_members_are_singletons():
    assert Mode("scanned") is Mode.SCANNED
    assert FilterMode("bw") is FilterMode.BW


def test_parsing_accepts_pagesmode_directly():
    # str-backed enum means the pure parser keeps working without conversion at the boundary.
    assert pages_for_mode(PagesMode.ODD, 6, 0) == [0, 2, 4]
    assert pages_for_mode(PagesMode.ALL, 3, 0) == [0, 1, 2]
