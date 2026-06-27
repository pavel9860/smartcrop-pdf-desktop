"""SmartCrop PDF — desktop app to crop, straighten and clean PDFs and scans for e-readers
(see docs/SmartCrop_PDF_Specification.md).

GUI: CustomTkinter (rounded, themed, Windows-11/Fluent look) over a tk Canvas for the page
view; the pure logic (geometry, detection, deskew, filters, history) stays toolkit-agnostic.
Load/render/export run through PyMuPDF, with mode classification, text-block / ink-box
detection (cv2), deskew, bilevel/grayscale cleaning, drag geometry, undo/redo, theming and UI
scaling. Dewarp uses the docuwarp mesh model when it is installed and falls back to
deskew-only otherwise. With no file open, a synthetic placeholder document is shown.

The application is one `SmartCropApp` whose behaviour is composed from focused mixins
(see core/ui_build, document, detect, canvas, export); this module holds the orchestration:
construction, shared state, keyboard/scaling, undo/redo history and `main()`.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, messagebox
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
import fitz

from core.constants import (DPI_PRESETS, THEMES, WINDOW_SIZE, WINDOW_MIN, DEFAULT_FONT_SIZE,
                            SCALE_THROTTLE_MS, UI_SCALE_MIN, UI_SCALE_MAX, FONT_SIZE_MIN,
                            FONT_SIZE_MAX, CACHE_WINDOW)
from core.geometry import Box, union_box
from core.lru import LRUCache
from core.enums import Mode, FilterMode, PagesMode
from core.ui_build import UIBuildMixin
from core.document import DocumentMixin
from core.detect import DetectMixin
from core.canvas import CanvasMixin
from core.export import ExportMixin


# ════════════════════════════════════════════════════════════════════════════
#  APP  (orchestration; behaviour is composed from the mixins imported below)
# ════════════════════════════════════════════════════════════════════════════
class SmartCropApp(UIBuildMixin, DocumentMixin, DetectMixin, CanvasMixin, ExportMixin):
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        root.title("SmartCrop PDF")
        root.geometry(WINDOW_SIZE)
        root.minsize(*WINDOW_MIN)
        self.ui_scale = 1.0
        self._scale_target = 1.0
        self._scale_job = None
        self._render_job = None
        # Use the native system UI font so rendering matches the OS; all sizes derive from
        # self.fs and are live-reconfigurable (CTkFont is shared/mutable) — see _set_font_size.
        self.sys_font = tkfont.nametofont("TkDefaultFont").actual("family")
        self.sys_mono = tkfont.nametofont("TkFixedFont").actual("family")
        self.fs = DEFAULT_FONT_SIZE
        self.font_title = ctk.CTkFont(self.sys_font, self.fs + 1, "bold")
        self.font_base = ctk.CTkFont(self.sys_font, self.fs)
        self.font_offset = ctk.CTkFont(self.sys_font, self.fs)
        self.font_badge = ctk.CTkFont(self.sys_font, self.fs - 2, "bold")
        self.font_mono = ctk.CTkFont(self.sys_mono, self.fs - 2)
        self.font_help = ctk.CTkFont(self.sys_font, self.fs + 1)   # help body (+1pt vs base)
        self._init_state()
        self._build_ui()
        self._bind_shortcuts()
        self._load_synthetic()

    # ── state ────────────────────────────────────────────────────────────
    def _init_state(self) -> None:
        self.doc: Optional[fitz.Document] = None
        self._pdf_path: Optional[str] = None         # first input file (title / export-name stem)
        self._input_paths: List[str] = []            # all loaded files, for Reset re-combine (§13)
        self._pt_size: List[Tuple[float, float]] = []
        self.current_page = 0
        self.view_box = 0                  # which committed split box of current_page is shown (viz)
        self.scale = 1.0
        self.img_x = self.img_y = 0
        self.tk_image = None
        self._busy = False

        self.mode = Mode.NORMAL
        self.dewarp_on = False
        self.filter_mode = FilterMode.NONE
        self.filter_strength = 2
        self._processed: Dict[int, dict] = {}
        # source/work hold full-resolution rasters → LRU-bounded so RAM stays flat on big docs.
        self._source_cache = LRUCache(CACHE_WINDOW)
        self._work_cache = LRUCache(CACHE_WINDOW)
        self._detect_cache: Dict[int, Box] = {}      # tiny Box per page → kept fully
        self._union: Optional[Box] = None
        self.auto_active = False
        self._cancelled = False                      # set by the overlay Cancel button

        self.split_count = 1
        self.same_size_var = tk.BooleanVar(value=True)
        self.crop_rects: List[Box] = []
        self._drag: Optional[dict] = None
        self._draw_rect: Optional[Box] = None       # live rubber-band while drawing a new crop
        self._view_dims: Tuple[float, float] = (1.0, 1.0)   # dims of the image shown now (page or
        #                                                     committed-crop output) — for crop-edit
        self._off_spins = []                         # offset steppers (built into the Advanced card)
        self._prev_applied: Optional[List[Box]] = None   # committed crop stashed while editing it
        self._drag_moved = False                    # did the current gesture actually move?
        self._applied: Dict[int, List[Box]] = {}    # page → committed crop box(es) = saved state
        self._rotation: Dict[int, int] = {}         # page → rotation in degrees CW

        self.left_off = tk.DoubleVar(value=0.0)
        self.top_off = tk.DoubleVar(value=0.0)
        self.right_off = tk.DoubleVar(value=0.0)
        self.bottom_off = tk.DoubleVar(value=0.0)
        self._suspend = False
        self.auto_left_var = tk.BooleanVar(value=True)
        self.auto_top_var = tk.BooleanVar(value=True)
        self.keep_ratio_var = tk.BooleanVar(value=False)
        self.ratio_var = tk.StringVar(value="—")

        self.pages_mode = PagesMode.ALL
        self.current_follow = False         # 'Current' toggle: Pattern follows the current page
        self.select_var = tk.StringVar(value="")
        # Compress Document DPI + Output colours + Export format (§7.6, §12.7). These are LIVE
        # output settings, deliberately NOT part of the undo history (inv 22).
        self.compress_var = tk.StringVar(value=next(iter(DPI_PRESETS)))   # "Original resolution"
        self.colours_var = tk.StringVar(value="Original colors")
        self.format_var = tk.StringVar(value="PDF")
        self.output_folder_var = tk.StringVar(value="")     # "" → same folder as the source file
        self.output_postfix_var = tk.StringVar(value="_cropped")   # appended before the extension

        self.history: List[dict] = []
        self.redo_stack: List[dict] = []
        self.undo_depth_var = tk.StringVar(value="4")

        self.theme_choice = tk.StringVar(value="Dark")
        self.confirm_overwrite = tk.BooleanVar(value=True)
        self.remember_folder = tk.BooleanVar(value=True)
        self.dewarp_ss_var = tk.StringVar(value="2.0")
        self.font_size_var = tk.StringVar(value=str(self.fs))
        # Zoom is a user multiplier on top of CustomTkinter's automatic system-DPI scaling,
        # so 100 % already renders at the system's display size ("default zoom from system").
        self.zoom_var = tk.StringVar(value=f"{int(round(self.ui_scale * 100))}%")

    def _theme(self) -> Dict[str, str]:
        return THEMES["dark" if ctk.get_appearance_mode() == "Dark" else "light"]

    # ════════════════════════════════════════════════════════════════════
    #  SHORTCUTS / SCALING
    # ════════════════════════════════════════════════════════════════════
    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind("<Control-o>", lambda _e: self.load_files())
        r.bind("<Control-Return>", lambda _e: self.apply_crop())
        r.bind("<Control-s>", lambda _e: self.export())
        r.bind("<Control-z>", lambda _e: self.undo())
        r.bind("<Control-y>", lambda _e: self.redo())
        r.bind("<Left>", lambda _e: self.prev_page())
        r.bind("<Prior>", lambda _e: self.prev_page())
        r.bind("<Right>", lambda _e: self.next_page())
        r.bind("<Next>", lambda _e: self.next_page())
        for s in ("<Control-equal>", "<Control-plus>", "<Control-KP_Add>"):
            r.bind(s, lambda _e: self._rescale(0.1))
        for s in ("<Control-minus>", "<Control-KP_Subtract>"):
            r.bind(s, lambda _e: self._rescale(-0.1))
        r.bind("<Control-0>", lambda _e: self._rescale(0))

    def _rescale(self, delta: float) -> None:
        # Update the *target* and throttle: leading-edge apply for instant feedback,
        # then at most ~12 applies/sec while the key auto-repeats (CTk's set_widget_scaling
        # redraws every widget, so unthrottled key-repeat is what makes it crawl).
        self._scale_target = (1.0 if delta == 0 else
                              max(UI_SCALE_MIN, min(UI_SCALE_MAX,
                                                    round(self._scale_target + delta, 2))))
        if self._scale_job is None:
            self._apply_scale()
            self._scale_job = self.root.after(SCALE_THROTTLE_MS, self._scale_tick)

    def _scale_tick(self) -> None:
        self._scale_job = None
        if abs(self._scale_target - self.ui_scale) > 1e-3:      # value accrued while throttled
            self._apply_scale()
            self._scale_job = self.root.after(SCALE_THROTTLE_MS, self._scale_tick)

    def _apply_scale(self) -> None:
        self.ui_scale = self._scale_target
        ctk.set_widget_scaling(self.ui_scale)
        if hasattr(self, "zoom_var"):
            self.zoom_var.set(f"{int(round(self.ui_scale * 100))}%")
        self._schedule_render(60)                               # one re-render, not one per event

    def _set_zoom(self, value: str) -> None:
        try:
            pct = int(str(value).rstrip("%"))
        except ValueError:
            return
        self._scale_target = max(UI_SCALE_MIN, min(UI_SCALE_MAX, pct / 100.0))
        self._apply_scale()

    def _set_font_size(self, value: str) -> None:
        try:
            n = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, int(value)))
        except (ValueError, TypeError):
            return
        self.fs = n                                  # CTkFont is shared+mutable → updates live
        self.font_base.configure(size=n)
        self.font_offset.configure(size=n)
        self.font_title.configure(size=n + 1)
        self.font_badge.configure(size=max(8, n - 2))
        self.font_mono.configure(size=max(8, n - 2))
        self.font_help.configure(size=n + 1)
        self._schedule_render(60)

    def _schedule_render(self, delay: int = 50) -> None:
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(delay, self._render_now)

    def _render_now(self) -> None:
        self._render_job = None
        self.render_page()

    # ════════════════════════════════════════════════════════════════════
    #  HISTORY
    # ════════════════════════════════════════════════════════════════════
    def _capture(self):
        return dict(processed={k: dict(v) for k, v in self._processed.items()},
                    detect=dict(self._detect_cache), union=self._union, auto=self.auto_active,
                    rects=list(self.crop_rects), rotation=dict(self._rotation),
                    applied={k: list(v) for k, v in self._applied.items()},
                    off=(self.left_off.get(), self.top_off.get(), self.right_off.get(),
                         self.bottom_off.get()),
                    dewarp=self.dewarp_on, filter=self.filter_mode, strength=self.filter_strength)

    def _restore(self, st):
        self._processed = {k: dict(v) for k, v in st["processed"].items()}
        self._detect_cache = dict(st["detect"])
        self._union, self.auto_active = st["union"], st["auto"]
        self.crop_rects = list(st["rects"])
        self._rotation = dict(st["rotation"])
        self._applied = {k: list(v) for k, v in st["applied"].items()}
        self._suspend = True
        self.left_off.set(st["off"][0]); self.top_off.set(st["off"][1])
        self.right_off.set(st["off"][2]); self.bottom_off.set(st["off"][3])
        self._suspend = False
        self.dewarp_on, self.filter_mode, self.filter_strength = st["dewarp"], st["filter"], st["strength"]
        self._source_cache.clear()                   # rotation changed → re-render rasters
        self._work_cache.clear()
        self._refresh_scan_buttons()
        self._refresh_detect_enabled()
        self.strength_seg.set(str(self.filter_strength))
        self._sync_ratio_label()
        self.render_page()

    def _snapshot_history(self):
        self.history.append(self._capture())
        try:
            depth = max(1, int(self.undo_depth_var.get()))
        except ValueError:
            depth = 2
        while len(self.history) > depth:
            self.history.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.history:
            return
        self.redo_stack.append(self._capture())
        self._restore(self.history.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.history.append(self._capture())
        self._restore(self.redo_stack.pop())

    def reset_page(self):
        idx = self.current_page
        self._snapshot_history()
        for d in (self._source_cache, self._work_cache, self._detect_cache, self._processed,
                  self._applied, self._rotation):    # full per-page reset incl. scan processing
            d.pop(idx, None)
        self.render_page()
        self.status_msg(f"Reset page {idx + 1} to original.")

    def delete_pages(self):
        """Delete the Pages selection from the document."""
        if self._busy or self.page_count() == 0:
            return
        if self.doc is None:
            messagebox.showinfo("Delete", "Open a PDF first (the demo document can't be edited).")
            return
        idxs = sorted(set(self._resolve_pages()))
        if not idxs:
            messagebox.showwarning("Delete", "Empty Pages selection.")
            return
        if len(idxs) >= self.page_count():
            messagebox.showwarning("Delete", "Can't delete every page.")
            return
        if not messagebox.askyesno("Delete", f"Delete {len(idxs)} page(s) from the document?"):
            return
        self.doc.delete_pages(idxs)                   # fitz reindexes the remaining pages
        self._pt_size = [(self.doc[i].rect.width, self.doc[i].rect.height)
                         for i in range(self.doc.page_count)]
        deleted = set(idxs)

        def _reindex(d):
            """Drop deleted pages, shift surviving keys down — adjustments (crop, filter,
            dewarp, rotation, detection) on the kept pages are preserved, not wiped."""
            return {o - sum(1 for x in idxs if x < o): v
                    for o, v in d.items() if o not in deleted}
        self._source_cache.clear()                    # regenerable rasters → re-render at new idx
        self._work_cache.clear()
        self._detect_cache = _reindex(self._detect_cache)
        self._processed = _reindex(self._processed)
        self._applied = _reindex(self._applied)
        self._rotation = _reindex(self._rotation)
        if self.auto_active and self._detect_cache:   # rebuild the union over surviving boxes
            self._union = union_box(list(self._detect_cache.values()))
        else:
            self._union = None
            self.auto_active = False
        self.history.clear(); self.redo_stack.clear()
        self.current_page = min(self.current_page, self.page_count() - 1)
        self.view_box = 0
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg(f"Deleted {len(idxs)} page(s). {self.page_count()} remain.")

    # ════════════════════════════════════════════════════════════════════
    #  ERROR RECOVERY
    # ════════════════════════════════════════════════════════════════════
    def handle_callback_error(self, exc, val, tb) -> None:
        """Last-resort handler for an *unexpected* exception in a Tk callback (expected errors —
        malformed PDF, bad custom size — are caught specifically at their call sites). Rather
        than print-and-pretend-all-is-fine, this clears the transient flags that a half-finished
        operation could leave stuck (`_busy`, `_suspend`, the progress overlay, disabled
        controls) so the user can't pile new clicks onto a frozen/half-applied state, repaints a
        consistent view, and surfaces the error. Undo (snapshot-before-mutation) remains the way
        to revert a bad action."""
        import traceback
        traceback.print_exception(exc, val, tb)
        self._busy = False
        self._suspend = False
        for recover in (self._hide_progress, lambda: self._set_controls_enabled(True),
                        self.render_page):
            try:
                recover()
            except Exception:
                pass
        try:
            messagebox.showerror("SmartCrop PDF",
                                 f"{getattr(exc, '__name__', type(val).__name__)}: {val}\n\n"
                                 "The operation was stopped; the app has been returned to a "
                                 "usable state. Use Undo if the last change looks wrong.")
        except Exception:
            pass


def main() -> None:
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = SmartCropApp(root)
    root.report_callback_exception = app.handle_callback_error
    root.mainloop()
