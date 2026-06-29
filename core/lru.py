"""A tiny page-keyed LRU cache for the raster caches (source/work images).

Bounding these caches to a small window around the current page keeps resident memory flat no
matter how large the document is — opening or scrolling a 300-page PDF can't grow RAM without
limit, and the garbage collector reclaims the evicted images. Plain `dict` semantics otherwise,
so the rest of the code (`get`/`[]=`/`in`/`pop`/`clear`/`items`/`values`) is unchanged.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any


class LRUCache(OrderedDict[Any, Any]):
    """An OrderedDict capped at `maxsize` entries; least-recently-used is evicted on insert.
    Reads (`[]`/`get`) and writes refresh recency. `maxsize <= 0` means unbounded."""

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self.maxsize = maxsize

    def __getitem__(self, key: Any) -> Any:
        self.move_to_end(key)
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            self.move_to_end(key)
            return super().__getitem__(key)
        return default

    def __setitem__(self, key: Any, value: Any) -> None:
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if self.maxsize and len(self) > self.maxsize:
            self.popitem(last=False)          # drop the least-recently-used entry
