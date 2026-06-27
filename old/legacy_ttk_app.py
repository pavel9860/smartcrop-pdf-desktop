"""
SmartCrop PDF — application window (v7).

Detection model (fixes the constant right-edge offset): auto-detect computes ONE
union box over all pages (min-left/top, max-right/bottom of text/ink). Crop edges
are then per-edge offsets in % of page dimension:
    left   = left_base  - L%·w      right  = auto_x1 + R%·w
    top    = top_base   - T%·h      bottom = auto_y1 + B%·h
left_base/top_base honour the Anchor toggles (detected edge vs page boundary).
Each offset controls exactly one edge, so dragging one border never moves the
opposite one — the jitter is structurally impossible and the right edge sits on
the detected right margin, not left+max_width.

Coordinate units: PDF points (normal mode) or raster pixels (scanned mode);
self.scale / img_x map page units → canvas, so geometry code is mode-agnostic.

Scanned processing applies to the current PAGES selection (threaded, with a
progress dialog). Clean offers two mutually-exclusive outputs — Bilevel (Sauvola
B/W) and Sharpen Gray (continuous-tone, sharpened). Nothing runs automatically.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import fitz
import numpy as np
from PIL import Image, ImageTk

from .constants import HELP_TEXT, RESOLUTIONS, THEMES
from . import imaging as IM
from .parsing import pages_for_mode
from .widgets import Segmented, Tooltip, ToggleSwitch, make_toggle_row

SRC_DPI = 200.0
HISTORY_DEPTH = 2


class PDFCropperApp:
    FONT_SCALE = 1.22
    HANDLE_R = 8

    def _f(self, size, weight="normal"):
        return ("Segoe UI", round(size * self.FONT_SCALE), weight)

    def _fm(self, size, weight="normal"):
        return ("Consolas", round(size * self.FONT_SCALE), weight)

    # ── init ───────────────────────────────────────────────────────────────────
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("SmartCrop PDF")
        root.geometry("1520x1000")
        root.minsize(980, 680)

        self.doc: Optional[fitz.Document] = None
        self.history: List[bytes] = []
        self.redo_history: List[bytes] = []
        self.current_page = 0
        self.scale = 1.0
        self.img_x = self.img_y = 0
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self._busy = False

        self.mode = "normal"
        self.mode_var = tk.StringVar(value="Normal")

        # scan intent
        self.unwarp_on = False
        self.clean_mode = "none"            # "none" | "bilevel" | "gray"
        self.clean_strength = 2
        self.preserve_pictures = False
        self._source_rasters: Dict[int, np.ndarray] = {}
        self._work_rasters: Dict[int, np.ndarray] = {}
        self._detect_cache: Dict[int, Tuple[int, int, int, int]] = {}

        self.split_count = 1

        # auto-detect: single union box (page units) + per-edge % offsets
        self.auto_active = False
        self.auto_x0 = self.auto_y0 = self.auto_x1 = self.auto_y1 = 0.0
        self._orig_ratio: Optional[float] = None

        self.crop_rects: List[fitz.Rect] = []
        self.active_draw_id: Optional[int] = None
        self.draw_start: Optional[Tuple[int, int]] = None
        self._drag_target: Optional[Tuple[int, str]] = None
        self._drag_last: Optional[Tuple[int, int]] = None
        self._suspend_offset_trace = False

        self.left_off = tk.DoubleVar(value=0.0)
        self.top_off = tk.DoubleVar(value=0.0)
        self.right_off = tk.DoubleVar(value=0.0)
        self.bottom_off = tk.DoubleVar(value=0.0)
        self.auto_left_var = tk.BooleanVar(value=True)
        self.auto_top_var = tk.BooleanVar(value=True)
        self.keep_ratio_var = tk.BooleanVar(value=False)
        self.preserve_var = tk.BooleanVar(value=False)

        self.pages_mode = "all"
        self.select_var = tk.StringVar(value="")
        self.resize_var = tk.StringVar(value="Original (No Resize)")

        self.theme_name = tk.StringVar(value="dark")
        self._t: Dict[str, str] = THEMES["dark"]

        self._build_ui()
        self._bind_traces()
        self._set_mode("normal", reset=True)

    # ════════════════════════════════════════════════════════════════════════
    #  STYLE
    # ════════════════════════════════════════════════════════════════════════
    def _build_style(self) -> None:
        t = self._t
        s = ttk.Style(self.root)
        s.theme_use("clam")
        self.root.configure(bg=t["BG"])
        fb = self._f(14)
        pad = (14, 7)
        s.configure(".", background=t["PANEL"], foreground=t["TEXT"], font=fb,
                    troughcolor=t["PANEL_2"], borderwidth=0)
        s.configure("TFrame", background=t["BG"])
        s.configure("Panel.TFrame", background=t["PANEL"])
        s.configure("TLabelframe", background=t["PANEL"], foreground=t["TEXT"],
                    bordercolor=t["BORDER"], relief="solid", padding=(8, 5))
        s.configure("TLabelframe.Label", background=t["PANEL"],
                    foreground=t["ACCENT_HOVER"], font=fb)
        s.configure("TButton", background=t["PANEL_3"], foreground=t["TEXT"], padding=pad,
                    bordercolor=t["BORDER"], focusthickness=2, focuscolor=t["ACCENT"],
                    font=fb, relief="flat")
        s.map("TButton", background=[("active", t["PANEL_2"]), ("pressed", t["PANEL"])],
              foreground=[("disabled", t["MUTED"])])
        s.configure("Selected.TButton", background=t["SELECT_BG"], foreground=t["SELECT_FG"],
                    font=fb, padding=pad, relief="flat")
        s.map("Selected.TButton",
              background=[("active", t["SELECT_BG"]), ("pressed", t["SELECT_BG"])])
        s.configure("Big.TButton", background=t["PANEL_3"], foreground=t["TEXT"],
                    padding=(10, 7), font=fb, relief="flat")
        s.map("Big.TButton", background=[("active", t["PANEL_2"]), ("pressed", t["PANEL"])],
              foreground=[("disabled", t["MUTED"])])
        s.configure("TEntry", fieldbackground=t["INPUT_BG"], foreground=t["INPUT_FG"],
                    insertcolor=t["INPUT_FG"], bordercolor=t["BORDER"], padding=(6, 5), font=fb)
        s.configure("TCombobox", fieldbackground=t["INPUT_BG"], background=t["INPUT_BG"],
                    foreground=t["INPUT_FG"], arrowsize=18, bordercolor=t["BORDER"],
                    padding=(6, 5), font=fb)
        s.map("TCombobox", fieldbackground=[("readonly", t["INPUT_BG"])],
              foreground=[("readonly", t["INPUT_FG"]), ("disabled", t["MUTED"])])
        s.configure("TSpinbox", fieldbackground=t["INPUT_BG"], foreground=t["INPUT_FG"],
                    bordercolor=t["BORDER"], padding=(4, 4), arrowsize=14, font=fb)
        s.map("TSpinbox", fieldbackground=[("readonly", t["INPUT_BG"])],
              foreground=[("disabled", t["MUTED"])])
        s.configure("TLabel", background=t["PANEL"], foreground=t["TEXT"], font=fb)
        s.configure("Muted.TLabel", background=t["PANEL"], foreground=t["MUTED"], font=self._f(11))
        s.configure("TSeparator", background=t["SEP"])
        s.configure("TScrollbar", troughcolor=t["PANEL_2"], background=t["PANEL_3"],
                    bordercolor=t["PANEL_3"], arrowcolor=t["MUTED"])

    def _apply_theme(self) -> None:
        self._t = THEMES[self.theme_name.get()]
        self._build_style()
        self._recolor(self.root)
        self.canvas.configure(bg=self._t["CANVAS_BG"], highlightbackground=self._t["BORDER"])
        self.status.configure(bg=self._t["CANVAS_BG"], fg=self._t["MUTED"])
        self._refresh_mode_badge()
        self._refresh_scan_highlights()
        if self.doc:
            self.render_page()

    def _recolor(self, w: tk.Widget) -> None:
        t = self._t
        cls = w.winfo_class()
        try:
            if cls in ("Frame", "Labelframe"):
                w.configure(bg=t["PANEL"])
            elif cls == "Toplevel":
                w.configure(bg=t["SETTINGS_BG"])
            elif cls == "Canvas":
                w.configure(bg=t["CANVAS_BG"] if w is self.canvas else t["PANEL"])
            elif cls == "Label":
                w.configure(bg=t["PANEL"], fg=t["TEXT"])
            elif cls == "Entry":
                w.configure(bg=t["INPUT_BG"], fg=t["INPUT_FG"], insertbackground=t["INPUT_FG"])
        except tk.TclError:
            pass
        for c in w.winfo_children():
            self._recolor(c)
        if isinstance(w, ToggleSwitch):
            w.refresh_colors()

    # ════════════════════════════════════════════════════════════════════════
    #  UI LAYOUT
    # ════════════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        self._build_style()
        self._pw = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=7, sashpad=0,
                                  sashrelief="flat", bg=self._t["SASH"], handlesize=0)
        self._pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left_host = tk.Frame(self._pw, bg=self._t["PANEL"], width=380)
        self._pw.add(left_host, minsize=300, stretch="never")
        self._ctrl_canvas = tk.Canvas(left_host, bg=self._t["PANEL"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(left_host, orient="vertical", command=self._ctrl_canvas.yview)
        self._ctrl_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._ctrl_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = ttk.Frame(self._ctrl_canvas, style="Panel.TFrame")
        self._win_id = self._ctrl_canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda _e: self._ctrl_canvas.configure(scrollregion=self._ctrl_canvas.bbox("all")))
        self._ctrl_canvas.bind("<Configure>",
                               lambda e: self._ctrl_canvas.itemconfig(self._win_id, width=e.width))
        for w in (self._ctrl_canvas, self.inner, left_host):
            w.bind("<MouseWheel>", lambda e: self._ctrl_canvas.yview_scroll(int(-e.delta / 120), "units"))

        self._build_doc_section()
        self._build_scan_section()
        self._build_split_section()
        self._build_detect_section()
        self._build_pages_section()
        self._build_resize_section()
        self._build_exec_section()
        self._build_nav_section()

        right_host = tk.Frame(self._pw, bg=self._t["CANVAS_BG"])
        self._pw.add(right_host, minsize=440, stretch="always")
        self.canvas = tk.Canvas(right_host, bg=self._t["CANVAS_BG"], highlightthickness=1,
                                highlightbackground=self._t["BORDER"], cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(right_host, text="", anchor="e", bg=self._t["CANVAS_BG"],
                               fg=self._t["MUTED"], font=self._fm(11))
        self.status.place(relx=1.0, rely=1.0, x=-10, y=-6, anchor="se")
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Configure>", lambda _e: self.render_page() if self.doc else None)

        self._toggle_custom_resize()
        self._sync_pages_buttons()

    def _tip(self, w, text):
        Tooltip(w, text, self)

    def _build_doc_section(self) -> None:
        sec = ttk.LabelFrame(self.inner, text=" Document & State ")
        sec.pack(fill=tk.X, padx=8, pady=(8, 4))
        top = ttk.Frame(sec, style="Panel.TFrame")
        top.pack(fill=tk.X, pady=(0, 6))
        bl = ttk.Button(top, text="📂  Load PDF", command=self.load_pdf)
        bl.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))
        self._tip(bl, "Open a PDF  (Ctrl+O). Auto-detects Normal vs Scanned.")
        self.mode_badge = tk.Label(top, textvariable=self.mode_var, width=10,
                                   font=self._f(12, "bold"), fg=self._t["TEXT"],
                                   bg=self._t["BADGE_NORMAL"], padx=8, pady=4, cursor="hand2")
        self.mode_badge.pack(side=tk.LEFT)
        self.mode_badge.bind("<Button-1>", lambda _e: self._toggle_mode())
        self._tip(self.mode_badge, "Detected mode. Click to override (Normal ⇄ Scanned).")
        ttk.Separator(sec, orient="horizontal").pack(fill=tk.X, pady=(0, 6))
        row = ttk.Frame(sec, style="Panel.TFrame")
        row.pack(fill=tk.X)
        bu = ttk.Button(row, text="↩  Undo", command=self.undo)
        bu.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self._tip(bu, f"Undo  (Ctrl+Z) — depth {HISTORY_DEPTH}")
        br = ttk.Button(row, text="Redo  ↪", command=self.redo)
        br.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 3))
        brs = ttk.Button(row, text="⟲  Reset", command=self.reset_page)
        brs.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 0))
        self._tip(brs, "Reload current page from cached original (clears clean/unwarp on it).")

    def _build_scan_section(self) -> None:
        self.scan_sec = ttk.LabelFrame(self.inner, text=" Scan Processing ")
        s = self.scan_sec
        self.btn_unwarp = ttk.Button(s, text="Unwarp + Deskew", command=self.run_unwarp)
        self.btn_unwarp.pack(fill=tk.X, pady=(0, 4))
        self._tip(self.btn_unwarp,
                  "Toggle learned mesh dewarp + deskew on the PAGES selection.\n"
                  "Always re-reads the original page (idempotent). Default OFF.\n"
                  "Needs docuwarp; without it a warning is shown.")
        ttk.Label(s, text="Clean output", style="Muted.TLabel").pack(anchor=tk.W)
        crow = ttk.Frame(s, style="Panel.TFrame")
        crow.pack(fill=tk.X, pady=(0, 4))
        crow.columnconfigure(0, weight=1)
        crow.columnconfigure(1, weight=1)
        self.btn_bilevel = ttk.Button(crow, text="Bilevel B/W", command=self.run_bilevel)
        self.btn_bilevel.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._tip(self.btn_bilevel, "Sauvola bilevel (pure black/white). Applies to PAGES selection.")
        self.btn_gray = ttk.Button(crow, text="Sharpen Gray", command=self.run_gray)
        self.btn_gray.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._tip(self.btn_gray, "Keep grayscale but flatten + sharpen. Applies to PAGES selection.")
        ttk.Label(s, text="Bilevel strength", style="Muted.TLabel").pack(anchor=tk.W)
        self.strength_seg = Segmented(
            s, self, [1, 2, 3], ["1 caut", "2 norm", "3 aggr"], self.set_clean_strength, initial=2,
            tooltip="Bilevel despeckle / binarization aggressiveness.")
        self.strength_seg.pack(fill=tk.X, pady=(0, 4))
        make_toggle_row(s, "Preserve pictures (bilevel)", self.preserve_var, self,
                        "Mask detected photo/figure regions out of the bilevel so they survive.")

    def _build_split_section(self) -> None:
        sec = ttk.LabelFrame(self.inner, text=" Split Into ")
        sec.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.split_seg = Segmented(sec, self, [1, 2, 4], ["1", "2", "4"], self.set_split, initial=1,
                                   tooltip="N areas → N output pages. 2/4 greys DETECT; draw\n"
                                           "boxes in reading order (numbered badges confirm).")
        self.split_seg.pack(fill=tk.X)
        self.split_status = ttk.Label(sec, text="", style="Muted.TLabel")
        self.split_status.pack(anchor=tk.W, pady=(2, 0))

    def _build_detect_section(self) -> None:
        self.detect_sec = ttk.LabelFrame(self.inner, text=" Detect ")
        self.detect_sec.pack(fill=tk.X, padx=8, pady=(0, 4))
        sec = self.detect_sec
        self.btn_detect = ttk.Button(sec, text="✦  Auto-detect", command=self.detect_content,
                                     style="Big.TButton")
        self.btn_detect.pack(fill=tk.X, pady=(0, 6))
        self._tip(self.btn_detect, "Union text/ink box across all pages. Safe to re-press.")
        self._sw_left = make_toggle_row(sec, "Anchor Left edge", self.auto_left_var, self,
                                        "ON: left edge = detected left margin. OFF: page boundary.")
        self._sw_top = make_toggle_row(sec, "Anchor Top edge", self.auto_top_var, self,
                                       "ON: top edge = detected top line. OFF: page boundary.")
        self._sw_ratio = make_toggle_row(sec, "Keep crop ratio", self.keep_ratio_var, self,
                                         "Adjusting Right also adjusts Bottom to hold aspect.")
        grid = ttk.Frame(sec, style="Panel.TFrame")
        grid.pack(fill=tk.X, pady=(4, 4))
        self._off_spins: List[ttk.Spinbox] = []
        for col, (lab, var) in enumerate([("L", self.left_off), ("T", self.top_off),
                                          ("R", self.right_off), ("B", self.bottom_off)]):
            ttk.Label(grid, text=lab).grid(row=0, column=col * 2, padx=(0 if col == 0 else 6, 2))
            sp = ttk.Spinbox(grid, from_=-100.0, to=100.0, increment=0.1, width=6,
                             format="%.1f", textvariable=var)
            sp.grid(row=0, column=col * 2 + 1)
            self._off_spins.append(sp)
        bc = ttk.Button(sec, text="✕  Clear", command=self.clear_rects)
        bc.pack(fill=tk.X)

    def _build_pages_section(self) -> None:
        sec = ttk.LabelFrame(self.inner, text=" Pages ")
        sec.pack(fill=tk.X, padx=8, pady=(0, 4))
        row = ttk.Frame(sec, style="Panel.TFrame")
        row.pack(fill=tk.X)
        self.pages_buttons: Dict[str, ttk.Button] = {}
        for mode, lab in [("all", "All"), ("odd", "Odd"), ("even", "Even"), ("select", "Select ▾")]:
            b = ttk.Button(row, text=lab, command=lambda m=mode: self.set_pages_mode(m))
            b.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
            self.pages_buttons[mode] = b
        self._tip(self.pages_buttons["odd"], "Odd page numbers (1,3,5 …) — 1-indexed.")
        self._tip(self.pages_buttons["even"], "Even page numbers (2,4,6 …) — 1-indexed.")
        self.select_entry = ttk.Entry(sec, textvariable=self.select_var, font=self._fm(13))
        self._tip(self.select_entry, "1-indexed pages: 1,3,5-9,12  (commas + inclusive ranges)")

    def _build_resize_section(self) -> None:
        sec = ttk.LabelFrame(self.inner, text=" Resize ")
        sec.pack(fill=tk.X, padx=8, pady=(0, 10))
        self.resize_combo = ttk.Combobox(sec, textvariable=self.resize_var, values=list(RESOLUTIONS),
                                          state="readonly", font=self._f(13))
        self.resize_combo.pack(fill=tk.X)
        self.resize_combo.bind("<<ComboboxSelected>>", self._toggle_custom_resize)
        self.resize_combo.option_add("*TCombobox*Listbox.font", self._f(13))
        self.custom_res = ttk.Frame(sec, style="Panel.TFrame")
        ttk.Label(self.custom_res, text="W").pack(side=tk.LEFT)
        self.custom_w = ttk.Entry(self.custom_res, width=8)
        self.custom_w.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.custom_res, text="H").pack(side=tk.LEFT)
        self.custom_h = ttk.Entry(self.custom_res, width=8)
        self.custom_h.pack(side=tk.LEFT, padx=(4, 0))

    def _build_exec_section(self) -> None:
        sec = ttk.Frame(self.inner, style="Panel.TFrame")
        sec.pack(fill=tk.X, padx=8, pady=(0, 4))
        prow = ttk.Frame(sec, style="Panel.TFrame")
        prow.pack(fill=tk.X, pady=(0, 4))
        prow.columnconfigure(0, weight=1)
        prow.columnconfigure(1, weight=1)
        self.btn_apply = ttk.Button(prow, text="✂  Apply Crop", command=self.apply_crop,
                                    style="Big.TButton")
        self.btn_apply.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._tip(self.btn_apply, "Apply crop to the PAGES selection  (Ctrl+Enter).")
        brot = ttk.Button(prow, text="↻  Rotate", command=self.rotate_pages, style="Big.TButton")
        brot.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._tip(brot, "Rotate selected pages 90° CW (pages, not crop).")
        bex = ttk.Button(sec, text="💾  Export PDF", command=self.save_pdf)
        bex.pack(fill=tk.X, pady=(0, 6))
        self._tip(bex, "Save processed document  (Ctrl+S).")
        ttk.Separator(sec, orient="horizontal").pack(fill=tk.X, pady=(0, 4))
        row2 = ttk.Frame(sec, style="Panel.TFrame")
        row2.pack(fill=tk.X)
        row2.columnconfigure(0, weight=1)
        row2.columnconfigure(1, weight=1)
        ttk.Button(row2, text="⚙  Settings", command=self.open_settings).grid(
            row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(row2, text="?  Help", command=self.open_help).grid(
            row=0, column=1, sticky="ew", padx=(3, 0))

    def _build_nav_section(self) -> None:
        nav = ttk.Frame(self.inner, style="Panel.TFrame")
        nav.pack(fill=tk.X, padx=8, pady=(2, 8))
        nav.columnconfigure(0, weight=1)
        nav.columnconfigure(3, weight=1)
        ttk.Button(nav, text="◀", command=self.prev_page, style="Big.TButton").grid(
            row=0, column=0, sticky="ew", padx=(0, 3))
        self.page_var = tk.StringVar(value="1")
        pe = ttk.Entry(nav, textvariable=self.page_var, width=5, justify="center",
                       font=self._f(14, "bold"))
        pe.grid(row=0, column=1, padx=2)
        pe.bind("<Return>", self.jump_to_page)
        self.page_total_label = ttk.Label(nav, text="/ 0")
        self.page_total_label.grid(row=0, column=2, padx=2)
        ttk.Button(nav, text="▶", command=self.next_page, style="Big.TButton").grid(
            row=0, column=3, sticky="ew", padx=(3, 0))

    # ════════════════════════════════════════════════════════════════════════
    #  TRACES / SHORTCUTS
    # ════════════════════════════════════════════════════════════════════════
    def _bind_traces(self) -> None:
        for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            var.trace_add("write", lambda *_: self._on_offset_change())
        self.auto_left_var.trace_add("write", lambda *_: self._on_anchor_change())
        self.auto_top_var.trace_add("write", lambda *_: self._on_anchor_change())
        self.keep_ratio_var.trace_add("write", lambda *_: self._on_offset_change())
        self.preserve_var.trace_add("write", lambda *_: self._on_preserve_change())
        self.root.bind("<Control-o>", lambda _e: self.load_pdf())
        self.root.bind("<Control-Return>", lambda _e: self.apply_crop())
        self.root.bind("<Control-s>", lambda _e: self.save_pdf())
        self.root.bind("<Control-z>", lambda _e: self.undo())
        self.root.bind("<Control-y>", lambda _e: self.redo())
        self.root.bind("<Left>", lambda _e: self.prev_page())
        self.root.bind("<Right>", lambda _e: self.next_page())
        self.root.bind("<Prior>", lambda _e: self.prev_page())
        self.root.bind("<Next>", lambda _e: self.next_page())

    def _on_anchor_change(self) -> None:
        if self.auto_active and self.doc:
            self.render_page()

    def _on_preserve_change(self) -> None:
        self.preserve_pictures = self.preserve_var.get()
        if self.mode == "scanned" and self.clean_mode == "bilevel":
            self._process_selected()

    def _toggle_custom_resize(self, _e=None) -> None:
        if self.resize_var.get() == "Custom…":
            self.custom_res.pack(fill=tk.X, pady=(8, 0))
        else:
            self.custom_res.pack_forget()

    def _sync_pages_buttons(self) -> None:
        for m, b in self.pages_buttons.items():
            b.configure(style="Selected.TButton" if m == self.pages_mode else "TButton")

    # ════════════════════════════════════════════════════════════════════════
    #  MODE
    # ════════════════════════════════════════════════════════════════════════
    def detect_mode(self) -> str:
        if self.doc is None or self.doc.page_count == 0:
            return "normal"
        scanned = 0
        n = self.doc.page_count
        for i in range(n):
            page = self.doc[i]
            txt = len(page.get_text("text").strip())
            area = page.rect.width * page.rect.height
            big = False
            for info in page.get_image_info():
                bb = info.get("bbox")
                if bb and area > 0:
                    r = fitz.Rect(bb)
                    if r.width * r.height >= 0.6 * area:
                        big = True
                        break
            if txt < 8 and big:
                scanned += 1
        return "scanned" if scanned * 2 > n else "normal"

    def _set_mode(self, mode: str, *, reset: bool = False) -> None:
        self.mode = mode
        self.mode_var.set("Scanned" if mode == "scanned" else "Normal")
        if mode == "scanned":
            self.scan_sec.pack(fill=tk.X, padx=8, pady=(0, 4),
                               after=self.inner.winfo_children()[0])
        else:
            self.scan_sec.pack_forget()
        self._refresh_mode_badge()
        if reset:
            self.clear_rects()
            self._work_rasters.clear()
            self._detect_cache.clear()
            self.unwarp_on = False
            self.clean_mode = "none"          # nothing runs automatically
        self._refresh_scan_highlights()

    def _toggle_mode(self) -> None:
        self._set_mode("normal" if self.mode == "scanned" else "scanned", reset=True)
        if self.doc:
            self.render_page()

    def _refresh_mode_badge(self) -> None:
        self.mode_badge.configure(
            bg=self._t["BADGE_SCAN"] if self.mode == "scanned" else self._t["BADGE_NORMAL"])

    def _refresh_scan_highlights(self) -> None:
        if not hasattr(self, "btn_unwarp"):
            return
        self.btn_unwarp.configure(style="Selected.TButton" if self.unwarp_on else "TButton")
        self.btn_bilevel.configure(
            style="Selected.TButton" if self.clean_mode == "bilevel" else "TButton")
        self.btn_gray.configure(
            style="Selected.TButton" if self.clean_mode == "gray" else "TButton")

    # ════════════════════════════════════════════════════════════════════════
    #  SCAN RASTERS / PROCESSING (applies to PAGES selection, threaded)
    # ════════════════════════════════════════════════════════════════════════
    def _source_raster(self, idx: int) -> np.ndarray:
        r = self._source_rasters.get(idx)
        if r is None:
            page = self.doc[idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(SRC_DPI / 72.0, SRC_DPI / 72.0), alpha=False)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            r = np.ascontiguousarray(img)
            self._source_rasters[idx] = r
        return r

    def _work_raster(self, idx: int) -> np.ndarray:
        return self._work_rasters.get(idx, self._source_raster(idx))

    def _intent_process(self, src_bgr: np.ndarray) -> np.ndarray:
        """Run the current scan intent on one raster. Worker-thread safe (cv2/np only)."""
        if self.unwarp_on and IM.unwarp_available():
            base = IM.unwarp_bgr(src_bgr)
        else:
            base, _ = IM.deskew_auto(src_bgr)
        if self.clean_mode == "bilevel":
            mask = IM.detect_picture_mask(base) if self.preserve_pictures else None
            return IM.clean_document_bilevel(base, strength=self.clean_strength, dpi=SRC_DPI,
                                             preserve_mask=mask)
        if self.clean_mode == "gray":
            return IM.sharpen_grayscale(base)
        return base

    def _process_selected(self) -> None:
        """(Re)compute work rasters for the PAGES selection under current intent."""
        if self.doc is None or self.mode != "scanned" or self._busy:
            return
        idxs = self._target_indices()
        if not idxs:
            messagebox.showwarning("Process", "Page selection is empty.")
            return
        if self.unwarp_on and not IM.unwarp_available():
            messagebox.showwarning("Unwarp", "docuwarp is not installed.\n\npip install docuwarp")
        for i in idxs:
            self._source_raster(i)                 # render on main thread

        def work(i):
            return self._intent_process(self._source_rasters[i])

        def done(results):
            self._work_rasters.update(results)
            for i in results:
                self._detect_cache.pop(i, None)
            self.render_page()

        self._threaded_map(idxs, work, done, "Processing pages")

    def run_unwarp(self) -> None:
        if self.doc is None or self.mode != "scanned":
            return
        self.unwarp_on = not self.unwarp_on
        self._refresh_scan_highlights()
        self._process_selected()

    def run_bilevel(self) -> None:
        if self.doc is None or self.mode != "scanned":
            return
        self.clean_mode = "none" if self.clean_mode == "bilevel" else "bilevel"
        self._refresh_scan_highlights()
        self._process_selected()

    def run_gray(self) -> None:
        if self.doc is None or self.mode != "scanned":
            return
        self.clean_mode = "none" if self.clean_mode == "gray" else "gray"
        self._refresh_scan_highlights()
        self._process_selected()

    def set_clean_strength(self, n: int) -> None:
        self.clean_strength = int(n)
        if self.mode == "scanned" and self.clean_mode == "bilevel":
            self._process_selected()

    def reset_page(self) -> None:
        idx = self.current_page
        self._work_rasters.pop(idx, None)
        self._detect_cache.pop(idx, None)
        self.render_page()

    def _scan_bilevel_for_detect(self, idx: int) -> np.ndarray:
        w = self._work_rasters.get(idx)
        if w is not None and w.ndim == 2 and self.clean_mode == "bilevel":
            return w
        base = w if (w is not None and w.ndim == 3) else self._source_raster(idx)
        return IM.clean_document_bilevel(base, strength=self.clean_strength, dpi=SRC_DPI)

    # ════════════════════════════════════════════════════════════════════════
    #  THREADED MAP (progress + cancel)
    # ════════════════════════════════════════════════════════════════════════
    def _threaded_map(self, indices: List[int], work_fn: Callable[[int], object],
                      on_done: Callable[[Dict[int, object]], None], title: str) -> None:
        self._busy = True
        self._set_controls_enabled(False)
        q: "queue.Queue" = queue.Queue()
        cancel = threading.Event()
        total = len(indices)
        prog = self._progress_dialog(total, cancel, title)

        def worker():
            results: Dict[int, object] = {}
            for n, i in enumerate(indices):
                if cancel.is_set():
                    q.put(("cancel", None))
                    return
                try:
                    results[i] = work_fn(i)
                except Exception as exc:                # surface, don't kill the GUI
                    q.put(("error", str(exc)))
                    return
                q.put(("progress", n + 1))
            q.put(("done", results))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "progress":
                        prog.update_value(payload)
                        self.status.configure(text=f"{title}… {payload}/{total}")
                    elif kind == "cancel":
                        prog.close()
                        self._finish_busy()
                        return
                    elif kind == "error":
                        prog.close()
                        self._finish_busy()
                        messagebox.showerror(title, payload)
                        return
                    elif kind == "done":
                        prog.close()
                        self._finish_busy()
                        on_done(payload)
                        self.status.configure(text="")
                        return
            except queue.Empty:
                self.root.after(40, poll)

        poll()

    def _finish_busy(self) -> None:
        self._busy = False
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for b in (getattr(self, "btn_apply", None), getattr(self, "btn_detect", None),
                  getattr(self, "btn_unwarp", None), getattr(self, "btn_bilevel", None),
                  getattr(self, "btn_gray", None)):
            if b is not None:
                try:
                    b.configure(state=state)
                except tk.TclError:
                    pass
        if enabled:
            self._refresh_detect_enabled()

    def _progress_dialog(self, total: int, cancel: threading.Event, title: str):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("360x120")
        win.transient(self.root)
        t = self._t
        win.configure(bg=t["PANEL"])
        tk.Label(win, text=f"{title}…", bg=t["PANEL"], fg=t["TEXT"], font=self._f(13)).pack(pady=(16, 8))
        pb = ttk.Progressbar(win, maximum=max(1, total), length=300, mode="determinate")
        pb.pack(pady=4)
        lbl = tk.Label(win, text=f"0 / {total}", bg=t["PANEL"], fg=t["MUTED"], font=self._fm(11))
        lbl.pack()
        ttk.Button(win, text="Cancel", command=cancel.set).pack(pady=6)

        class _P:
            def update_value(_s, v):
                pb["value"] = v
                lbl.configure(text=f"{v} / {total}")

            def close(_s):
                try:
                    win.destroy()
                except tk.TclError:
                    pass
        return _P()

    # ════════════════════════════════════════════════════════════════════════
    #  SPLIT / PAGES
    # ════════════════════════════════════════════════════════════════════════
    def set_split(self, n: int) -> None:
        self.split_count = int(n)
        if n > 1:
            self.auto_active = False
            self.crop_rects = []
        self._refresh_detect_enabled()
        self._refresh_apply_state()
        if self.doc:
            self.render_page()

    def _refresh_detect_enabled(self) -> None:
        enabled = self.split_count == 1 and not self._busy
        state = "normal" if enabled else "disabled"
        for w in (self.btn_detect, *self._off_spins):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        for sw in (self._sw_left, self._sw_top, self._sw_ratio):
            sw.set_enabled(enabled)

    def _refresh_apply_state(self) -> None:
        ok = True
        if self.split_count > 1:
            ok = len(self.crop_rects) == self.split_count
            self.split_status.configure(text=f"{len(self.crop_rects)} / {self.split_count} drawn")
        else:
            self.split_status.configure(text="")
        if not self._busy:
            self.btn_apply.configure(state="normal" if ok else "disabled")

    def set_pages_mode(self, mode: str) -> None:
        self.pages_mode = mode
        if mode == "select":
            self.select_entry.pack(fill=tk.X, pady=(4, 0))
        else:
            self.select_entry.pack_forget()
        self._sync_pages_buttons()

    def _target_indices(self) -> List[int]:
        if self.doc is None:
            return []
        try:
            return pages_for_mode(self.pages_mode, self.doc.page_count, self.current_page,
                                  self.select_var.get())
        except ValueError:
            return []

    # ════════════════════════════════════════════════════════════════════════
    #  DETECT  (single union box)  +  PER-EDGE AUTO RECT
    # ════════════════════════════════════════════════════════════════════════
    @staticmethod
    def _text_blocks(page: fitz.Page) -> list:
        return [b for b in page.get_text("blocks") if len(b) < 7 or b[6] == 0]

    def _page_dims(self, idx: int) -> Tuple[float, float]:
        if self.mode == "scanned":
            h, w = self._work_raster(idx).shape[:2]
            return float(w), float(h)
        page = self.doc[idx]
        return float(page.rect.width), float(page.rect.height)

    def detect_content(self) -> None:
        if self.doc is None or self.split_count > 1 or self._busy:
            return
        gx0 = gy0 = float("inf")
        gx1 = gy1 = float("-inf")
        n = self.doc.page_count
        for idx in range(n):
            if self.mode == "scanned":
                box = self._detect_cache.get(idx)
                if box is None:
                    box = IM.content_box(self._scan_bilevel_for_detect(idx))
                    if box is not None:
                        self._detect_cache[idx] = box
                if box is None:
                    continue
                bx0, by0, bx1, by1 = box
            else:
                blocks = self._text_blocks(self.doc[idx])
                if not blocks:
                    continue
                bx0 = min(b[0] for b in blocks)
                by0 = min(b[1] for b in blocks)
                bx1 = max(b[2] for b in blocks)
                by1 = max(b[3] for b in blocks)
            gx0, gy0 = min(gx0, bx0), min(gy0, by0)
            gx1, gy1 = max(gx1, bx1), max(gy1, by1)
        if gx0 == float("inf"):
            messagebox.showwarning("Auto-detect", "No text/ink detected.")
            return
        self.auto_x0, self.auto_y0, self.auto_x1, self.auto_y1 = gx0, gy0, gx1, gy1
        self._orig_ratio = ((gx1 - gx0) / (gy1 - gy0)) if (gy1 - gy0) > 0 else None
        self._suspend_offset_trace = True
        for v in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            v.set(0.0)
        self._suspend_offset_trace = False
        self.auto_active = True
        self.crop_rects = []
        self.current_page = min(self.current_page, n - 1)
        self.render_page()

    def _anchor_bases(self, idx: int) -> Tuple[float, float]:
        if self.mode == "scanned":
            pb_l = pb_t = 0.0
        else:
            r = self.doc[idx].rect
            pb_l, pb_t = r.x0, r.y0
        lb = self.auto_x0 if self.auto_left_var.get() else pb_l
        tb = self.auto_y0 if self.auto_top_var.get() else pb_t
        return lb, tb

    def _auto_rect_for_page(self, idx: int) -> Optional[fitz.Rect]:
        if not self.auto_active or self.doc is None:
            return None
        pw, ph = self._page_dims(idx)
        lb, tb = self._anchor_bases(idx)
        x0 = lb - self.left_off.get() / 100.0 * pw
        y0 = tb - self.top_off.get() / 100.0 * ph
        x1 = self.auto_x1 + self.right_off.get() / 100.0 * pw
        y1 = self.auto_y1 + self.bottom_off.get() / 100.0 * ph
        if x1 - x0 < 5:
            x1 = x0 + 5
        if y1 - y0 < 5:
            y1 = y0 + 5
        return fitz.Rect(x0, y0, x1, y1)

    def _preview_rects(self) -> List[Optional[fitz.Rect]]:
        if self.auto_active:
            r = self._auto_rect_for_page(self.current_page)
            return [r] if r is not None else []
        return list(self.crop_rects)

    def _on_offset_change(self) -> None:
        if self._suspend_offset_trace or not self.auto_active or self.doc is None:
            return
        if self.keep_ratio_var.get() and self._orig_ratio:
            pw, ph = self._page_dims(self.current_page)
            lb, tb = self._anchor_bases(self.current_page)
            x0 = lb - self.left_off.get() / 100.0 * pw
            x1 = self.auto_x1 + self.right_off.get() / 100.0 * pw
            y0 = tb - self.top_off.get() / 100.0 * ph
            width = max(5.0, x1 - x0)
            target_y1 = y0 + width / self._orig_ratio
            self._suspend_offset_trace = True
            self.bottom_off.set(round((target_y1 - self.auto_y1) / ph * 100.0, 1))
            self._suspend_offset_trace = False
        self.render_page()

    # ════════════════════════════════════════════════════════════════════════
    #  CANVAS COORDS / HANDLES
    # ════════════════════════════════════════════════════════════════════════
    def _pdf_to_canvas(self, px, py):
        return (px * self.scale + self.img_x, py * self.scale + self.img_y)

    def _canvas_to_pdf_rect(self, x0, y0, x1, y1) -> fitz.Rect:
        return fitz.Rect((min(x0, x1) - self.img_x) / self.scale,
                         (min(y0, y1) - self.img_y) / self.scale,
                         (max(x0, x1) - self.img_x) / self.scale,
                         (max(y0, y1) - self.img_y) / self.scale)

    def _handle_positions(self, rect: fitz.Rect) -> Dict[str, Tuple[float, float]]:
        x0, y0 = self._pdf_to_canvas(rect.x0, rect.y0)
        x1, y1 = self._pdf_to_canvas(rect.x1, rect.y1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return {"nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0), "w": (x0, my), "e": (x1, my),
                "sw": (x0, y1), "s": (mx, y1), "se": (x1, y1)}

    def _hit_handle(self, cx, cy) -> Optional[Tuple[int, str]]:
        hit_r = self.HANDLE_R + 5
        for i, rect in enumerate(self._preview_rects()):
            if rect is None:
                continue
            for hname, (hx, hy) in self._handle_positions(rect).items():
                if abs(cx - hx) <= hit_r and abs(cy - hy) <= hit_r:
                    return i, hname
        return None

    def _cursor_for_handle(self, h) -> str:
        return {"nw": "size_nw_se", "ne": "size_ne_sw", "se": "size_nw_se", "sw": "size_ne_sw",
                "n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we"}.get(h or "", "crosshair")

    @staticmethod
    def _apply_handle_drag(rect: fitz.Rect, handle: str, dpx: float, dpy: float) -> fitz.Rect:
        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
        if "w" in handle:
            x0 += dpx
        if "e" in handle:
            x1 += dpx
        if "n" in handle:
            y0 += dpy
        if "s" in handle:
            y1 += dpy
        if x1 - x0 < 5:
            if "w" in handle:
                x0 = x1 - 5
            else:
                x1 = x0 + 5
        if y1 - y0 < 5:
            if "n" in handle:
                y0 = y1 - 5
            else:
                y1 = y0 + 5
        return fitz.Rect(x0, y0, x1, y1)

    def _drag_to_offsets(self, new_rect: fitz.Rect) -> None:
        """Back out per-edge % offsets from the dragged rect. Each edge maps to one
        offset, so the non-dragged edges reproduce exactly (float, one render)."""
        idx = self.current_page
        pw, ph = self._page_dims(idx)
        lb, tb = self._anchor_bases(idx)
        self._suspend_offset_trace = True
        self.left_off.set(round((lb - new_rect.x0) / pw * 100.0, 1))
        self.top_off.set(round((tb - new_rect.y0) / ph * 100.0, 1))
        self.right_off.set(round((new_rect.x1 - self.auto_x1) / pw * 100.0, 1))
        self.bottom_off.set(round((new_rect.y1 - self.auto_y1) / ph * 100.0, 1))
        self._suspend_offset_trace = False
        self.render_page()

    # ════════════════════════════════════════════════════════════════════════
    #  RENDER
    # ════════════════════════════════════════════════════════════════════════
    def _display_image(self, idx: int) -> Image.Image:
        pw, ph = self._page_dims(idx)
        if self.mode == "scanned":
            img = self._work_raster(idx)
            dw, dh = max(1, int(pw * self.scale)), max(1, int(ph * self.scale))
            resized = cv2.resize(img, (dw, dh), interpolation=cv2.INTER_AREA)
            if resized.ndim == 2:
                return Image.fromarray(resized)
            return Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
        page = self.doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def render_page(self) -> None:
        if self.doc is None:
            self.canvas.delete("all")
            return
        self.canvas.update_idletasks()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 2 or ch <= 2:
            return
        pw, ph = self._page_dims(self.current_page)
        self.scale = min((cw - 36) / pw, (ch - 36) / ph)
        pil = self._display_image(self.current_page)
        self.tk_image = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.img_x = max(0, (cw - pil.width) // 2)
        self.img_y = max(0, (ch - pil.height) // 2)
        self.canvas.create_image(self.img_x, self.img_y, anchor=tk.NW, image=self.tk_image)

        colors = [self._t["CANVAS_ACCENT"], "#5dcff0", "#f0b35d", "#9b8cff"]
        for i, rect in enumerate(self._preview_rects()):
            if rect is None:
                continue
            color = colors[min(i, len(colors) - 1)]
            x0, y0 = self._pdf_to_canvas(rect.x0, rect.y0)
            x1, y1 = self._pdf_to_canvas(rect.x1, rect.y1)
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=3, dash=(6, 4))
            hc, hfil, R = self._t["HANDLE"], self._t["HANDLE_FILL"], self.HANDLE_R
            for _hn, (hx, hy) in self._handle_positions(rect).items():
                self.canvas.create_polygon(hx, hy - R, hx + R, hy, hx, hy + R, hx - R, hy,
                                           fill=hfil, outline=hc, width=2)
            if self.split_count > 1:
                self.canvas.create_oval(x0 + 4, y0 + 4, x0 + 30, y0 + 30,
                                        fill=color, outline=self._t["ACCENT_TEXT"])
                self.canvas.create_text(x0 + 17, y0 + 17, text=str(i + 1),
                                        fill=self._t["ACCENT_TEXT"], font=self._f(12, "bold"))
            elif self.auto_active:
                self.canvas.create_text(x0 + 14, y0 + 14, text="✦", fill=self._t["MAGIC"],
                                        font=("Segoe UI", 14, "bold"), anchor=tk.NW)

    # ════════════════════════════════════════════════════════════════════════
    #  MOUSE
    # ════════════════════════════════════════════════════════════════════════
    def _update_status(self, event) -> None:
        if self.doc is None or self._busy:
            return
        pw, ph = self._page_dims(self.current_page)
        px = (event.x - self.img_x) / self.scale
        py = (event.y - self.img_y) / self.scale
        tail = f"page {self.current_page + 1} / {self.doc.page_count}"
        if not (0 <= px <= pw and 0 <= py <= ph):
            self.status.configure(text=tail)
            return
        txt = f"x {px / pw * 100:5.1f}%  y {py / ph * 100:5.1f}%"
        if self._drag_target is not None or self.active_draw_id is not None:
            rects = self._preview_rects()
            if rects and rects[0] is not None:
                r = rects[0]
                txt += f"   ⬓ {r.width / pw * 100:.1f} × {r.height / ph * 100:.1f}%"
        self.status.configure(text=txt + "    " + tail)

    def _on_motion(self, event) -> None:
        if self.doc is None:
            return
        hit = self._hit_handle(event.x, event.y)
        self.canvas.configure(cursor=self._cursor_for_handle(hit[1] if hit else None))
        self._update_status(event)

    def _on_press(self, event) -> None:
        if self.doc is None or self._busy:
            return
        hit = self._hit_handle(event.x, event.y)
        if hit is not None:
            self._drag_target = hit
            self._drag_last = (event.x, event.y)
            return
        self._drag_target = None
        self._drag_last = None
        if self.split_count == 1:
            if self.auto_active:
                self.auto_active = False
                self.crop_rects = []
            if len(self.crop_rects) >= 1:
                self.crop_rects = []
        else:
            if len(self.crop_rects) >= self.split_count:
                self.crop_rects = []
        self.draw_start = (event.x, event.y)
        self.active_draw_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=self._t["CANVAS_ACCENT"], width=3, dash=(6, 4))

    def _on_drag(self, event) -> None:
        if self.doc is None:
            return
        if self._drag_target is not None and self._drag_last is not None:
            rect_idx, handle = self._drag_target
            rects = list(self._preview_rects())
            if rect_idx >= len(rects) or rects[rect_idx] is None:
                return
            lx, ly = self._drag_last
            dpx = (event.x - lx) / self.scale
            dpy = (event.y - ly) / self.scale
            new_rect = self._apply_handle_drag(rects[rect_idx], handle, dpx, dpy)
            if self.auto_active:
                self._drag_to_offsets(new_rect)
            else:
                self.crop_rects[rect_idx] = new_rect
                self.render_page()
            self._drag_last = (event.x, event.y)
            self._update_status(event)
            return
        if self.active_draw_id is None or self.draw_start is None:
            return
        self.canvas.coords(self.active_draw_id, self.draw_start[0], self.draw_start[1],
                           event.x, event.y)
        self._update_status(event)

    def _on_release(self, event) -> None:
        if self.doc is None:
            return
        if self._drag_target is not None:
            self._drag_target = None
            self._drag_last = None
            return
        if self.draw_start is None or self.active_draw_id is None:
            return
        rect = self._canvas_to_pdf_rect(self.draw_start[0], self.draw_start[1], event.x, event.y)
        self.canvas.delete(self.active_draw_id)
        self.active_draw_id = None
        self.draw_start = None
        if rect.width < 5 or rect.height < 5:
            self.render_page()
            self._refresh_apply_state()
            return
        self.crop_rects.append(rect)
        self._refresh_apply_state()
        self.render_page()

    # ════════════════════════════════════════════════════════════════════════
    #  CROP / APPLY
    # ════════════════════════════════════════════════════════════════════════
    def _selected_target_resolution(self) -> Optional[Tuple[int, int]]:
        import re
        val = self.resize_var.get().strip()
        if val == "Original (No Resize)":
            return None
        if val == "Custom…":
            w, h = int(self.custom_w.get()), int(self.custom_h.get())
            if w <= 0 or h <= 0:
                raise ValueError("Custom resolution must be positive integers.")
            return w, h
        m = re.search(r"\((\d+)[×x](\d+)\)", val)
        if not m:
            raise ValueError(f"Cannot parse resolution from: {val!r}")
        return int(m.group(1)), int(m.group(2))

    def _clips_for_page(self, idx: int) -> List[Optional[fitz.Rect]]:
        if self.split_count > 1:
            return list(self.crop_rects[:self.split_count])
        if self.auto_active:
            return [self._auto_rect_for_page(idx)]
        return list(self.crop_rects[:1])

    def apply_crop(self) -> None:
        if self.doc is None or self._busy:
            return
        if self.split_count > 1 and len(self.crop_rects) != self.split_count:
            messagebox.showwarning("Crop", f"Draw {self.split_count} areas first "
                                            f"({len(self.crop_rects)} drawn).")
            return
        if self.split_count == 1 and not self.auto_active and not self.crop_rects:
            messagebox.showwarning("Crop", "Auto-detect or draw a crop area first.")
            return
        try:
            targets = set(self._target_indices())
            target_res = self._selected_target_resolution()
        except ValueError as exc:
            messagebox.showerror("Crop", str(exc))
            return
        if not targets:
            messagebox.showwarning("Crop", "Page selection is empty.")
            return
        if self.mode == "scanned":
            self._apply_crop_scanned(targets, target_res)
        else:
            self._apply_crop_normal(targets, target_res)

    def _apply_crop_normal(self, targets, target_res) -> None:
        self._snapshot()
        new_doc = fitz.open()
        for pi in range(self.doc.page_count):
            if pi not in targets:
                new_doc.insert_pdf(self.doc, from_page=pi, to_page=pi)
                continue
            for clip in self._clips_for_page(pi):
                if clip is None:
                    continue
                clip = clip & self.doc[pi].rect
                if clip.is_empty:
                    continue
                if target_res is None:
                    p = new_doc.new_page(width=clip.width, height=clip.height)
                else:
                    p = new_doc.new_page(width=target_res[0], height=target_res[1])
                p.show_pdf_page(p.rect, self.doc, pi, clip=clip)
        self._swap_doc(new_doc)

    def _apply_crop_scanned(self, targets, target_res) -> None:
        order = sorted(targets)
        for pi in order:
            self._source_raster(pi)
        self._snapshot()

        def work(pi):
            proc = self._work_rasters.get(pi)
            if proc is None:
                proc = self._intent_process(self._source_rasters[pi])
            H, W = proc.shape[:2]
            crops = []
            for clip in self._clips_for_page(pi):
                if clip is None:
                    continue
                x0 = max(0, int(round(clip.x0)))
                y0 = max(0, int(round(clip.y0)))
                x1 = min(W, int(round(clip.x1)))
                y1 = min(H, int(round(clip.y1)))
                if x1 - x0 < 2 or y1 - y0 < 2:
                    continue
                crop = np.ascontiguousarray(proc[y0:y1, x0:x1])
                if target_res is not None:
                    crop = cv2.resize(crop, (target_res[0], target_res[1]),
                                      interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".png", crop)
                if ok:
                    crops.append((buf.tobytes(), crop.shape[1], crop.shape[0]))
            return crops

        def done(results):
            new_doc = fitz.open()
            oset = set(order)
            for pi in range(self.doc.page_count):
                if pi not in oset:
                    new_doc.insert_pdf(self.doc, from_page=pi, to_page=pi)
                    continue
                for png, w, h in results.get(pi, []):
                    page = new_doc.new_page(width=float(w), height=float(h))
                    page.insert_image(page.rect, stream=png)
            self._swap_doc(new_doc)

        self._threaded_map(order, work, done, "Cropping pages")

    def _swap_doc(self, new_doc: fitz.Document) -> None:
        self.doc.close()
        self.doc = new_doc
        self.current_page = 0
        self._invalidate_rasters()
        self.clear_rects()
        self.update_nav()
        self.render_page()

    def rotate_pages(self) -> None:
        if self.doc is None or self._busy:
            return
        target = set(self._target_indices())
        if not target:
            messagebox.showwarning("Rotate", "Page selection is empty.")
            return
        self._snapshot()
        for pi in target:
            page = self.doc[pi]
            page.set_rotation((page.rotation + 90) % 360)
        self._invalidate_rasters()
        self.render_page()

    # ════════════════════════════════════════════════════════════════════════
    #  HISTORY (bounded)
    # ════════════════════════════════════════════════════════════════════════
    def _snapshot(self) -> None:
        if self.doc is None:
            return
        self.history.append(self.doc.tobytes(deflate=True, clean=True))
        if len(self.history) > HISTORY_DEPTH:
            self.history.pop(0)
        self.redo_history.clear()

    def _restore(self, state: bytes) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open(stream=state, filetype="pdf")
        self._invalidate_rasters()

    def _invalidate_rasters(self) -> None:
        self._source_rasters.clear()
        self._work_rasters.clear()
        self._detect_cache.clear()

    def undo(self) -> None:
        if not self.history:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return
        if self.doc is not None:
            self.redo_history.append(self.doc.tobytes(deflate=True, clean=True))
            if len(self.redo_history) > HISTORY_DEPTH:
                self.redo_history.pop(0)
        self._restore(self.history.pop())
        self.current_page = min(self.current_page, self.doc.page_count - 1)
        self.clear_rects()
        self.update_nav()
        self.render_page()

    def redo(self) -> None:
        if not self.redo_history:
            messagebox.showinfo("Redo", "Nothing to redo.")
            return
        if self.doc is not None:
            self.history.append(self.doc.tobytes(deflate=True, clean=True))
            if len(self.history) > HISTORY_DEPTH:
                self.history.pop(0)
        self._restore(self.redo_history.pop())
        self.current_page = min(self.current_page, self.doc.page_count - 1)
        self.clear_rects()
        self.update_nav()
        self.render_page()

    def clear_rects(self) -> None:
        self.auto_active = False
        self.auto_x0 = self.auto_y0 = self.auto_x1 = self.auto_y1 = 0.0
        self._orig_ratio = None
        self.crop_rects = []
        self.active_draw_id = None
        self.draw_start = None
        self._drag_target = None
        self._drag_last = None
        self._suspend_offset_trace = True
        for v in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            v.set(0.0)
        self._suspend_offset_trace = False
        self._refresh_apply_state()
        self.render_page()

    # ════════════════════════════════════════════════════════════════════════
    #  NAV / IO
    # ════════════════════════════════════════════════════════════════════════
    def load_pdf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open(path)
        self.history.clear()
        self.redo_history.clear()
        self.current_page = 0
        self._invalidate_rasters()
        self.clear_rects()
        self._set_mode(self.detect_mode(), reset=True)
        self.update_nav()
        self.render_page()

    def update_nav(self) -> None:
        if self.doc is None:
            self.page_var.set("1")
            self.page_total_label.config(text="/ 0")
            return
        self.page_var.set(str(self.current_page + 1))
        self.page_total_label.config(text=f"/ {self.doc.page_count}")
        self._refresh_apply_state()

    def _goto(self, idx: int) -> None:
        self.current_page = idx
        self.update_nav()
        self.render_page()

    def prev_page(self) -> None:
        if self.doc and self.current_page > 0:
            self._goto(self.current_page - 1)

    def next_page(self) -> None:
        if self.doc and self.current_page < self.doc.page_count - 1:
            self._goto(self.current_page + 1)

    def jump_to_page(self, _e=None) -> None:
        if self.doc is None:
            return
        try:
            p = int(self.page_var.get()) - 1
        except ValueError:
            self.update_nav()
            return
        if 0 <= p < self.doc.page_count:
            self._goto(p)
        else:
            self.update_nav()

    def save_pdf(self) -> None:
        if self.doc is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        # NOTE: bilevel scan pages embed as PNG; CCITT-G4 / JBIG2 not yet wired.
        self.doc.save(path, garbage=4, deflate=True, clean=True)
        messagebox.showinfo("Exported", f"Saved to:\n{path}")

    # ════════════════════════════════════════════════════════════════════════
    #  SETTINGS / HELP
    # ════════════════════════════════════════════════════════════════════════
    def open_help(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Help — SmartCrop PDF")
        win.geometry("760x880")
        t = self._t
        win.configure(bg=t["SETTINGS_BG"])
        hdr = tk.Frame(win, bg=t["ACCENT"])
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="?  Help & Quick-Start", bg=t["ACCENT"], fg=t["ACCENT_TEXT"],
                 font=self._f(14, "bold")).pack(side=tk.LEFT, padx=18, pady=8)
        body = tk.Frame(win, bg=t["SETTINGS_BG"])
        body.pack(fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(body, orient="vertical")
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(body, wrap="word", font=self._fm(12), bg=t["PANEL"], fg=t["TEXT"],
                      borderwidth=0, padx=22, pady=16, yscrollcommand=sb.set)
        txt.pack(fill=tk.BOTH, expand=True)
        sb.configure(command=txt.yview)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")

    def open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Settings — SmartCrop PDF")
        win.geometry("560x320")
        t = self._t
        win.configure(bg=t["SETTINGS_BG"])
        hdr = tk.Frame(win, bg=t["ACCENT"], height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙  Settings", bg=t["ACCENT"], fg=t["ACCENT_TEXT"],
                 font=self._f(14, "bold")).pack(side=tk.LEFT, padx=18)
        body = tk.Frame(win, bg=t["SETTINGS_BG"])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        r = tk.Frame(body, bg=t["PANEL"])
        r.pack(fill=tk.X, pady=6)
        tk.Label(r, text="Colour scheme", width=18, anchor="w", bg=t["PANEL"], fg=t["TEXT"],
                 font=self._f(13)).pack(side=tk.LEFT, padx=8)
        cb = ttk.Combobox(r, textvariable=self.theme_name, values=["dark", "light"],
                          state="readonly", font=self._f(13))
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_theme())
        r2 = tk.Frame(body, bg=t["PANEL"])
        r2.pack(fill=tk.X, pady=6)
        tk.Label(r2, text="Default resolution", width=18, anchor="w", bg=t["PANEL"], fg=t["TEXT"],
                 font=self._f(13)).pack(side=tk.LEFT, padx=8)
        cb2 = ttk.Combobox(r2, textvariable=self.resize_var, values=list(RESOLUTIONS),
                           state="readonly", font=self._f(13))
        cb2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        cb2.bind("<<ComboboxSelected>>", self._toggle_custom_resize)
