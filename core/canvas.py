"""Canvas rendering, the crop-handle overlay, mouse drag/resize/move and page navigation
for SmartCropApp. The committed-page preview uses the shared core.render path so it
matches the export pixel-for-pixel. Mixed into SmartCropApp; see core/app.py.
"""
from __future__ import annotations

from typing import List, Optional

from PIL import Image, ImageTk

from core import render, viewmodel
from core.constants import CANVAS_MARGIN, HANDLE_R, HANDLE_SLACK
from core.geometry import (Box, MIN_RECT, HANDLE_CURSOR, anchored_base, clamp_box, hit_handle,
                           move_box, point_in_box, resize_by_handle)
from core.theme import CROP_BLUE, SPLIT_BLUE

class CanvasMixin:
    """Page rendering, crop overlay, drag interactions and output-page navigation."""
    # ════════════════════════════════════════════════════════════════════
    #  CANVAS
    # ════════════════════════════════════════════════════════════════════
    def _pdf_to_canvas(self, x, y):
        return self.img_x + x * self.scale, self.img_y + y * self.scale

    def _canvas_to_pdf(self, x, y):
        return (x - self.img_x) / self.scale, (y - self.img_y) / self.scale

    def render_page(self) -> None:
        if self.page_count() == 0 or not hasattr(self, "canvas"):
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        self.canvas.configure(bg=self._theme()["CANVAS_BG"])
        w, h = self._page_dims(self.current_page)
        work = self._work_image(self.current_page)
        applied = self._applied.get(self.current_page)
        if applied:                                  # committed page → show the EXACT export image
            self.view_box = max(0, min(self.view_box, len(applied) - 1))
            box = applied[self.view_box]             # crop + resize identically to the exporter
            work = render.output_image(work, box, w, h, self._target_size(box.width, box.height),
                                       self._remove_colours())
            w, h = work.width, work.height           # WYSIWYG: preview pixels == saved pixels
        else:
            self.view_box = 0
        self._view_dims = (w, h)                      # the shown image's dims (crop-edit maps in it)
        self.scale = render.fit_scale(w, h, cw, ch, CANVAS_MARGIN)
        disp = work.resize((max(1, round(w * self.scale)), max(1, round(h * self.scale))),
                           Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(disp)
        self.img_x = max(0, (cw - disp.width) // 2)
        self.img_y = max(0, (ch - disp.height) // 2)
        self.canvas.delete("all")
        self.canvas.create_image(self.img_x, self.img_y, anchor="nw", image=self.tk_image)
        if not applied:                              # no handles/overlay over a committed crop
            self._draw_overlay()
        self.page_var.set(str(self._view_position() + 1))     # output-page numbering (split-aware)
        self.page_total.configure(text=f"/ {self._view_total()}")
        if not self._busy:
            self.status.configure(text=self._view_status())
        self._set_controls_enabled(not self._busy)

    def _draw_overlay(self) -> None:
        t = self._theme()
        split = self.split_count > 1
        if self._draw_rect is not None:               # rubber-band for a new crop area
            dx0, dy0 = self._pdf_to_canvas(self._draw_rect.x0, self._draw_rect.y0)
            dx1, dy1 = self._pdf_to_canvas(self._draw_rect.x1, self._draw_rect.y1)
            self.canvas.create_rectangle(dx0, dy0, dx1, dy1, outline=CROP_BLUE, width=2, dash=(4, 3))
            return
        for i, box in enumerate(self._preview_boxes()):
            if box is None:
                continue
            color = SPLIT_BLUE if split else CROP_BLUE
            width = 4 if split else 3                  # split lines 30% thicker, absolute
            x0, y0 = self._pdf_to_canvas(box.x0, box.y0)
            x1, y1 = self._pdf_to_canvas(box.x1, box.y1)
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=width, dash=(6, 4))
            for hx, hy in self._handle_positions(box).values():
                self.canvas.create_polygon(hx, hy - HANDLE_R, hx + HANDLE_R, hy, hx, hy + HANDLE_R,
                                           hx - HANDLE_R, hy, fill=t["HANDLE_FILL"],
                                           outline=t["HANDLE"], width=2)
            if split:                                 # big number, no circle, dark blue
                self.canvas.create_text(x0 + 20, y0 + 20, text="①②③④"[i], fill=SPLIT_BLUE,
                                        font=("Segoe UI", 28, "bold"), anchor="nw")
            elif self.auto_active:
                self.canvas.create_text(x0 + 13, y0 + 13, text="✦", fill=CROP_BLUE,
                                        font=("Segoe UI", 16, "bold"), anchor="nw")

    def _preview_boxes(self) -> List[Optional[Box]]:
        if self.split_count > 1:
            return list(self.crop_rects)
        return [self._crop_rect(self.current_page)]

    def _handle_positions(self, box: Box):
        x0, y0 = self._pdf_to_canvas(box.x0, box.y0)
        x1, y1 = self._pdf_to_canvas(box.x1, box.y1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return {"NW": (x0, y0), "N": (mx, y0), "NE": (x1, y0), "E": (x1, my),
                "SE": (x1, y1), "S": (mx, y1), "SW": (x0, y1), "W": (x0, my)}

    def _hit_handle(self, box, ex, ey):
        px, py = self._canvas_to_pdf(ex, ey)             # hit-test in page coords (shared logic)
        tol = (HANDLE_R + HANDLE_SLACK) / max(self.scale, 1e-6)
        return hit_handle(box, px, py, tol)

    def _on_press(self, event):
        if self.page_count() == 0 or self._busy:
            return
        # Stash (not drop) the committed crop: pressing reopens the full page for editing, but a
        # gesture that commits nothing (a stray click, a too-small draw) must NOT lose the crop —
        # it is restored on release. See _on_release / _commit_drawn_rect (bug: crop dropped on
        # a new draw / click).
        self._drag_moved = False
        applied = self._applied.get(self.current_page)
        if applied and self.split_count == 1:
            # Edit WITHIN the cropped view (§9.3, option a): a committed single-crop page stays
            # shown cropped — pressing starts a fresh rubber-band ON the crop that tightens it on
            # release (mapped back into the committed box). No flip to the full page, no "jump".
            px, py = self._canvas_to_pdf(event.x, event.y)
            self._drag = dict(kind="crop-edit", start=(px, py))
            self._draw_rect = None
            self.canvas.configure(cursor="crosshair")
            return
        self._prev_applied = self._applied.pop(self.current_page, None)
        if self._prev_applied is not None:           # split>1 committed: edit on the full page
            self.view_box = 0
            self.render_page()
        if self.split_count > 1:
            self._press_split(event)
        else:
            self._press_auto(event)

    def _on_canvas_wheel(self, e):
        """Mouse wheel turns pages — it never magnifies the page. The page view is always
        fit-to-window (§5), so there is no zoom-out-of-bounds state to land in."""
        (self.prev_page if getattr(e, "delta", 0) > 0 else self.next_page)()
        return "break"

    def _press_auto(self, event):
        box = self._crop_rect(self.current_page)
        px, py = self._canvas_to_pdf(event.x, event.y)
        handle = self._hit_handle(box, event.x, event.y) if box is not None else None
        w, h = self._page_dims(self.current_page)
        b = self._detect_cache.get(self.current_page) or Box(0, 0, w, h)
        u = self._union or Box(0, 0, w, h)
        ab = anchored_base(b, u, self.auto_left_var.get(), self.auto_top_var.get(), w, h)
        base = dict(rect0=box, start=(px, py), w=w, h=h,
                    off0=(self.left_off.get(), self.top_off.get(),
                          self.right_off.get(), self.bottom_off.get()),
                    left_base=ab.x0, top_base=ab.y0)
        if handle is not None:                       # resize one edge
            self._drag = dict(kind="auto", handle=handle, **base)
            self.canvas.configure(cursor=HANDLE_CURSOR[handle])
        elif box is not None and point_in_box(box, px, py):   # move the whole crop
            self._drag = dict(kind="auto-move", **base)
            self.canvas.configure(cursor="fleur")
        else:                                        # empty area → draw a fresh crop
            self._drag = dict(kind="draw", start=(px, py))
            self._draw_rect = None
            self.canvas.configure(cursor="crosshair")

    def _press_split(self, event):
        px, py = self._canvas_to_pdf(event.x, event.y)
        for i, box in enumerate(self.crop_rects):
            handle = self._hit_handle(box, event.x, event.y)
            if handle:
                self._drag = dict(kind="split-edge", idx=i, handle=handle, rect0=box, start=(px, py))
                self.canvas.configure(cursor=HANDLE_CURSOR[handle])
                return
            if box.x0 <= px <= box.x1 and box.y0 <= py <= box.y1:
                self._drag = dict(kind="split-move", idx=i, rect0=box, start=(px, py))
                self.canvas.configure(cursor="fleur")
                return

    def _on_drag(self, event):
        if self._drag is None:
            return
        self._drag_moved = True
        px, py = self._canvas_to_pdf(event.x, event.y)
        dx, dy = px - self._drag["start"][0], py - self._drag["start"][1]
        k = self._drag["kind"]
        if k == "auto":
            d = self._drag
            self._write_auto_offsets(resize_by_handle(d["rect0"], d["handle"], dx, dy, d["w"], d["h"]))
        elif k == "auto-move":                       # translate the whole auto crop
            d = self._drag
            self._write_auto_offsets(move_box(d["rect0"], dx, dy, d["w"], d["h"]))
        elif k == "split-edge":
            self._drag_split_edge(dx, dy)
        elif k == "split-move":
            self._drag_split_move(dx, dy)
        else:                                        # "draw" / "crop-edit" — live rubber-band
            bw, bh = self._view_dims if k == "crop-edit" else self._page_dims(self.current_page)
            sx, sy = self._drag["start"]
            self._draw_rect = clamp_box(Box(min(sx, px), min(sy, py),
                                            max(sx, px), max(sy, py)), bw, bh)
        self.render_page()
        self._update_status(event)

    def _write_auto_offsets(self, new: Box):
        """Write the four offsets so _crop_rect reproduces `new` exactly (drag/move)."""
        d = self._drag
        w, h, u = d["w"], d["h"], self._union
        self._suspend = True
        self.left_off.set(round((d["left_base"] - new.x0) / w * 100.0, 1))
        self.top_off.set(round((d["top_base"] - new.y0) / h * 100.0, 1))
        self.right_off.set(round((new.x1 - (d["left_base"] + u.width)) / w * 100.0, 1))
        self.bottom_off.set(round((new.y1 - (d["top_base"] + u.height)) / h * 100.0, 1))
        self._suspend = False

    def _drag_split_edge(self, dx, dy):
        d = self._drag
        w, h = self._page_dims(self.current_page)
        self.crop_rects[d["idx"]] = resize_by_handle(d["rect0"], d["handle"], dx, dy, w, h)

    def _drag_split_move(self, dx, dy):
        d = self._drag
        w, h = self._page_dims(self.current_page)
        self.crop_rects[d["idx"]] = move_box(d["rect0"], dx, dy, w, h)

    def _on_release(self, _e):
        d = self._drag
        if d and d["kind"].startswith("split"):
            i = d["idx"]
            if self.keep_ratio_var.get():
                ratio = self._active_ratio()         # the Keep-ratio field value (§9.7)
                if ratio:
                    box = self.crop_rects[i]
                    _, h = self._page_dims(self.current_page)
                    self.crop_rects[i] = Box(box.x0, box.y0, box.x1,
                                             box.y0 + min(box.width / ratio, h - box.y0))
            if self.same_size_var.get():
                self._apply_same_size(i)
            if self._prev_applied is not None:       # an edited committed split page stays committed
                self._applied[self.current_page] = list(self.crop_rects)
            self.render_page()
        elif d and d["kind"] == "draw":
            self._commit_drawn_rect()
        elif d and d["kind"] == "crop-edit":
            self._commit_crop_edit()
        elif d and d["kind"] in ("auto", "auto-move") and self._drag_moved \
                and self._prev_applied is not None:
            box = self._crop_rect(self.current_page)  # dragged a committed crop → keep it committed
            self._applied[self.current_page] = [box] if box is not None else self._prev_applied
            self.render_page()
        elif self._prev_applied is not None and not self._drag_moved:
            self._restore_prev_applied()             # a pure click must not drop the committed crop
        self._prev_applied = None
        self._drag = None
        self.canvas.configure(cursor="crosshair")

    def _restore_prev_applied(self):
        """Put back the crop stashed on press (the gesture committed nothing new)."""
        self._applied[self.current_page] = self._prev_applied
        self._prev_applied = None
        self.view_box = 0
        self.render_page()

    def _cancel_drag(self, _e=None):
        """Esc / right-click during a drag (§9.3, §9.6): discard the in-progress gesture, commit
        nothing, take no history snapshot, and leave the crop exactly as it was before the drag —
        the live split mutation and auto-crop offsets are rolled back, and a committed page's
        stashed crop is restored. No-op (lets Esc propagate) when nothing is in progress."""
        d = self._drag
        if d is None and self._draw_rect is None:
            return                                       # nothing to cancel — let Esc propagate
        self._draw_rect = None
        self._drag = None
        self.canvas.configure(cursor="crosshair")
        if d is not None and d.get("kind", "").startswith("split"):
            self.crop_rects[d["idx"]] = d["rect0"]       # roll back the live split mutation
        elif d is not None and "off0" in d:              # roll back the live auto-crop offsets
            self._suspend = True
            self.left_off.set(d["off0"][0]); self.top_off.set(d["off0"][1])
            self.right_off.set(d["off0"][2]); self.bottom_off.set(d["off0"][3])
            self._suspend = False
        if self._prev_applied is not None:               # restore a committed page's stashed crop
            self._applied[self.current_page] = self._prev_applied
            self._prev_applied = None
            self.view_box = 0
        self.render_page()
        return "break"

    def _commit_drawn_rect(self):
        """A hand-drawn rectangle is *this page's* crop only. Commit it straight to `applied`
        so it shows WYSIWYG and leaves the global detection (the live union shared by every
        other page) untouched — drawing on one page no longer resizes the crop preview of the
        other pages. Click the page again to redraw."""
        r = self._draw_rect
        self._draw_rect = None
        if r is None or r.width < 2 * MIN_RECT or r.height < 2 * MIN_RECT:
            if self._prev_applied is not None:       # aborted draw → keep the existing crop
                self._restore_prev_applied()
            else:
                self.render_page()
            return
        self._snapshot_history()
        self._applied[self.current_page] = [r]       # per-page committed crop (single)
        self.view_box = 0
        self.render_page()
        self.status_msg("Crop set for this page. Click the page to redraw.")

    def _commit_crop_edit(self):
        """Release of a crop-edit (§9.3, option a): map the rubber-band drawn on the cropped view
        back into the committed box → a **tightened** crop, re-committed so the page stays cropped.
        A stray click or a band smaller than 2·MIN_RECT leaves the committed crop unchanged (§9.5);
        the crop is never dropped — Undo reverts the tighten."""
        r = self._draw_rect
        self._draw_rect = None
        cur = self._applied.get(self.current_page)
        if not cur or r is None or r.width < 2 * MIN_RECT or r.height < 2 * MIN_RECT:
            self.render_page()                       # nothing valid → keep the committed crop
            return
        box = cur[0]
        ow, oh = self._view_dims
        sx, sy = box.width / max(ow, 1e-6), box.height / max(oh, 1e-6)   # display → page units
        new = Box(box.x0 + r.x0 * sx, box.y0 + r.y0 * sy,
                  box.x0 + r.x1 * sx, box.y0 + r.y1 * sy)
        if self.keep_ratio_var.get():
            ratio = self._active_ratio()
            if ratio:
                new = Box(new.x0, new.y0, new.x1, new.y0 + new.width / ratio)
        self._snapshot_history()
        self._applied[self.current_page] = [new]
        self.view_box = 0
        self.render_page()
        self.status_msg("Crop tightened. Esc / right-click to cancel; draw again to re-tighten.")

    def _apply_same_size(self, src: int):
        """Resize every split rectangle to match box `src`, anchored at its own corner."""
        if not self.crop_rects or src >= len(self.crop_rects):
            return
        tw, th = self.crop_rects[src].width, self.crop_rects[src].height
        w, h = self._page_dims(self.current_page)
        for j, box in enumerate(self.crop_rects):
            if j == src:
                continue
            x0 = min(box.x0, max(0.0, w - tw))
            y0 = min(box.y0, max(0.0, h - th))
            self.crop_rects[j] = Box(x0, y0, min(w, x0 + tw), min(h, y0 + th))

    def _on_motion(self, event):
        if self._drag is not None or self._busy or self.page_count() == 0:
            return
        cursor = "crosshair"
        for box in (b for b in self._preview_boxes() if b is not None):
            hit = self._hit_handle(box, event.x, event.y)
            if hit:
                cursor = HANDLE_CURSOR[hit]
                break
        self.canvas.configure(cursor=cursor)
        self._update_status(event)

    def _update_status(self, event):
        if self.page_count() == 0:
            return
        w, h = self._page_dims(self.current_page)
        px, py = self._canvas_to_pdf(event.x, event.y)
        parts = []
        if 0 <= px <= w and 0 <= py <= h:
            parts.append(f"x {px / w * 100:5.1f}%  y {py / h * 100:5.1f}%")
        boxes = [b for b in self._preview_boxes() if b is not None]
        if boxes:
            b = boxes[0]
            parts.append(f"⬓ {b.width / w * 100:.1f} × {b.height / h * 100:.1f} %")
        parts.append(f"page {self._view_position() + 1} / {self._view_total()}")
        self.status.configure(text="     ".join(parts))


    # ════════════════════════════════════════════════════════════════════
    #  NAV  (output pages: a committed split page expands into N navigable pages, #2 viz)
    # ════════════════════════════════════════════════════════════════════
    def _page_box_count(self, i: int) -> int:
        """How many output pages source page i yields (N for a committed split, else 1)."""
        return viewmodel.page_box_count(self._applied, i)

    def _view_total(self) -> int:
        return viewmodel.view_total(self._applied, self.page_count())

    def _view_position(self) -> int:
        """0-based flat index of the current (source page, split box) in the output sequence."""
        return viewmodel.view_position(self._applied, self.current_page, self.view_box)

    def _view_status(self) -> str:
        total = self._view_total()
        if self._page_box_count(self.current_page) > 1:       # show split index on a split page
            return (f"page {self._view_position() + 1} / {total}   "
                    f"(page {self.current_page + 1} split {self.view_box + 1}"
                    f"/{self._page_box_count(self.current_page)})")
        return f"page {self._view_position() + 1} / {total}"

    def _sync_follow(self):
        """When the 'Current' toggle is on, keep Pattern pointed at the current page."""
        if self.current_follow:
            self.select_var.set(str(self.current_page + 1))

    def prev_page(self):
        if not self.page_count():
            return
        if self.view_box > 0:                                 # step back through this page's splits
            self.view_box -= 1
        elif self.current_page > 0:
            self.current_page -= 1
            self.view_box = self._page_box_count(self.current_page) - 1
        else:
            return
        self._sync_follow()
        self.render_page()

    def next_page(self):
        if not self.page_count():
            return
        if self.view_box < self._page_box_count(self.current_page) - 1:   # next split of this page
            self.view_box += 1
        elif self.current_page < self.page_count() - 1:
            self.current_page += 1
            self.view_box = 0
        else:
            return
        self._sync_follow()
        self.render_page()

    def jump_to_page(self, _e=None):
        try:
            n = int(self.page_var.get())
        except ValueError:
            n = -1
        if 1 <= n <= self._view_total():                      # map flat output index → (page, box)
            self.current_page, self.view_box = viewmodel.flat_to_page_box(
                self._applied, self.page_count(), n - 1)
            self._sync_follow()
            self.render_page()
        else:
            self.page_var.set(str(self._view_position() + 1))


