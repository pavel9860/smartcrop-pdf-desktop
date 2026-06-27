"""Detection, crop geometry and split for SmartCropApp: per-page content boxes, the union
crop frame, anchors/offsets/keep-ratio, offset clamping and 1/2/4-up split layout.
Mixed into SmartCropApp; see core/app.py.
"""
from __future__ import annotations

from tkinter import TclError, messagebox
from typing import Dict, List, Optional

import cv2
import numpy as np

import core.imaging
from core.constants import DETECT_MAX_PX, FULL_PAGE_FRAC, OFFSET_LIMIT
from core.enums import Mode
from core.geometry import Box, anchored_base, auto_crop_rect, clamp_box, union_box


class DetectMixin:
    """Auto-detect, crop-rectangle math, offsets and split layout."""
    # ════════════════════════════════════════════════════════════════════
    #  DETECT / GEOMETRY
    # ════════════════════════════════════════════════════════════════════
    def _resolve_pages(self) -> List[int]:
        try:
            from core.parsing import pages_for_mode
            return pages_for_mode(self.pages_mode, self.page_count(), self.current_page,
                                  self.select_var.get())
        except ValueError:
            return []

    def _content_box_page(self, idx: int) -> Box:
        w, h = self._page_dims(idx)
        if self.mode == Mode.NORMAL:
            if self.doc is not None:
                blocks = [b for b in self.doc[idx].get_text("blocks") if b[6] == 0 and b[4].strip()]
                if blocks:
                    return Box(min(b[0] for b in blocks), min(b[1] for b in blocks),
                               max(b[2] for b in blocks), max(b[3] for b in blocks))
                return Box(0, 0, w, h)
            return self._synthetic_text_box(idx, w, h)
        img = self._work_image(idx) if self.mode == Mode.SCANNED else self._source_image(idx)
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        g0h, g0w = bgr.shape[:2]
        s = min(1.0, DETECT_MAX_PX / max(g0h, g0w))      # downscale for speed
        if s < 1.0:
            bgr = cv2.resize(bgr, (max(1, round(g0w * s)), max(1, round(g0h * s))),
                             interpolation=cv2.INTER_AREA)
        gh, gw = bgr.shape[:2]
        # Real Sauvola clean (flattens photo background) → far better ink mask on real scans
        # than a global Otsu, which marks a photographed page's tinted paper as ink.
        bw = core.imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
        t = core.imaging.content_box(bw)              # (x0,y0,x1,y1) in (downscaled) raster px
        if t is None:
            return Box(0, 0, w, h)
        sx, sy = w / gw, h / gh                  # map back to page units
        return Box(t[0] * sx, t[1] * sy, t[2] * sx, t[3] * sy)

    def detect_content(self) -> None:
        if self._busy or self.split_count > 1:
            return
        if not (self.auto_left_var.get() or self.auto_top_var.get()):
            messagebox.showinfo("Auto-detect", "Turn on Anchor Left and/or Anchor Top first.")
            return
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Auto-detect", "Empty Pages selection.")
            return
        if self.mode == Mode.SCANNED:                # raster detection is heavy → show progress
            results: Dict[int, Box] = {}             # Boxes are tiny, so accumulating is cheap
            self._run_batch(indices, self._content_box_page,
                            lambda i, b: results.__setitem__(i, b),
                            lambda ok: self._finish_detect(results) if ok else None,
                            "Detecting")
        else:
            self._finish_detect({i: self._content_box_page(i) for i in indices})

    def _finish_detect(self, results: Dict[int, Box]) -> None:
        if not results:
            messagebox.showwarning("Auto-detect", "No text or ink found.")
            return
        # A page in this selection that already carries a committed crop is *re-committed* to the
        # fresh auto crop below — so re-detecting takes visible effect (bug: auto-detect did
        # nothing after a crop) WITHOUT ever dropping the crop: the page stays cropped, only the
        # box updates, and it is undoable. Pages outside this selection keep their crops untouched.
        recommit = [i for i in results if i in self._applied]
        if recommit:
            self._snapshot_history()
        self._detect_cache.update(results)
        # Exclude pages where detection fell back to the full page — one such outlier would
        # blow W/H up to the sheet size and push right/bottom to the page edge.
        good = []
        for i, b in results.items():
            w, h = self._page_dims(i)
            if b.width < FULL_PAGE_FRAC * w or b.height < FULL_PAGE_FRAC * h:
                good.append(b)
        boxes = good or list(results.values())
        self._union = union_box(boxes)               # constant W=max width, H=max height
        self.auto_active = True
        for i in recommit:                           # refresh — never drop — the committed crop
            rect = self._crop_rect(i)
            if rect is not None:
                self._applied[i] = [rect]
        self._sync_ratio_label()
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg(f"Detected {self._union.width:.0f}×{self._union.height:.0f} px "
                        f"crop over {len(boxes)} page(s).")

    def _sync_ratio_label(self) -> None:
        if self._union and self._union.height and not self.keep_ratio_var.get():
            self.ratio_var.set(f"{self._union.width / self._union.height:.3f}")
        elif not self._union:
            self.ratio_var.set("—")

    def _active_ratio(self) -> Optional[float]:
        try:
            r = float(self.ratio_var.get())
            return r if r > 0 else None
        except ValueError:
            return self._union.width / self._union.height if self._union and self._union.height else None

    def _crop_rect(self, idx: int) -> Optional[Box]:
        # Inactive for split, when undetected, or when both anchors are OFF (spec §7.4).
        if self.split_count > 1 or not self.auto_active or self._union is None:
            return None
        if not (self.auto_left_var.get() or self.auto_top_var.get()):
            return None
        w, h = self._page_dims(idx)
        b = self._detect_cache.get(idx) or Box(0, 0, w, h)
        rect = auto_crop_rect(b, self._union, self.auto_left_var.get(), self.auto_top_var.get(),
                              self.left_off.get(), self.top_off.get(),
                              self.right_off.get(), self.bottom_off.get(), w, h)
        if self.keep_ratio_var.get():                # lock height = width / ratio
            ratio = self._active_ratio()
            if ratio:
                rect = clamp_box(Box(rect.x0, rect.y0, rect.x1, rect.y0 + rect.width / ratio), w, h)
        return rect

    def _on_offset_change(self):
        if not self._suspend:
            self.render_page()

    def _on_right_change(self):
        self.render_page()                           # ratio (if on) is enforced in _crop_rect

    def _clamp_offsets(self, _e=None):
        """On commit (Return / focus-out), snap each offset to the largest value the page
        actually allows, so the crop edge lands on the page border / opposite side instead
        of accepting absurd numbers like 100000. Done by round-tripping the crop
        through clamp_box and reading each edge back out as its offset."""
        if not (self.auto_active and self._union):   # no live crop → just bound to ±100
            self._suspend = True
            for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
                try:
                    v = float(var.get())
                except (TclError, ValueError):
                    v = 0.0
                var.set(round(max(-OFFSET_LIMIT, min(OFFSET_LIMIT, v)), 1))
            self._suspend = False
            self.render_page()
            return
        idx = self.current_page
        rect = self._crop_rect(idx)                  # already clamped to the page (and ratio)
        if rect is None:
            return
        w, h = self._page_dims(idx)
        b = self._detect_cache.get(idx) or Box(0, 0, w, h)
        u = self._union
        ab = anchored_base(b, u, self.auto_left_var.get(), self.auto_top_var.get(), w, h)
        lb, tb = ab.x0, ab.y0
        self._suspend = True
        self.left_off.set(round((lb - rect.x0) / w * 100.0, 1))
        self.top_off.set(round((tb - rect.y0) / h * 100.0, 1))
        self.right_off.set(round((rect.x1 - (lb + u.width)) / w * 100.0, 1))
        if not self.keep_ratio_var.get():            # B is inert (derived) when ratio is locked
            self.bottom_off.set(round((rect.y1 - (tb + u.height)) / h * 100.0, 1))
        else:
            try:
                bv = float(self.bottom_off.get())
            except (TclError, ValueError):
                bv = 0.0
            self.bottom_off.set(round(max(-OFFSET_LIMIT, min(OFFSET_LIMIT, bv)), 1))
        self._suspend = False
        self.render_page()

    def _on_anchor(self):
        self._refresh_detect_enabled()               # both anchors OFF ⇒ detect inactive
        self.render_page()

    def _on_ratio_toggle(self):
        self._sync_ratio_label()
        self.render_page()


    # ════════════════════════════════════════════════════════════════════
    #  SPLIT
    # ════════════════════════════════════════════════════════════════════
    def set_split(self, n: int):
        if n != self.split_count:
            self._applied.clear()        # committed crops belong to the previous split mode
        self.split_count = n
        if n == 1:
            self.crop_rects.clear()
        else:
            self._auto_layout_split(n)
        self._sync_split_ui()
        self._set_detect_enabled(n == 1)
        self.render_page()

    def _auto_layout_split(self, n: int):
        w, h = self._page_dims(self.current_page)
        if n == 2:
            self.crop_rects = [Box(0, 0, w / 2, h), Box(w / 2, 0, w, h)]
        else:
            self.crop_rects = [Box(0, 0, w / 2, h / 2), Box(w / 2, 0, w, h / 2),
                               Box(0, h / 2, w / 2, h), Box(w / 2, h / 2, w, h)]

    def _on_same_size(self, _v=None):
        if self.same_size_var.get() and self.split_count > 1:
            self._auto_layout_split(self.split_count)
            self.render_page()

    def _sync_split_ui(self):
        if self.split_count in (2, 4):
            self.same_size_row.pack(fill="x", pady=(8, 0))
        else:
            self.same_size_row.pack_forget()
        if hasattr(self, "btn_apply"):
            ok = self.split_count == 1 or len(self.crop_rects) == self.split_count
            self.btn_apply.configure(state="normal" if ok and not self._busy else "disabled")

    def _set_detect_enabled(self, enabled: bool):
        """Anchors/ratio/offsets follow split (enabled only at split=1)."""
        state = "normal" if enabled else "disabled"
        for sw in (self.sw_left, self.sw_top, self.sw_ratio):
            sw.configure(state=state)
        self.ratio_entry.configure(state=state)
        for sp in self._off_spins:
            sp.configure_state(state)
        self._refresh_detect_enabled()

    def _refresh_detect_enabled(self):
        """Auto-detect is available at split=1 with at least one anchor ON (spec §7.4).
        It is an *action*, never a stuck toggle: it stays neutral (never highlighted) and
        re-pressable at any time so re-running after editing the crop always works."""
        one_anchor = self.auto_left_var.get() or self.auto_top_var.get()
        ok = self.split_count == 1 and one_anchor and not self._busy
        if hasattr(self, "btn_detect"):
            self.btn_detect.configure(state="normal" if ok else "disabled")
            self._set_active(self.btn_detect, False)

