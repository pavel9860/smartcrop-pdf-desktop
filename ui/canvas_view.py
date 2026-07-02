"""The page canvas (spec §5, §9): paints from `AppModel.view_snapshot()`, fits the page to the
window (never magnified, never overflowing — §5/§14), and translates raw Tk mouse/wheel events
into page-unit coordinates for `AppModel.begin_drag/update_drag/end_drag/cancel_drag`. All hit
testing for cursor/clicks is the model's own (`core.geometry`, shared pure leaf) — this module
owns only the canvas <-> page-unit coordinate mapping and event wiring, never gesture logic.

Nothing is drawn over the page image (inv 32): the pointer's coordinates (percent of the page)
show in a small label at the right pane's bottom-right corner and empty when the pointer leaves.
Hover nav arrows appear at the canvas's edge midpoints and disable at the document's ends
(inv 34, 37). The fitted page bitmap is cached per (raster, size) — `PHOTO_CACHE` entries — so
page navigation and drag repaints skip the full-page resample (§17).
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
    NAV_ARROW_H,
    NAV_ARROW_PAD,
    NAV_ARROW_W,
    PHOTO_CACHE,
    STATUS_PAD,
    THEMES,
)

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
        self._build_nav_arrows(parent)
        # Cursor read-out: bottom-right corner of the right pane — white, shared status font,
        # never drawn on the page image itself (§6, §19, inv 32).
        self.coords_label = ctk.CTkLabel(parent, text="", text_color="#FFFFFF",
                                         fg_color="transparent",
                                         font=ctk.CTkFont(size=CANVAS_STATUS_FONT_SIZE))
        self.coords_label.place(relx=1.0, rely=1.0, x=-STATUS_PAD, y=-STATUS_PAD, anchor="se")
        self._bind_events()

    def _build_nav_arrows(self, parent: ctk.CTkBaseClass) -> None:
        """Hover ◀/▶ at the canvas edge midpoints — same styling as the bottom nav (inv 34)."""
        def arrow(text: str, cmd: Callable[[], None]) -> ctk.CTkButton:
            return ctk.CTkButton(parent, text=text, command=cmd, width=NAV_ARROW_W,
                                 height=NAV_ARROW_H, fg_color=THEMES["secondary"],
                                 hover_color=THEMES["secondary_hover"],
                                 text_color=THEMES["secondary_text"])
        self.btn_arrow_prev = arrow("◀", lambda: self._arrow_nav(self.model.prev_page))
        self.btn_arrow_next = arrow("▶", lambda: self._arrow_nav(self.model.next_page))

    def set_arrow_states(self, prev_disabled: bool, next_disabled: bool) -> None:
        """Disable each arrow at its end of the document, like the bottom nav (inv 37)."""
        self.btn_arrow_prev.configure(state="disabled" if prev_disabled else "normal")
        self.btn_arrow_next.configure(state="disabled" if next_disabled else "normal")

    def _arrow_nav(self, command: Callable[[], None]) -> None:
        command()
        self._on_nav()

    def _show_arrows(self, _event: object = None) -> None:
        self.btn_arrow_prev.place(relx=0.0, rely=0.5, x=NAV_ARROW_PAD, anchor="w")
        self.btn_arrow_next.place(relx=1.0, rely=0.5, x=-NAV_ARROW_PAD, anchor="e")

    def _hide_arrows(self, _event: object = None) -> None:
        holder = self.canvas.master
        px, py = holder.winfo_pointerxy()
        inside = (holder.winfo_rootx() <= px < holder.winfo_rootx() + holder.winfo_width()
                  and holder.winfo_rooty() <= py < holder.winfo_rooty() + holder.winfo_height())
        if not inside:                           # ignore Leave events caused by the arrows
            self.btn_arrow_prev.place_forget()
            self.btn_arrow_next.place_forget()

    def _bind_events(self) -> None:
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._right_click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._pointer_left)
        self.canvas.bind("<Enter>", self._show_arrows)
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

    # ── hover: cursor maps to the action (§9.5); coords read-out bottom-right (§6, inv 32) ──
    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        snap = self._snap
        if snap is None:
            return
        px, py = self._to_page(event.x, event.y)
        self._update_cursor(snap, px, py)
        self._update_coords(snap, px, py)

    def _update_coords(self, snap: ViewSnapshot, px: float, py: float) -> None:
        if snap.page_w <= 0 or not (0 <= px <= snap.page_w and 0 <= py <= snap.page_h):
            text = ""                            # pointer off the page → empty read-out
        else:
            text = f"x {px / snap.page_w * 100.0:.1f}%  y {py / snap.page_h * 100.0:.1f}%"
        if self.coords_label.cget("text") != text:
            self.coords_label.configure(text=text)

    def _pointer_left(self, event: tk.Event[tk.Misc]) -> None:
        if self.coords_label.cget("text"):
            self.coords_label.configure(text="")
        self._hide_arrows(event)

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



