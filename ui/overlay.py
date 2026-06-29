"""Crop-rect + handle drawing onto the page canvas (spec §9). Pure drawing: given boxes already
mapped to canvas pixels (via the caller's `to_canvas`), draws the dashed auto-crop frame or the
numbered split rectangles, their 8 handles and the move-sign. No model access, no event handling
— canvas_view.py owns the coordinate mapping and gesture wiring.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from core.geometry import Box, handle_positions
from core.model import OverlayBox
from ui.constants import THEMES

ToCanvas = Callable[[float, float], tuple[float, float]]


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
    dash = () if kind == "split" else (6, 4)
    canvas.create_rectangle(x0, y0, x1, y1, outline=colour, width=3 if kind == "split" else 2,
                             dash=dash, tags="overlay")
    _draw_handles(canvas, Box(x0, y0, x1, y1), colour)
    _draw_move_sign(canvas, x1, y0, colour)
    if kind == "split":
        canvas.create_text(x0 + 14, y0 + 12, text=str(index + 1), fill=colour,
                            font=("", 14, "bold"), tags="overlay")


def _draw_handles(canvas: tk.Canvas, canvas_box: Box, colour: str) -> None:
    for _name, (hx, hy) in handle_positions(canvas_box).items():
        canvas.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill=colour, outline="",
                                 tags="overlay")


def _draw_move_sign(canvas: tk.Canvas, x1: float, y0: float, colour: str) -> None:
    """Cosmetic affordance at the top-right corner (§9.1); the model treats any non-handle point
    inside the box as a move, so this glyph marks intent rather than gating a separate hit-zone."""
    r = 6.0
    canvas.create_oval(x1 - 2.4 * r, y0 - 0.4 * r, x1 + 0.4 * r, y0 + 2.4 * r,
                        outline=colour, width=2, tags="overlay")
