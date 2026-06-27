"""Tests for smartcrop.geometry — the crop-rectangle / mouse-drag adjustment math
that the UI uses for handle-resize, whole-box move, clamping and hit-testing."""
from __future__ import annotations

import pytest

from core.geometry import (MIN_RECT, Box, auto_crop_rect, clamp_box, fit_box_keep_size,
                                handle_positions, hit_handle, move_box, point_in_box,
                                resize_by_handle, rotate_box_cw, union_box)

W, H = 595.0, 842.0                                   # an A4-ish page


class TestBox:
    def test_width_height(self):
        b = Box(10, 20, 110, 220)
        assert b.width == 100 and b.height == 200

    def test_equality_and_tuple(self):
        assert Box(1, 2, 3, 4) == Box(1, 2, 3, 4)
        assert Box(1, 2, 3, 4).as_tuple() == (1.0, 2.0, 3.0, 4.0)


class TestClamp:
    def test_inside_unchanged(self):
        assert clamp_box(Box(50, 60, 200, 300), W, H) == Box(50, 60, 200, 300)

    def test_negative_origin_pulled_in(self):
        b = clamp_box(Box(-30, -40, 100, 100), W, H)
        assert b.x0 == 0 and b.y0 == 0

    def test_overflow_clamped_to_page(self):
        b = clamp_box(Box(100, 100, 9999, 9999), W, H)
        assert b.x1 == W and b.y1 == H

    def test_fit_keep_size_shifts_not_shrinks(self):
        # overhang right+bottom → shift inward, size preserved
        b = fit_box_keep_size(Box(W - 50, H - 50, W + 150, H + 250), W, H)
        assert (round(b.width), round(b.height)) == (200, 300)     # size kept
        assert round(b.x1) == round(W) and round(b.y1) == round(H)  # on the border
        # negative origin → shift right/down, size kept
        b2 = fit_box_keep_size(Box(-40, -10, 60, 90), W, H)
        assert b2.x0 == 0 and b2.y0 == 0 and (round(b2.width), round(b2.height)) == (100, 100)

    def test_fit_keep_size_shrinks_only_when_larger_than_page(self):
        b = fit_box_keep_size(Box(-100, -100, W + 100, H + 100), W, H)
        assert b.x0 == 0 and b.y0 == 0 and round(b.x1) == round(W) and round(b.y1) == round(H)

    def test_minimum_size_enforced(self):
        b = clamp_box(Box(300, 300, 300, 300), W, H)
        assert b.width >= MIN_RECT and b.height >= MIN_RECT


class TestResizeByHandle:
    """Dragging a handle must move only the edges it owns; the opposite edge stays put."""
    def setup_method(self):
        self.box = Box(100, 100, 300, 300)

    def test_east_moves_only_right_edge(self):
        out = resize_by_handle(self.box, "E", 50, 0, W, H)
        assert out == Box(100, 100, 350, 300)

    def test_west_moves_only_left_edge(self):
        out = resize_by_handle(self.box, "W", 50, 0, W, H)
        assert out == Box(150, 100, 300, 300)

    def test_south_moves_only_bottom_edge(self):
        out = resize_by_handle(self.box, "S", 0, 40, W, H)
        assert out == Box(100, 100, 300, 340)

    def test_north_moves_only_top_edge(self):
        out = resize_by_handle(self.box, "N", 0, -40, W, H)
        assert out == Box(100, 60, 300, 300)

    @pytest.mark.parametrize("handle,dx,dy,expect", [
        ("NW", -10, -20, Box(90, 80, 300, 300)),
        ("NE", 20, -20, Box(100, 80, 320, 300)),
        ("SE", 25, 25, Box(100, 100, 325, 325)),
        ("SW", -15, 30, Box(85, 100, 300, 330)),
    ])
    def test_corners_move_two_edges(self, handle, dx, dy, expect):
        assert resize_by_handle(self.box, handle, dx, dy, W, H) == expect

    def test_drag_past_opposite_edge_keeps_min_size(self):
        out = resize_by_handle(self.box, "E", -10_000, 0, W, H)
        assert out.width >= MIN_RECT and 0 <= out.x0 < out.x1 <= W

    @pytest.mark.parametrize("handle", list("NW N NE E SE S SW W".split()))
    def test_result_always_valid_and_on_page(self, handle):
        out = resize_by_handle(self.box, handle, 5000, -5000, W, H)
        assert 0 <= out.x0 < out.x1 <= W
        assert 0 <= out.y0 < out.y1 <= H
        assert out.width >= MIN_RECT and out.height >= MIN_RECT


class TestMoveBox:
    def test_translate_preserves_size(self):
        out = move_box(Box(100, 100, 200, 250), 50, 30, W, H)
        assert out == Box(150, 130, 250, 280)

    def test_clamped_at_right_bottom(self):
        b = Box(100, 100, 200, 250)
        out = move_box(b, 10_000, 10_000, W, H)
        assert out.x1 == W and out.y1 == H
        assert out.width == b.width and out.height == b.height       # size kept

    def test_clamped_at_origin(self):
        out = move_box(Box(100, 100, 200, 250), -10_000, -10_000, W, H)
        assert out.x0 == 0 and out.y0 == 0


class TestHitHandle:
    def setup_method(self):
        self.box = Box(100, 100, 300, 300)

    def test_corner_hit(self):
        assert hit_handle(self.box, 102, 103, tol=8) == "NW"

    def test_edge_midpoint_hit(self):
        assert hit_handle(self.box, 300, 200, tol=6) == "E"        # E midpoint = (300,200)

    def test_centre_misses_all_handles(self):
        assert hit_handle(self.box, 200, 200, tol=10) is None

    def test_just_outside_tolerance_is_none(self):
        assert hit_handle(self.box, 320, 100, tol=8) is None       # 20px from NE, tol 8

    def test_all_eight_handles_are_hittable(self):
        for name, (hx, hy) in handle_positions(self.box).items():
            assert hit_handle(self.box, hx, hy, tol=4) == name


class TestPointInBox:
    def test_inside_and_edges(self):
        b = Box(100, 100, 300, 300)
        assert point_in_box(b, 200, 200)
        assert point_in_box(b, 100, 100)            # corner counts as inside
        assert not point_in_box(b, 99, 200)


def test_simulated_mouse_drag_sequence():
    """Grab SE handle, drag it out, then drag the whole box — as the UI does."""
    box = Box(0, 0, 300, 400)
    resized = resize_by_handle(box, "SE", 40, 25, W, H)
    assert resized == Box(0, 0, 340, 425)
    moved = move_box(resized, 50, 10, W, H)
    assert moved.x0 == 50 and moved.y0 == 10
    assert moved.width == resized.width and moved.height == resized.height


class TestUnionBox:
    """union_box: constant W=max(width), H=max(height) — not the bounding span (#1, #2)."""
    def test_size_is_max_not_bounding_span(self):
        boxes = [Box(10, 10, 110, 210),          # 100 × 200, left/top-most
                 Box(400, 300, 460, 360)]         # 60 × 60, far to the right/bottom
        u = union_box(boxes)
        assert u.width == 100 and u.height == 200          # max dims, NOT 450×350 span
        assert u.x0 == 10 and u.y0 == 10                   # top-/left-most corner

    def test_single_box(self):
        u = union_box([Box(5, 6, 55, 106)])
        assert (u.width, u.height) == (50, 100)


class TestAutoCropRect:
    """The per-page crop frame: constant size + independent edges (#1, #2, #7, #8)."""
    def setup_method(self):
        self.union = Box(50, 60, 250, 460)        # constant W=200, H=400
        self.pageA = Box(50, 60, 240, 450)        # page A content
        self.pageB = Box(80, 90, 300, 500)        # page B content (different position/size)

    def _crop(self, page, al, at, l=0.0, t=0.0, r=0.0, b=0.0):
        return auto_crop_rect(page, self.union, al, at, l, t, r, b, W, H)

    def test_constant_size_across_pages(self):
        a = self._crop(self.pageA, True, True)
        b = self._crop(self.pageB, True, True)
        assert (round(a.width), round(a.height)) == (200, 400)   # both pages -> same W×H
        assert (round(b.width), round(b.height)) == (200, 400)

    def test_anchor_on_uses_page_edge(self):
        a = self._crop(self.pageA, True, True)
        assert a.x0 == self.pageA.x0 and a.y0 == self.pageA.y0

    def test_anchor_off_uses_union_edge(self):
        a = self._crop(self.pageB, False, False if False else True)  # left OFF, top ON
        # left OFF -> union.x0; top ON -> page B's y0
        assert a.x0 == self.union.x0 and a.y0 == self.pageB.y0

    def test_left_offset_moves_only_left_edge(self):
        base = self._crop(self.pageA, True, True)
        moved = self._crop(self.pageA, True, True, l=10.0)        # +10% page width
        assert moved.x0 < base.x0                                  # left edge moved out
        assert moved.x1 == base.x1                                 # right edge unchanged (#8)
        assert moved.y0 == base.y0 and moved.y1 == base.y1         # top/bottom unchanged

    def test_bottom_offset_moves_only_bottom_edge(self):
        base = self._crop(self.pageA, True, True)
        moved = self._crop(self.pageA, True, True, b=10.0)
        assert moved.y1 > base.y1                                  # bottom edge moved down
        assert moved.y0 == base.y0                                 # top unchanged (#8)
        assert moved.x0 == base.x0 and moved.x1 == base.x1

    def test_left_drag_does_not_move_bottom(self):
        """The reported bug: dragging the left side jumped the bottom to the page edge."""
        base = self._crop(self.pageA, True, True)
        moved = self._crop(self.pageA, True, True, l=8.0)
        assert moved.y1 == base.y1                                 # bottom stays put

    def test_overflow_shifts_keeping_constant_size(self):
        """#5: content near the right/bottom edge → the anchored W×H frame is SHIFTED inward
        (opposite edge extends), never shrunk — the constant size is preserved on every page."""
        near_corner = Box(W - 30, H - 30, W - 10, H - 10)          # base would extend off-page
        a = self._crop(near_corner, True, True)                    # anchors ON, offsets 0
        assert (round(a.width), round(a.height)) == (200, 400)     # size NOT shrunk
        assert a.x0 >= 0 and a.y0 >= 0 and a.x1 <= W and a.y1 <= H  # fully on-page
        assert round(a.x1) == round(W) and round(a.y1) == round(H)  # trailing edge on the border


class TestRotateBoxCw:
    """rotate_box_cw lets crops/detection survive a 90° page turn (#6)."""

    def test_maps_corners_into_rotated_page(self):
        # (x,y) -> (h - y, x); page w×h -> h×w. Box stays in-bounds of the rotated page.
        b = rotate_box_cw(Box(10, 20, 30, 60), 100.0, 200.0)
        assert b == Box(200 - 60, 10, 200 - 20, 30)                # (140, 10, 180, 30)
        assert 0 <= b.x0 <= b.x1 <= 200 and 0 <= b.y0 <= b.y1 <= 100

    def test_four_turns_return_original(self):
        b0 = Box(12, 34, 56, 78)
        b, w, h = b0, 595.0, 842.0
        for _ in range(4):
            b = rotate_box_cw(b, w, h)
            w, h = h, w                                            # dims swap each quarter turn
        assert b == b0
