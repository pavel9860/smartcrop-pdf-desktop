"""Tests for core.lru.LRUCache — the page-keyed bound that keeps raster RAM flat."""
from __future__ import annotations

from core.lru import LRUCache


def test_evicts_least_recently_used_on_insert():
    c = LRUCache(3)
    for k in (0, 1, 2, 3):          # inserting a 4th drops the oldest (0)
        c[k] = k
    assert set(c) == {1, 2, 3}
    assert len(c) == 3


def test_get_refreshes_recency():
    c = LRUCache(3)
    for k in (0, 1, 2):
        c[k] = k
    assert c.get(0) == 0            # touch 0 → now 1 is the LRU
    c[3] = 3                        # inserting 3 evicts 1, not 0
    assert set(c) == {0, 2, 3}


def test_setitem_existing_refreshes_recency():
    c = LRUCache(3)
    for k in (0, 1, 2):
        c[k] = k
    c[0] = 99                       # re-writing 0 makes it most-recent
    c[3] = 3                        # evicts 1
    assert set(c) == {0, 2, 3}
    assert c[0] == 99


def test_dict_api_still_works():
    c = LRUCache(4)
    c[5] = "a"
    assert 5 in c and c.get(9) is None
    assert c.pop(5) == "a" and 5 not in c
    c[1] = "x"; c.clear()
    assert len(c) == 0


def test_zero_or_negative_maxsize_is_unbounded():
    c = LRUCache(0)
    for k in range(100):
        c[k] = k
    assert len(c) == 100
