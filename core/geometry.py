"""Pure crop-rectangle geometry — no Tk, no cv2. Shared by the UI and the tests so
the mouse-crop adjustment math has exactly one implementation.

Coordinates are page/PDF units (origin top-left). A handle is one of the 8 compass
names; dragging it moves only the edges it owns (so the opposite edge never moves).
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

MIN_RECT = 5.0

# Which Box edges each handle moves.
HANDLE_EDGES: Dict[str, Tuple[str, ...]] = {
    "NW": ("x0", "y0"), "N": ("y0",), "NE": ("x1", "y0"), "E": ("x1",),
    "SE": ("x1", "y1"), "S": ("y1",), "SW": ("x0", "y1"), "W": ("x0",),
}


class Box:
    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0, self.y0, self.x1, self.y1 = float(x0), float(y0), float(x1), float(y1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Box) and self.as_tuple() == other.as_tuple()

    def __repr__(self) -> str:
        return f"Box({self.x0:.1f}, {self.y0:.1f}, {self.x1:.1f}, {self.y1:.1f})"


def clamp_box(b: Box, w: float, h: float) -> Box:
    """Clamp a box inside the page (w×h), keeping it at least MIN_RECT in each axis."""
    x0 = max(0.0, min(b.x0, w - MIN_RECT))
    y0 = max(0.0, min(b.y0, h - MIN_RECT))
    x1 = min(w, max(b.x1, x0 + MIN_RECT))
    y1 = min(h, max(b.y1, y0 + MIN_RECT))
    return Box(x0, y0, x1, y1)


def fit_box_keep_size(b: Box, w: float, h: float) -> Box:
    """Place `b` fully inside the page (w×h) WITHOUT changing its size: if it overhangs an edge,
    translate it inward (the opposite edge takes up the slack). A side is shrunk to the page
    (>= MIN_RECT) only when the box is itself larger than the page in that axis. This preserves
    the constant W×H of the auto-crop frame on every page (§9.2) — shift, don't shrink."""
    bw = max(MIN_RECT, min(b.width, w))
    bh = max(MIN_RECT, min(b.height, h))
    x0 = min(max(b.x0, 0.0), max(0.0, w - bw))
    y0 = min(max(b.y0, 0.0), max(0.0, h - bh))
    return Box(x0, y0, x0 + bw, y0 + bh)


def anchored_base(page_box: Box, union: Box, anchor_left: bool, anchor_top: bool,
                  w: float, h: float) -> Box:
    """The constant-`union`-size crop frame placed on the page *before* offsets: anchored to this
    page's content edge (anchor ON) or the union edge (OFF), then shifted inward to stay on-page
    at the full W×H (§9.2). Shared by the live crop, drag round-trip and offset clamp so all three
    agree on the same base."""
    lb = page_box.x0 if anchor_left else union.x0
    tb = page_box.y0 if anchor_top else union.y0
    return fit_box_keep_size(Box(lb, tb, lb + union.width, tb + union.height), w, h)


def resize_by_handle(box: Box, handle: str, dx: float, dy: float,
                     w: float, h: float) -> Box:
    """New box after dragging `handle` by (dx, dy). Only the handle's edges move;
    edges can't cross (kept ≥ MIN_RECT apart) and the result is clamped to the page."""
    c = {"x0": box.x0, "y0": box.y0, "x1": box.x1, "y1": box.y1}
    for edge in HANDLE_EDGES[handle]:
        c[edge] += dx if edge in ("x0", "x1") else dy
    fixed = Box(min(c["x0"], c["x1"] - MIN_RECT), min(c["y0"], c["y1"] - MIN_RECT),
                max(c["x1"], c["x0"] + MIN_RECT), max(c["y1"], c["y0"] + MIN_RECT))
    return clamp_box(fixed, w, h)


def move_box(box: Box, dx: float, dy: float, w: float, h: float) -> Box:
    """Translate the whole box by (dx, dy), keeping it fully inside the page."""
    nx0 = min(max(0.0, box.x0 + dx), w - box.width)
    ny0 = min(max(0.0, box.y0 + dy), h - box.height)
    return Box(nx0, ny0, nx0 + box.width, ny0 + box.height)


def rotate_box_cw(b: Box, w: float, h: float) -> Box:
    """A box in a `w`×`h` page, rotated 90° clockwise → its coordinates in the resulting
    `h`×`w` page. Lets crops/detection survive a page rotation instead of being dropped.
    Four applications return the original box (rotate_box_cw is its own 4-cycle)."""
    return Box(h - b.y1, b.x0, h - b.y0, b.x1)


def handle_positions(box: Box) -> Dict[str, Tuple[float, float]]:
    """The 8 handle anchor points in page coordinates."""
    mx, my = (box.x0 + box.x1) / 2.0, (box.y0 + box.y1) / 2.0
    return {"NW": (box.x0, box.y0), "N": (mx, box.y0), "NE": (box.x1, box.y0),
            "E": (box.x1, my), "SE": (box.x1, box.y1), "S": (mx, box.y1),
            "SW": (box.x0, box.y1), "W": (box.x0, my)}


def hit_handle(box: Box, x: float, y: float, tol: float) -> Optional[str]:
    """Name of the handle within `tol` of (x, y), or None. Corners win over edges."""
    for name, (hx, hy) in handle_positions(box).items():
        if abs(x - hx) <= tol and abs(y - hy) <= tol:
            return name
    return None


def point_in_box(box: Box, x: float, y: float) -> bool:
    return box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1


# --------------------------------------------------------------- auto-detect frame
def union_box(boxes: Iterable[Box]) -> Box:
    """Constant crop frame for a set of per-page content boxes.

    Size is the *largest* content width and height seen across pages — W = max(right-left),
    H = max(bottom-top) — so every page is cropped to one constant W×H (not the bounding
    span of all edges, which would over-crop). Position is the top-/left-most content
    corner, used as the base when an anchor is OFF.
    """
    boxes = list(boxes)
    if not boxes:
        raise ValueError("union_box: no boxes")
    x0 = min(b.x0 for b in boxes)
    y0 = min(b.y0 for b in boxes)
    w = max(b.width for b in boxes)
    h = max(b.height for b in boxes)
    return Box(x0, y0, x0 + w, y0 + h)


def auto_crop_rect(page_box: Box, union: Box, anchor_left: bool, anchor_top: bool,
                   left_off: float, top_off: float, right_off: float, bottom_off: float,
                   w: float, h: float) -> Box:
    """Per-page crop rectangle from the constant `union` frame.

    Each edge is independent: `left_off` moves only the left edge, `right_off` only the
    right, etc. (right/bottom are anchored to `union` size, NOT to the moved left/top — so
    dragging one edge never drags its opposite). Anchor ON pins the left/top to *this*
    page's content edge; OFF pins it to the union (cross-page) edge. Offsets are percent
    of page width/height.
    """
    base = anchored_base(page_box, union, anchor_left, anchor_top, w, h)   # shifted, never shrunk
    left = base.x0 - left_off / 100.0 * w
    top = base.y0 - top_off / 100.0 * h
    right = base.x0 + union.width + right_off / 100.0 * w
    bottom = base.y0 + union.height + bottom_off / 100.0 * h
    return clamp_box(Box(left, top, right, bottom), w, h)
