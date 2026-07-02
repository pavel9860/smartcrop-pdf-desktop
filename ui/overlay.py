"""Crop-rect + handle drawing onto the page canvas (spec §9). Pure drawing: given boxes already
mapped to canvas pixels (via the caller's `to_canvas`), draws the dashed auto-crop frame or the
numbered split rectangles, their 8 handles, move-sign and numbered badge. No model access, no
event handling
— canvas_view.py owns the coordinate mapping and gesture wiring.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from core.geometry import Box, handle_positions
from core.model import OverlayBox
from ui.constants import (
    HANDLE_R,
    SPLIT_BADGE_FONT_SIZE,
    SPLIT_BADGE_MARGIN,
    SPLIT_BADGE_R,
    THEMES,
)

ToCanvas = Callable[[float, float], tuple[float, float]]

_WINDOW_DASH = (6, 4)  # every crop/split window border is dashed (spec §9.1, §9.6)


def draw_overlay(canvas: tk.Canvas, boxes: tuple[OverlayBox, ...], draw_rect: Box | None,
                  to_canvas: ToCanvas) -> None:
    for ob in boxes:
        _draw_box(canvas, ob.box, to_canvas, kind=ob.kind, index=ob.index)
    if draw_rect is not None:
        x0, y0 = to_canvas(draw_rect.x0, draw_rect.y0)
        x1, y1 = to_canvas(draw_rect.x1, draw_rect.y1)
        canvas.create_rectangle(x0, y0, x1, y1, outline=str(THEMES["crop_blue"]), width=2,
                                 dash=(4, 3), tags="overlay")


def _draw_box(canvas: tk.Canvas, box: Box, to_canvas: ToCanvas, *, kind: str, index: int) -> None:
    x0, y0 = to_canvas(box.x0, box.y0)
    x1, y1 = to_canvas(box.x1, box.y1)
    colour = str(THEMES["split_blue"]) if kind == "split" else str(THEMES["crop_blue"])
    canvas.create_rectangle(x0, y0, x1, y1, outline=colour, width=3 if kind == "split" else 2,
                             dash=_WINDOW_DASH, tags="overlay")
    _draw_handles(canvas, Box(x0, y0, x1, y1), colour)
    if kind == "split":
        _draw_split_badge(canvas, x0, y0, colour, index)


def _draw_handles(canvas: tk.Canvas, canvas_box: Box, colour: str) -> None:
    for _name, (hx, hy) in handle_positions(canvas_box).items():
        canvas.create_rectangle(hx - HANDLE_R, hy - HANDLE_R, hx + HANDLE_R, hy + HANDLE_R,
                                 fill=colour, outline="", tags="overlay")


def _draw_split_badge(canvas: tk.Canvas, x0: float, y0: float, colour: str, index: int) -> None:
    """Numbered badge marking output order, at the window's top-left corner (spec §9.6)."""
    cx = x0 + SPLIT_BADGE_MARGIN + SPLIT_BADGE_R
    cy = y0 + SPLIT_BADGE_MARGIN + SPLIT_BADGE_R
    canvas.create_oval(cx - SPLIT_BADGE_R, cy - SPLIT_BADGE_R, cx + SPLIT_BADGE_R,
                        cy + SPLIT_BADGE_R, outline=colour, width=2, fill="", tags="overlay")
    canvas.create_text(cx, cy, text=str(index + 1), fill=colour,
                        font=("", SPLIT_BADGE_FONT_SIZE, "bold"), tags="overlay")
