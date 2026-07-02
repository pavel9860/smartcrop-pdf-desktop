"""The page canvas (spec §5, §9): paints from `AppModel.view_snapshot()`, fits the page to the
window (never magnified, never overflowing — §5/§14), and translates raw Tk mouse/wheel events
into page-unit coordinates for `AppModel.begin_drag/update_drag/end_drag/cancel_drag`. All hit
testing for cursor/clicks is the model's own (`core.geometry`, shared pure leaf) — this module
owns only the canvas <-> page-unit coordinate mapping and event wiring, never gesture logic.

The output-page position ("3 / 312") is drawn directly on the page image at its bottom-left
corner (§6, §19) — position only, no coordinate read-out. The fitted page bitmap is cached per
(raster, size) — `PHOTO_CACHE` entries — so page navigation and drag repaints skip the full-page
resample (§17).
"""
from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from core.geometry import hit_handle, point_in_box
from core.model import AppModel, ViewSnapshot
from core.render import fit_scale
from ui import overlay
from ui.constants import (
    CANVAS_STATUS_FONT_SIZE,
    HANDLE_CURSOR,
    HANDLE_R,
    HANDLE_SLACK,
    PHOTO_CACHE,
    STATUS_PAD,
)

_STATUS_FONT = ("", CANVAS_STATUS_FONT_SIZE)
_STATUS_FG = "#e8e8e8"
_STATUS_SHADOW = "#000000"

# cache key → (source image ref, PhotoImage); the ref pins the raster so Python can't recycle
# its id() while the entry lives, making the id-based key collision-free.
_PhotoEntry = tuple[Image.Image, "ImageTk.PhotoImage"]


class CanvasView:
    def __init__(self, parent: ctk.CTkBaseClass, model: AppModel,
                 on_change: Callable[[], None],
                 on_nav: Callable[[], None] | None = None) -> None:
        self.model = model
        self._on_change = on_change
        self._on_nav = on_nav or on_change
        self.canvas = tk.Canvas(parent, highlightthickness=0, bg="#1b1b1b")
        self.canvas.pack(fill="both", expand=True)
        self._scale = 1.0
        self._img_x = 0.0
        self._img_y = 0.0
        self._photo: ImageTk.PhotoImage | None = None
        self._photo_cache: OrderedDict[tuple[int, int, int], _PhotoEntry] = OrderedDict()
        self._snap: ViewSnapshot | None = None
        self._bind_events()

    def _bind_events(self) -> None:
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._right_click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", self._wheel_prev)
        self.canvas.bind("<Button-5>", self._wheel_next)

    # ── paint (spec §12.1 WYSIWYG; §5 fit-to-window) ─────────────────────────────────────────
    def redraw(self) -> ViewSnapshot:
        snap = self.model.view_snapshot()
        self._snap = snap
        self.canvas.delete("all")
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self._scale = fit_scale(snap.page_w, snap.page_h, cw, ch, 0)
        iw = max(1, round(snap.page_w * self._scale))
        ih = max(1, round(snap.page_h * self._scale))
        self._img_x = (cw - iw) / 2
        self._img_y = max(0, (ch - ih) // 2 if ih < ch else 0)
        self._photo = self._fitted_photo(snap.image, iw, ih)
        self.canvas.create_image(self._img_x, self._img_y, anchor="nw", image=self._photo)
        overlay.draw_overlay(self.canvas, snap.overlay, snap.draw_rect, self._to_canvas)
        self._draw_status(snap.status)
        return snap

    def _fitted_photo(self, image: Image.Image, iw: int, ih: int) -> ImageTk.PhotoImage:
        """The fitted page bitmap, LRU-cached per (raster, size) so nav/drag repaints skip the
        full-page LANCZOS resample (§17). The stored image ref pins the key's id()."""
        key = (id(image), iw, ih)
        hit = self._photo_cache.get(key)
        if hit is not None and hit[0] is image:
            self._photo_cache.move_to_end(key)
            return hit[1]
        resized = image.resize((iw, ih), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized)  # type: ignore[no-untyped-call]
        self._photo_cache[key] = (image, photo)
        while len(self._photo_cache) > PHOTO_CACHE:
            self._photo_cache.popitem(last=False)
        return photo

    def _draw_status(self, text: str) -> None:
        """Position text at the page image's bottom-left corner (§6, §19)."""
        if not text:
            return
        ih = max(1, round((self._snap.page_h if self._snap else 1) * self._scale))
        x = self._img_x + STATUS_PAD
        y = self._img_y + ih - STATUS_PAD
        self.canvas.create_text(x + 1, y + 1, text=text, anchor="sw",
                                fill=_STATUS_SHADOW, font=_STATUS_FONT, tags="status")
        self.canvas.create_text(x, y, text=text, anchor="sw",
                                fill=_STATUS_FG, font=_STATUS_FONT, tags="status")

    # ── coordinate mapping ────────────────────────────────────────────────────────────────────
    def _to_page(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self._img_x) / self._scale, (cy - self._img_y) / self._scale

    def _to_canvas(self, px: float, py: float) -> tuple[float, float]:
        return px * self._scale + self._img_x, py * self._scale + self._img_y

    def _tol(self) -> float:
        return (HANDLE_R + HANDLE_SLACK) / self._scale if self._scale else 0.0

    # ── gestures (§9.3, §9.6) ────────────────────────────────────────────────────────────────
    def _press(self, event: tk.Event[tk.Misc]) -> None:
        px, py = self._to_page(event.x, event.y)
        self.model.begin_drag(px, py, self._tol())
        self.redraw()

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        px, py = self._to_page(event.x, event.y)
        self.model.update_drag(px, py)
        self.redraw()

    def _release(self, _event: tk.Event[tk.Misc]) -> None:
        self.model.end_drag()
        self._on_change()

    def _right_click(self, _event: tk.Event[tk.Misc]) -> None:
        self.cancel_drag()

    def cancel_drag(self) -> None:
        """Esc (app_window.py) or a right-click (spec §9.3, §21, inv 24)."""
        self.model.cancel_drag()
        self._on_change()

    # ── wheel turns pages, never zooms (§5, §21) ─────────────────────────────────────────────
    def _wheel(self, event: tk.Event[tk.Misc]) -> None:
        (self.model.prev_page if event.delta > 0 else self.model.next_page)()
        self._on_nav()

    def _wheel_prev(self, _event: tk.Event[tk.Misc]) -> None:
        self.model.prev_page()
        self._on_nav()

    def _wheel_next(self, _event: tk.Event[tk.Misc]) -> None:
        self.model.next_page()
        self._on_nav()

    # ── hover: cursor maps to the action (§9.5) ─────────────────────────────────────────────
    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        snap = self._snap
        if snap is None:
            return
        px, py = self._to_page(event.x, event.y)
        self._update_cursor(snap, px, py)

    def _update_cursor(self, snap: ViewSnapshot, px: float, py: float) -> None:
        tol = self._tol()
        cursor = ""
        for ob in snap.overlay:
            handle = hit_handle(ob.box, px, py, tol)
            if handle is not None:
                cursor = HANDLE_CURSOR[handle]
                break
            if point_in_box(ob.box, px, py):
                cursor = "fleur"
        self.canvas.configure(cursor=cursor)



