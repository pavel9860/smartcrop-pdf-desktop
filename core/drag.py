"""`DragState` — the transient, per-gesture interaction state (ARCHITECTURE §5.4).

Replaces the legacy `_drag: dict`. A frozen variant per gesture; `AppModel.begin_drag` hit-tests
and constructs the right one, `update_drag` reads it, `end_drag`/`cancel_drag` consume it. A
`None` handle means "move the whole rectangle"; a named handle means "resize that edge/corner".
"""
from __future__ import annotations

from dataclasses import dataclass

from core.document_state import Offsets
from core.geometry import Box

Point = tuple[float, float]


@dataclass(frozen=True)
class AutoDrag:
    """Resize (handle set) or move (handle None) the live auto-crop, written back as offsets."""
    handle: str | None
    rect0: Box
    start: Point
    page_w: float
    page_h: float
    offsets0: Offsets
    left_base: float
    top_base: float


@dataclass(frozen=True)
class SplitDrag:
    """Resize (handle set) or move (handle None) split rectangle `idx`."""
    idx: int
    handle: str | None
    rect0: Box
    start: Point


@dataclass(frozen=True)
class DrawDrag:
    """Rubber-band a new drawn crop window on an uncommitted page (§9.4) — not a commit."""
    start: Point


@dataclass(frozen=True)
class WindowDrag:
    """Resize (handle set) or move (handle None) the page's drawn crop window (§9.4)."""
    handle: str | None
    rect0: Box
    start: Point


@dataclass(frozen=True)
class CropEditDrag:
    """Rubber-band a tightening crop within a committed page (§9.3)."""
    start: Point


DragState = AutoDrag | SplitDrag | DrawDrag | WindowDrag | CropEditDrag
