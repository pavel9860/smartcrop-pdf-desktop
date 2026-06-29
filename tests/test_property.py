"""Property-based tests (hypothesis) for the pure geometry and parsing modules."""
from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from core.geometry import (
    MIN_RECT,
    Box,
    clamp_box,
    move_box,
    resize_by_handle,
    rotate_box_cw,
    union_box,
)
from core.parsing import parse_selection

W, H = 595.0, 842.0
ints = st.integers(min_value=-2000, max_value=2000)
dims = st.integers(min_value=1, max_value=3000)


def _box(x0, y0, x1, y1):
    return Box(min(x0, x1), min(y0, y1), max(x0, x1) + 1, max(y0, y1) + 1)


@given(x0=ints, y0=ints, x1=ints, y1=ints, w=dims, h=dims)
def test_rotate_four_times_is_identity(x0, y0, x1, y1, w, h):
    b0 = _box(x0, y0, x1, y1)
    b, ww, hh = b0, float(w), float(h)
    for _ in range(4):
        b = rotate_box_cw(b, ww, hh)
        ww, hh = hh, ww                  # the page dims swap each quarter turn
    assert b == b0                       # integer coords → exact 4-cycle


@given(x0=ints, y0=ints, x1=ints, y1=ints)
def test_clamp_box_lands_on_page(x0, y0, x1, y1):
    b = clamp_box(_box(x0, y0, x1, y1), W, H)
    assert 0 <= b.x0 <= b.x1 <= W + 1e-9
    assert 0 <= b.y0 <= b.y1 <= H + 1e-9
    assert b.width >= MIN_RECT - 1e-9 and b.height >= MIN_RECT - 1e-9


@given(x0=st.integers(0, 500), y0=st.integers(0, 700), dx=ints, dy=ints)
def test_move_box_preserves_size_and_stays_on_page(x0, y0, dx, dy):
    b = Box(x0, y0, x0 + 80, y0 + 90)
    m = move_box(b, dx, dy, W, H)
    assert m.width == b.width and m.height == b.height
    assert 0 <= m.x0 and m.x1 <= W + 1e-9 and 0 <= m.y0 and m.y1 <= H + 1e-9


@given(handle=st.sampled_from(["NW", "N", "NE", "E", "SE", "S", "SW", "W"]), dx=ints, dy=ints)
def test_resize_by_handle_always_valid(handle, dx, dy):
    out = resize_by_handle(Box(100, 100, 300, 300), handle, dx, dy, W, H)
    assert 0 <= out.x0 < out.x1 <= W + 1e-9
    assert 0 <= out.y0 < out.y1 <= H + 1e-9
    assert out.width >= MIN_RECT - 1e-9 and out.height >= MIN_RECT - 1e-9


@given(boxes=st.lists(st.tuples(st.integers(0, 400), st.integers(0, 400),
                                st.integers(1, 200), st.integers(1, 200)), min_size=1, max_size=8))
def test_union_box_size_is_max_dims(boxes):
    bs = [Box(x, y, x + w, y + h) for x, y, w, h in boxes]
    u = union_box(bs)
    assert u.width == max(b.width for b in bs)
    assert u.height == max(b.height for b in bs)
    assert u.x0 == min(b.x0 for b in bs) and u.y0 == min(b.y0 for b in bs)


@given(nums=st.lists(st.integers(-20, 80), min_size=1, max_size=20), total=st.integers(1, 60))
def test_parse_selection_in_range_sorted_unique(nums, total):
    out = parse_selection(",".join(str(n) for n in nums), total)
    assert out == sorted(set(out))
    assert all(0 <= i < total for i in out)
