"""Pure output-page navigation math (no Tk).

A committed split page expands into one output page per committed box; an uncommitted page
is a single view. These helpers turn the per-page `applied` map into the flat sequence the
viewer pages through, so the preview count matches the exported file (see [[render]]).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

# Covariant view: any per-page map of box-sequences (e.g. dict[int, list[Box]]) is accepted.
Applied = Mapping[int, Sequence[Any]]


def page_box_count(applied: Applied, i: int) -> int:
    """Number of output pages source page `i` yields (N for a committed split, else 1)."""
    boxes = applied.get(i)
    return len(boxes) if boxes else 1


def view_total(applied: Applied, n_pages: int) -> int:
    """Total output pages across the document."""
    return sum(page_box_count(applied, i) for i in range(n_pages))


def view_position(applied: Applied, current_page: int, view_box: int) -> int:
    """0-based flat output index of (current_page, view_box)."""
    before = sum(page_box_count(applied, j) for j in range(current_page))
    return before + min(view_box, max(0, page_box_count(applied, current_page) - 1))


def flat_to_page_box(applied: Applied, n_pages: int, flat: int) -> Tuple[int, int]:
    """Map a 0-based flat output index to (source_page, box_index)."""
    rem = flat
    for i in range(n_pages):
        c = page_box_count(applied, i)
        if rem < c:
            return i, rem
        rem -= c
    last = max(0, n_pages - 1)
    return last, max(0, page_box_count(applied, last) - 1)
