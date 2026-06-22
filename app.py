"""SmartCrop PDF — modern UI prototype for spec V9 (docs/SmartCrop_PDF_Specification_V9.md).
Toolkit: CustomTkinter (rounded, themed, Fluent-style 2026 look) over a tk Canvas for
the page view. Pure logic (geometry, detection, deskew, filters, history) is toolkit-
agnostic. Real: load/render/export via PyMuPDF, mode classification, text-block /
ink-box detect (cv2), deskew, bilevel/sharpen, drag geometry, history, theme, UI
scaling, settings, help. Simplified: synthetic placeholder doc when nothing loaded;
deskew-only (no mesh dewarp model); export rasterizes.
"""
from __future__ import annotations

import io
import os
import queue
import random
import re
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageTk

import imaging
from constants import RESOLUTIONS, THEMES
from geometry import (Box, MIN_RECT, HANDLE_CURSOR, auto_crop_rect, clamp_box,
                      hit_handle, move_box, point_in_box, resize_by_handle,
                      rotate_box_cw, union_box)

SRC_DPI = 200.0
NORMAL_DPI = 150.0
HANDLE_R = 8
HANDLE_SLACK = 6
CANVAS_MARGIN = 40
PROGRESS_POLL_MS = 40
MODE_TEXT_MIN = 8
MODE_IMG_COVER = 0.60
DESKEW_MAX_DEG = 15.0
BORDER_FRAC = 0.02
MIN_COMP_FRAC = 2.5e-4
DETECT_MAX_PX = 1400          # cap raster size for content detection (speed, #12)
SYNTH_PAGES = 24

# Palette + help text (sibling modules).
from theme import (ACCENT, ACCENT_HOVER, ACCENT_TEXT, CARD, CARD_BORDER,
                   CROP_BLUE, MUTED, SECONDARY, SECONDARY_HOVER, SECONDARY_TEXT,
                   SEG_UNSEL, SPLIT_BLUE, STATUS_FG)
from help_content import HELP_SECTIONS, OFFSET_TIP, SPLIT_TIP


# Geometry → geometry.py · raster processing → imaging.py
_CLEAN_AMOUNT = {1: 0.6, 2: 1.1, 3: 1.6}      # grayscale-filter unsharp amount per strength


def _pil_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()




# ════════════════════════════════════════════════════════════════════════════
#  TOOLTIP
from widgets import ToolTip, Spin


# ════════════════════════════════════════════════════════════════════════════
#  APP
# ════════════════════════════════════════════════════════════════════════════
class TestUIApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        root.title("SmartCrop PDF")
        root.geometry("1560x1000")
        root.minsize(1040, 700)
        self.ui_scale = 1.0
        self._scale_target = 1.0
        self._scale_job = None
        self._render_job = None
        # Use the native system UI font so rendering matches the OS; all sizes derive from
        # self.fs and are live-reconfigurable (CTkFont is shared/mutable) — see _set_font_size.
        self.sys_font = tkfont.nametofont("TkDefaultFont").actual("family")
        self.sys_mono = tkfont.nametofont("TkFixedFont").actual("family")
        self.fs = 15
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
        self._pdf_path: Optional[str] = None
        self._pt_size: List[Tuple[float, float]] = []
        self.current_page = 0
        self.scale = 1.0
        self.img_x = self.img_y = 0
        self.tk_image = None
        self._busy = False

        self.mode = "normal"
        self.dewarp_on = False
        self.clean_mode = "none"            # none | bw | gray
        self.clean_strength = 2
        self._processed: Dict[int, dict] = {}
        self._source_cache: Dict[int, Image.Image] = {}
        self._work_cache: Dict[int, Image.Image] = {}
        self._detect_cache: Dict[int, Box] = {}
        self._union: Optional[Box] = None
        self.auto_active = False

        self.split_count = 1
        self.same_size_var = tk.BooleanVar(value=True)
        self.crop_rects: List[Box] = []
        self._rect_ratio: List[Optional[float]] = []
        self._drag: Optional[dict] = None
        self._draw_rect: Optional[Box] = None       # live rubber-band while drawing a new crop
        self._out_pages: List[Image.Image] = []
        self._applied: Dict[int, List[Box]] = {}    # page → committed crop box(es) = saved state
        self._rotation: Dict[int, int] = {}         # page → rotation in degrees CW (#8, #13)

        self.left_off = tk.DoubleVar(value=0.0)
        self.top_off = tk.DoubleVar(value=0.0)
        self.right_off = tk.DoubleVar(value=0.0)
        self.bottom_off = tk.DoubleVar(value=0.0)
        self._suspend = False
        self.auto_left_var = tk.BooleanVar(value=True)
        self.auto_top_var = tk.BooleanVar(value=True)
        self.keep_ratio_var = tk.BooleanVar(value=False)
        self.ratio_var = tk.StringVar(value="—")

        self.pages_mode = "all"
        self.select_var = tk.StringVar(value="")
        self.resize_var = tk.StringVar(value=RESOLUTIONS[0])

        self.history: List[dict] = []
        self.redo_stack: List[dict] = []
        self.undo_depth_var = tk.StringVar(value="4")

        self.theme_choice = tk.StringVar(value="Dark")
        self.confirm_overwrite = tk.BooleanVar(value=True)
        self.remember_folder = tk.BooleanVar(value=True)
        self.dewarp_ss_var = tk.StringVar(value="2.0")
        self.workers_var = tk.StringVar(value="4")
        self.font_size_var = tk.StringVar(value=str(self.fs))
        # Zoom is a user multiplier on top of CustomTkinter's automatic system-DPI scaling,
        # so 100 % already renders at the system's display size ("default zoom from system").
        self.zoom_var = tk.StringVar(value=f"{int(round(self.ui_scale * 100))}%")

    def _theme(self) -> Dict[str, str]:
        return THEMES["dark" if ctk.get_appearance_mode() == "Dark" else "light"]

    # ════════════════════════════════════════════════════════════════════
    #  LAYOUT
    # ════════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        t = self._theme()
        self.paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=8, bd=0,
                                    bg=t["SASH"], sashrelief="flat")
        self.paned.pack(fill="both", expand=True, padx=10, pady=10)

        left = ctk.CTkFrame(self.paned, fg_color="transparent", width=440)
        left.pack_propagate(False)                    # hold the panel width (no bottom-bar anchor now)
        self.paned.add(left, minsize=380, stretch="never", width=440)
        self.controls = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.controls.pack(side="top", fill="both", expand=True)

        self._build_doc_section()
        self._build_scan_section()
        self._build_split_section()
        self._build_detect_section()
        self._build_pages_section()
        self._build_resize_section()
        self._build_exec_section()
        self._build_bottom_bar()                     # Settings/Help + nav scroll with the rest (B#1)

        right = ctk.CTkFrame(self.paned, fg_color=CARD, corner_radius=12)
        self.paned.add(right, minsize=480, stretch="always")
        self.canvas = ctk.CTkCanvas(right, highlightthickness=0, bd=0,
                                    bg=t["CANVAS_BG"], cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_render(50))

        self.status = ctk.CTkLabel(right, text="", text_color=STATUS_FG, justify="right",
                                   font=ctk.CTkFont(self.sys_mono, self.fs - 1),
                                   fg_color=CARD, corner_radius=6)
        self.status.place(relx=1.0, rely=1.0, x=-12, y=-10, anchor="se")
        self._build_overlay(right)
        self._refresh_mode_badge()
        self._sync_split_ui()
        self._sync_pages_ui()
        self._sync_resize_ui()

    def _card(self, title: str, header_extra=None) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.controls, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=CARD_BORDER)
        card.pack(fill="x", padx=4, pady=6)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(head, text=title, font=self.font_title, anchor="w").pack(side="left")
        if header_extra is not None:
            header_extra(head)
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(0, 12))
        return body

    def _btn(self, master, text, cmd, primary=False, **kw):
        # All buttons look neutral at rest; an "active" highlight is applied separately via
        # _set_active (#16). `primary` kept for call-site intent but no longer fills.
        kw.setdefault("height", 36)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", CARD_BORDER)
        return ctk.CTkButton(master, text=text, command=cmd, fg_color=SECONDARY,
                             hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT,
                             font=self.font_base, corner_radius=8, **kw)

    def _set_active(self, btn, on: bool):
        """Highlight a button only while it represents an active state (#16)."""
        btn.configure(fg_color=ACCENT if on else SECONDARY,
                      text_color=ACCENT_TEXT if on else SECONDARY_TEXT,
                      hover_color=ACCENT_HOVER if on else SECONDARY_HOVER)

    def _seg_tips(self, seg: ctk.CTkSegmentedButton, mapping: Dict[str, str]):
        for val, btn in getattr(seg, "_buttons_dict", {}).items():
            if val in mapping:
                ToolTip(btn, mapping[val], self)

    def _build_bottom_bar(self) -> None:
        # Settings/Help + nav is the last card. A flexible spacer above it grows to push the
        # card to the visible bottom of the panel when the column is shorter than the
        # viewport (so it looks pinned), and collapses to nothing when the column overflows,
        # letting the card scroll into reach like any other card (#5).
        self._bb_spacer = ctk.CTkFrame(self.controls, fg_color="transparent", height=1)
        self._bb_spacer.pack(fill="x")
        bar = ctk.CTkFrame(self.controls, fg_color=CARD, corner_radius=12, border_width=1,
                           border_color=CARD_BORDER)
        bar.pack(fill="x", padx=4, pady=(2, 8))
        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(10, 4))
        bs = self._btn(row1, "⚙  Settings", self.open_settings)
        bs.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ToolTip(bs, "Appearance, output, behaviour and scan settings.", self)
        bh = self._btn(row1, "?  Help", self.open_help)
        bh.pack(side="left", expand=True, fill="x", padx=(4, 0))
        ToolTip(bh, "Quick-start guide with an interactive table of contents.", self)
        # Page nav: arrows hug the edges, the page box gets the middle space so the
        # current/total page numbers stay fully visible up to 4 digits (#3).
        row2 = ctk.CTkFrame(bar, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 10))
        row2.columnconfigure(0, weight=0)
        row2.columnconfigure(1, weight=1)
        row2.columnconfigure(2, weight=0)
        self._btn(row2, "◀", self.prev_page, width=46).grid(row=0, column=0, sticky="w")
        pagebox = ctk.CTkFrame(row2, fg_color="transparent")
        pagebox.grid(row=0, column=1, sticky="")
        self.page_var = tk.StringVar(value="1")
        pe = ctk.CTkEntry(pagebox, textvariable=self.page_var, width=64, justify="center",
                          font=self.font_base)
        pe.pack(side="left")
        pe.bind("<Return>", self.jump_to_page)
        self.page_total = ctk.CTkLabel(pagebox, text="/ 0", font=self.font_base, text_color=MUTED)
        self.page_total.pack(side="left", padx=(8, 0))
        self._btn(row2, "▶", self.next_page, width=46).grid(row=0, column=2, sticky="e")
        # Reflow whenever the viewport height changes; content-height changes call it directly.
        self.controls._parent_canvas.bind("<Configure>", self._reflow_bottom_bar, add="+")
        self.root.after_idle(self._reflow_bottom_bar)

    def _reflow_bottom_bar(self, _e=None) -> None:
        """Size the spacer so the Settings/Help+nav card sits at the panel bottom when there
        is room, and collapses (card scrolls) when the column overflows the viewport (#5)."""
        if not hasattr(self, "_bb_spacer"):
            return
        try:
            self.controls.update_idletasks()
            viewport = self.controls._parent_canvas.winfo_height()
            cur = self._bb_spacer.winfo_height()
            content = self.controls.winfo_reqheight() - cur     # column height sans the spacer
            target = max(1, viewport - content)
            if abs(target - cur) > 2:
                self._bb_spacer.configure(height=target)
        except tk.TclError:
            pass

    def _build_doc_section(self) -> None:
        def badge(head):
            # A detection *marker*, not a button: same pill look, but not interactive (#3).
            self.mode_badge = ctk.CTkLabel(head, text="NORMAL", font=self.font_badge,
                                           corner_radius=11, width=88, height=26,
                                           text_color="white")
            self.mode_badge.pack(side="right", padx=(16, 0))     # gap after the title (#4)
            ToolTip(self.mode_badge, "Detected document mode (Normal = vector, "
                    "Scanned = raster). Set automatically on load.", self)
        body = self._card("Document & State", badge)
        bl = self._btn(body, "\U0001F4C2   Load PDF", self.load_pdf, primary=True, height=40)
        bl.pack(fill="x", pady=(2, 8))
        ToolTip(bl, "Open a PDF (Ctrl+O). Classifies Normal vs Scanned automatically.", self)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        row.columnconfigure((0, 1, 2), weight=1, uniform="urr")
        bu = self._btn(row, "↩ Undo", self.undo)
        bu.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(bu, "Undo (Ctrl+Z).", self)
        br = self._btn(row, "Redo ↪", self.redo)
        br.grid(row=0, column=1, sticky="ew", padx=4)
        ToolTip(br, "Redo (Ctrl+Y).", self)
        brs = self._btn(row, "⟲ Reset", self.reset_document)
        brs.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        ToolTip(brs, "Reload the current page from its cached source.", self)

    def _build_scan_section(self) -> None:
        self.scan_card = ctk.CTkFrame(self.controls, fg_color=CARD, corner_radius=12,
                                      border_width=1, border_color=CARD_BORDER)
        head = ctk.CTkFrame(self.scan_card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(head, text="Scan Processing", font=self.font_title, anchor="w").pack(side="left")
        body = ctk.CTkFrame(self.scan_card, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(0, 12))
        self.btn_dewarp = self._btn(body, "Dewarp & Deskew", self.run_dewarp)
        self.btn_dewarp.pack(fill="x", pady=(2, 10))
        ToolTip(self.btn_dewarp, "Straighten pages (deskew; mesh dewarp when a model is "
                "present) over the Pages selection. Idempotent from the source page.", self)
        clean = ctk.CTkFrame(body, fg_color="transparent", border_width=1,
                             border_color=CARD_BORDER, corner_radius=10)
        clean.pack(fill="x")
        ctk.CTkLabel(clean, text="Clean", font=self.font_title, anchor="w").pack(
            anchor="w", padx=12, pady=(10, 4))
        crow = ctk.CTkFrame(clean, fg_color="transparent")
        crow.pack(fill="x", padx=12)
        crow.columnconfigure((0, 1), weight=1)
        self.btn_bw = self._btn(crow, "B/W", lambda: self.set_clean_mode("bw"))
        self.btn_bw.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_bw, "B/W filter — bilevel black/white threshold. Press again to turn off.", self)
        self.btn_gray = self._btn(crow, "Grayscale", lambda: self.set_clean_mode("gray"))
        self.btn_gray.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(self.btn_gray, "Flatten + sharpen, keeps continuous tone. Mutually exclusive "
                "with B/W.", self)
        ctk.CTkLabel(clean, text="Strength", font=self.font_title, anchor="w").pack(
            anchor="w", padx=12, pady=(8, 2))
        self.strength_seg = ctk.CTkSegmentedButton(
            clean, values=["1", "2", "3"], font=self.font_base,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=SEG_UNSEL, text_color=ACCENT_TEXT,
            command=lambda v: self.set_clean_strength(int(v)))
        self.strength_seg.set("2")
        self.strength_seg.pack(fill="x", padx=12, pady=(0, 12))
        self._seg_tips(self.strength_seg, {v: f"Strength {v} — "
                       f"{['cautious', 'normal', 'aggressive'][i]} cleaning."
                       for i, v in enumerate(["1", "2", "3"])})

    def _build_split_section(self) -> None:
        body = self._card("Split Into")
        self.split_seg = ctk.CTkSegmentedButton(
            body, values=["1", "2", "4"], font=self.font_base,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=SEG_UNSEL, text_color=ACCENT_TEXT,
            command=lambda v: self.set_split(int(v)))
        self.split_seg.set("1")
        self.split_seg.pack(fill="x")
        self._seg_tips(self.split_seg, {str(k): v for k, v in SPLIT_TIP.items()})
        self.same_size_row = self._switch_row(
            body, "Same size", self.same_size_var, self._on_same_size,
            "ON: keep every split rectangle the same size (dragging one resizes all to match).")

    def _build_detect_section(self) -> None:
        body = self._card("Detect")
        self.detect_body = body
        self.btn_detect = self._btn(body, "✦   Auto-detect", self.detect_content, primary=True,
                                    height=40)
        self.btn_detect.pack(fill="x", pady=(2, 8))
        ToolTip(self.btn_detect, "Per-page content box, then one union box across the Pages "
                "selection. Safe to re-press.", self)
        self.sw_left = self._switch_row(body, "Anchor Left", self.auto_left_var,
                                        self._on_anchor, "ON: this page's detected left edge. "
                                        "OFF: union-minimum left edge.").switch
        self.sw_top = self._switch_row(body, "Anchor Top", self.auto_top_var, self._on_anchor,
                                       "ON: this page's detected top edge. OFF: union-minimum "
                                       "top edge.").switch
        ratio_row = ctk.CTkFrame(body, fg_color="transparent")
        ratio_row.pack(fill="x", pady=4)
        self.sw_ratio = ctk.CTkSwitch(ratio_row, text="Keep ratio", variable=self.keep_ratio_var,
                                      command=self._on_ratio_toggle, font=self.font_base,
                                      progress_color=ACCENT)
        self.sw_ratio.pack(side="left")
        self.ratio_entry = ctk.CTkEntry(ratio_row, textvariable=self.ratio_var, width=72,
                                        justify="center", font=self.font_base)
        self.ratio_entry.pack(side="right")
        self.ratio_entry.bind("<Return>", lambda _e: self.render_page())
        ToolTip(ratio_row, "When ON, editing Right adjusts Bottom to hold this width÷height "
                "ratio. The ratio field is editable.", self)
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", pady=(8, 6))
        grid.columnconfigure((0, 1, 2, 3), weight=1, uniform="off")
        self._off_spins: List[Spin] = []
        for col, (lab, var) in enumerate([("L", self.left_off), ("T", self.top_off),
                                          ("R", self.right_off), ("B", self.bottom_off)]):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(cell, text=lab, font=self.font_base, text_color=MUTED,
                         width=14).pack(side="left", padx=(0, 4))
            sp = Spin(cell, var, self, width=48)
            sp.pack(side="left", fill="x", expand=True)
            ToolTip(sp.entry, OFFSET_TIP[lab], self)
            sp.entry.bind("<FocusOut>", self._clamp_offsets, add="+")   # snap to page limits (#7)
            sp.entry.bind("<Return>", self._clamp_offsets, add="+")
            self._off_spins.append(sp)
        for var in (self.left_off, self.top_off, self.bottom_off):
            var.trace_add("write", lambda *_: self._on_offset_change())
        self.right_off.trace_add("write", lambda *_: self._on_right_change())
        bc = self._btn(body, "✕   Clear", self.clear_detect)
        bc.pack(fill="x")
        ToolTip(bc, "Drop detection and reset all offsets.", self)

    def _switch_row(self, master, text, var, cmd, tip):
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", pady=4)
        sw = ctk.CTkSwitch(row, text=text, variable=var, command=cmd, font=self.font_base,
                           progress_color=ACCENT)
        sw.pack(side="left")
        ToolTip(row, tip, self)
        row.switch = sw
        return row

    def _build_pages_section(self) -> None:
        body = self._card("Pages")
        self.pages_seg = ctk.CTkSegmentedButton(
            body, values=["All", "Odd", "Even", "Selected"], font=self.font_base,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=SEG_UNSEL, text_color=ACCENT_TEXT,
            command=self.set_pages_mode)
        self.pages_seg.set("All")
        self.pages_seg.pack(fill="x")
        self._seg_tips(self.pages_seg, {
            "All": "Every page in the document.",
            "Odd": "Odd page numbers (1, 3, 5 …) — 1-indexed.",
            "Even": "Even page numbers (2, 4, 6 …) — 1-indexed.",
            "Selected": "Reveal a field for a custom list: 1,3,5-9,12 (commas + ranges)."})
        self.select_row = ctk.CTkFrame(body, fg_color="transparent")
        ctk.CTkLabel(self.select_row, text="Pattern", font=self.font_base).pack(side="left")
        bcur = self._btn(self.select_row, "⦿ Current", self._select_current, width=96, height=30)
        bcur.pack(side="right", padx=(8, 0))          # right at the tab edge (#9, #12)
        ToolTip(bcur, "Set the pattern to the current page and keep it selected.", self)
        se = ctk.CTkEntry(self.select_row, textvariable=self.select_var, font=self.font_mono)
        se.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ToolTip(se, "Pages 1,3,5-9,12 — commas, ranges (a-b) and slices (a:b) accepted.", self)

    def _select_current(self):
        self.select_var.set(str(self.current_page + 1))
        if self.pages_mode != "select":
            self.set_pages_mode("Selected")
        self.render_page()

    def _build_resize_section(self) -> None:
        body = self._card("Resize")
        cb = ctk.CTkOptionMenu(body, variable=self.resize_var, values=list(RESOLUTIONS),
                               command=lambda _v: self._sync_resize_ui(), font=self.font_base,
                               fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                               button_hover_color=ACCENT, text_color=SECONDARY_TEXT)
        cb.pack(fill="x")
        ToolTip(cb, "Output size, applied last (after crop).", self)
        self.custom_row = ctk.CTkFrame(body, fg_color="transparent")
        ctk.CTkLabel(self.custom_row, text="W", font=self.font_base).pack(side="left")
        self.custom_w = ctk.CTkEntry(self.custom_row, width=70, font=self.font_base)
        self.custom_w.pack(side="left", padx=(4, 12))
        ctk.CTkLabel(self.custom_row, text="H", font=self.font_base).pack(side="left")
        self.custom_h = ctk.CTkEntry(self.custom_row, width=70, font=self.font_base)
        self.custom_h.pack(side="left", padx=(4, 0))

    def _build_exec_section(self) -> None:
        body = ctk.CTkFrame(self.controls, fg_color="transparent")
        body.pack(fill="x", padx=4, pady=(2, 10))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        row.columnconfigure((0, 1, 2), weight=1, uniform="exec")
        self.btn_apply = self._btn(row, "✂  Crop", self.apply_crop, primary=True, height=42)
        self.btn_apply.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_apply, "Apply the crop to the Pages selection (Ctrl+Enter).", self)
        brot = self._btn(row, "↻  Rotate", self.rotate_pages, height=42)
        brot.grid(row=0, column=1, sticky="ew", padx=4)
        ToolTip(brot, "Rotate the Pages selection 90° CW; cleaning survives rotation.", self)
        bdel = self._btn(row, "🗑  Delete", self.delete_pages, height=42)
        bdel.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        ToolTip(bdel, "Delete the Pages selection from the document.", self)
        bex = self._btn(body, "\U0001F4BE   Export PDF", self.save_pdf, primary=True, height=44)
        bex.pack(fill="x")
        ToolTip(bex, "Save the processed document (Ctrl+S).", self)

    def _build_overlay(self, master) -> None:
        self.overlay = ctk.CTkFrame(master, fg_color=CARD, corner_radius=14, border_width=1,
                                    border_color=CARD_BORDER)
        self.ov_title = ctk.CTkLabel(self.overlay, text="", font=self.font_title)
        self.ov_title.pack(padx=28, pady=(20, 8))
        self.ov_bar = ctk.CTkProgressBar(self.overlay, width=260, progress_color=ACCENT)
        self.ov_bar.set(0)
        self.ov_bar.pack(padx=28)
        self.ov_count = ctk.CTkLabel(self.overlay, text="", font=self.font_mono, text_color=MUTED)
        self.ov_count.pack(pady=(6, 4))
        self.ov_cancel_evt: Optional[threading.Event] = None
        self._btn(self.overlay, "Cancel", self._cancel_progress).pack(pady=(6, 20), padx=28)

    def _show_progress(self, title, total):
        self.ov_title.configure(text=f"{title}…")
        self.ov_bar.set(0)
        self.ov_count.configure(text=f"0 / {total}")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.overlay.lift()

    def _cancel_progress(self):
        if self.ov_cancel_evt:
            self.ov_cancel_evt.set()

    def _hide_progress(self):
        self.overlay.place_forget()

    # ════════════════════════════════════════════════════════════════════
    #  SHORTCUTS / SCALING
    # ════════════════════════════════════════════════════════════════════
    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind("<Control-o>", lambda _e: self.load_pdf())
        r.bind("<Control-Return>", lambda _e: self.apply_crop())
        r.bind("<Control-s>", lambda _e: self.save_pdf())
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
                              max(0.7, min(2.0, round(self._scale_target + delta, 2))))
        if self._scale_job is None:
            self._apply_scale()
            self._scale_job = self.root.after(80, self._scale_tick)

    def _scale_tick(self) -> None:
        self._scale_job = None
        if abs(self._scale_target - self.ui_scale) > 1e-3:      # value accrued while throttled
            self._apply_scale()
            self._scale_job = self.root.after(80, self._scale_tick)

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
        self._scale_target = max(0.7, min(2.0, pct / 100.0))
        self._apply_scale()

    def _set_font_size(self, value: str) -> None:
        try:
            n = max(10, min(24, int(value)))
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
    #  DOCUMENT
    # ════════════════════════════════════════════════════════════════════
    def _load_synthetic(self) -> None:
        self.doc = None
        rnd = random.Random(7)
        self._pt_size = [(600 + rnd.uniform(-15, 15), 820 + rnd.uniform(-20, 20))
                         for _ in range(SYNTH_PAGES)]
        self._reset_doc_state()
        self._set_mode("normal")
        self.status_msg(f"Synthetic {SYNTH_PAGES}-page sample — Load PDF for a real file.")

    def load_pdf(self) -> None:
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF", "*.pdf")])
        if path:
            self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            doc = fitz.open(path)
            if doc.page_count == 0:
                raise ValueError("PDF has no pages.")
        except Exception as exc:
            messagebox.showerror("Load PDF", f"Could not open file:\n{exc}")
            return
        self.doc = doc
        self._pdf_path = path
        self.root.title(f"SmartCrop PDF — {os.path.basename(path)}")     # (#14)
        self._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
        self._reset_doc_state()
        mode = self._classify_document()
        self._set_mode(mode)
        self.status_msg(f"Loaded {doc.page_count} pages — classified {mode.capitalize()}.")

    def reset_document(self):
        """Reset everything to the just-opened state (re-open the book) (#11)."""
        if self.doc is not None and self._pdf_path:
            self.history.clear(); self.redo_stack.clear()
            self._open_path(self._pdf_path)
        else:                                        # synthetic demo doc
            self._reset_doc_state()
            self._set_mode("normal")
            self._load_synthetic()
        self.status_msg("Reset to the original document.")

    def _reset_doc_state(self) -> None:
        self.current_page = 0
        for d in (self._processed, self._source_cache, self._work_cache, self._detect_cache):
            d.clear()
        self._union = None
        self.auto_active = False
        self.crop_rects.clear()
        self._rect_ratio.clear()
        self.history.clear()
        self.redo_stack.clear()
        self.dewarp_on = False
        self.clean_mode = "none"
        self._out_pages = []
        self._applied.clear()
        self._rotation.clear()
        for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            var.set(0.0)

    def page_count(self) -> int:
        return len(self._pt_size)

    def _classify_document(self) -> str:
        if self.doc is None:
            return self.mode
        scanned = 0
        for i in range(self.doc.page_count):
            page = self.doc[i]
            area = page.rect.width * page.rect.height
            cov = 0.0
            try:
                for info in page.get_image_info():
                    bx = info.get("bbox")
                    if bx:
                        cov = max(cov, abs((bx[2] - bx[0]) * (bx[3] - bx[1])) / max(area, 1.0))
            except Exception:
                pass
            if len(page.get_text().strip()) < MODE_TEXT_MIN and cov >= MODE_IMG_COVER:
                scanned += 1
        return "scanned" if scanned * 2 > self.doc.page_count else "normal"

    def _toggle_mode(self) -> None:
        self._set_mode("scanned" if self.mode == "normal" else "normal")

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._detect_cache.clear()
        self._work_cache.clear()
        self._union = None
        self.auto_active = False
        if hasattr(self, "scan_card"):
            if mode == "scanned":
                self.scan_card.pack(fill="x", padx=4, pady=6,
                                    after=self.controls.winfo_children()[0])
            else:
                self.scan_card.pack_forget()
            self.controls._parent_canvas.yview_moveto(0.0)   # no gap at top after switch
            self.root.after_idle(self._reflow_bottom_bar)
        self._refresh_mode_badge()
        self.render_page()

    def _refresh_mode_badge(self) -> None:
        if not hasattr(self, "mode_badge"):
            return
        scan = self.mode == "scanned"
        self.mode_badge.configure(text="SCANNED" if scan else "NORMAL",
                                  fg_color=THEMES["dark"]["BADGE_SCAN"] if scan
                                  else THEMES["dark"]["BADGE_NORMAL"])

    def status_msg(self, text: str) -> None:
        if hasattr(self, "status"):
            self.status.configure(text=text)
            self.root.after(2400, self._status_idle)

    def _status_idle(self) -> None:
        if not self._busy and hasattr(self, "status"):
            self.status.configure(text=f"page {self.current_page + 1} / {self.page_count()}")

    def _page_dims(self, idx: int) -> Tuple[float, float]:
        w, h = self._pt_size[idx]
        if self.mode == "scanned":
            k = SRC_DPI / 72.0
            w, h = w * k, h * k
        if self._rotation.get(idx, 0) % 180 == 90:    # rotation swaps page dimensions
            return h, w
        return w, h

    # ════════════════════════════════════════════════════════════════════
    #  RASTER
    # ════════════════════════════════════════════════════════════════════
    def _source_image(self, idx: int) -> Image.Image:
        img = self._source_cache.get(idx)
        if img is not None:
            return img
        if self.doc is not None:
            pm = self.doc[idx].get_pixmap(dpi=int(SRC_DPI if self.mode == "scanned" else NORMAL_DPI),
                                          alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        else:
            img = self._synthetic_image(idx)
        ang = self._rotation.get(idx, 0)              # apply page rotation (#8, #13)
        if ang:
            img = img.rotate(-ang, expand=True)       # PIL rotates CCW; -ang = clockwise
        self._source_cache[idx] = img
        return img

    def _synthetic_image(self, idx: int) -> Image.Image:
        w, h = self._pt_size[idx]
        img = Image.new("RGB", (int(w), int(h)), "white")
        d = ImageDraw.Draw(img)
        rnd = random.Random(idx * 31 + 1)
        box = self._synthetic_text_box(idx, w, h)
        if self.mode == "normal":
            y = box.y0
            while y < box.y1 - 10:
                d.line([(box.x0, y), (box.x1 - rnd.uniform(0, w * 0.18), y)],
                       fill=(70, 70, 75), width=2)
                y += rnd.uniform(14, 20)
            d.rectangle([box.x0, box.y0, box.x1, box.y1], outline=(210, 210, 215))
            return img
        d.rectangle([box.x0, box.y0, box.x1, box.y1], fill=(60, 60, 65))
        for _ in range(40):
            x, y = rnd.uniform(box.x0, box.x1), rnd.uniform(box.y0, box.y1)
            d.ellipse([x, y, x + 3, y + 3], fill=(230, 230, 225))
        return img.rotate(rnd.uniform(-5, 5), fillcolor="white", resample=Image.BICUBIC)

    def _synthetic_text_box(self, idx, w, h) -> Box:
        rnd = random.Random(idx * 17 + 3)
        return Box(w * (0.09 + rnd.uniform(-0.02, 0.03)), h * (0.10 + rnd.uniform(-0.02, 0.03)),
                   w * (1 - 0.09 - rnd.uniform(-0.02, 0.03)), h * (1 - 0.13 - rnd.uniform(-0.03, 0.03)))

    def _work_image(self, idx: int) -> Image.Image:
        cached = self._work_cache.get(idx)
        if cached is not None:
            return cached
        src = self._source_image(idx)
        if self.mode != "scanned":
            self._work_cache[idx] = src
            return src
        proc = self._processed.get(idx, {})
        bgr = cv2.cvtColor(np.array(src), cv2.COLOR_RGB2BGR)
        if proc.get("dewarp"):
            bgr = self._dewarp_bgr(bgr)
        clean = proc.get("clean")
        if clean:
            cmode, strength = clean
            if cmode == "bw":
                g = imaging.clean_document_bilevel(bgr, strength=strength, upscale=1.0)
            else:
                g = imaging.sharpen_grayscale(bgr, amount=_CLEAN_AMOUNT[strength])
            bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        out = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        self._work_cache[idx] = out
        return out

    def _dewarp_bgr(self, bgr: np.ndarray) -> np.ndarray:
        """Real learned mesh dewarp when docuwarp is present; otherwise deskew-only."""
        if imaging.unwarp_available():
            try:
                return imaging.unwarp_bgr(bgr)
            except Exception:
                pass
        return imaging.deskew_auto(bgr)[0]

    def _gray_for_detect(self, idx: int) -> np.ndarray:
        img = self._work_image(idx) if self.mode == "scanned" else self._source_image(idx)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

    # ════════════════════════════════════════════════════════════════════
    #  DETECT / GEOMETRY
    # ════════════════════════════════════════════════════════════════════
    def _resolve_pages(self) -> List[int]:
        try:
            from parsing import pages_for_mode
            return pages_for_mode(self.pages_mode, self.page_count(), self.current_page,
                                  self.select_var.get())
        except ValueError:
            return []

    def _content_box_page(self, idx: int) -> Box:
        w, h = self._page_dims(idx)
        if self.mode == "normal":
            if self.doc is not None:
                blocks = [b for b in self.doc[idx].get_text("blocks") if b[6] == 0 and b[4].strip()]
                if blocks:
                    return Box(min(b[0] for b in blocks), min(b[1] for b in blocks),
                               max(b[2] for b in blocks), max(b[3] for b in blocks))
                return Box(0, 0, w, h)
            return self._synthetic_text_box(idx, w, h)
        img = self._work_image(idx) if self.mode == "scanned" else self._source_image(idx)
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        g0h, g0w = bgr.shape[:2]
        s = min(1.0, DETECT_MAX_PX / max(g0h, g0w))      # downscale for speed (#12)
        if s < 1.0:
            bgr = cv2.resize(bgr, (max(1, round(g0w * s)), max(1, round(g0h * s))),
                             interpolation=cv2.INTER_AREA)
        gh, gw = bgr.shape[:2]
        # Real Sauvola clean (flattens photo background) → far better ink mask on real scans
        # than a global Otsu, which marks a photographed page's tinted paper as ink (#5).
        bw = imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
        t = imaging.content_box(bw)              # (x0,y0,x1,y1) in (downscaled) raster px
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
        if self.mode == "scanned":
            self._threaded_map(indices, self._content_box_page, self._finish_detect, "Detecting")
        else:
            self._finish_detect({i: self._content_box_page(i) for i in indices})

    def _finish_detect(self, results: Dict[int, Box]) -> None:
        self._detect_cache.update(results)
        if not results:
            messagebox.showwarning("Auto-detect", "No text or ink found.")
            return
        # Exclude pages where detection fell back to the full page — one such outlier would
        # blow W/H up to the sheet size and push right/bottom to the page edge (#2).
        good = []
        for i, b in results.items():
            w, h = self._page_dims(i)
            if b.width < 0.97 * w or b.height < 0.97 * h:
                good.append(b)
        boxes = good or list(results.values())
        self._union = union_box(boxes)               # constant W=max width, H=max height
        self.auto_active = True
        self._applied.clear()
        self._sync_ratio_label()
        self._refresh_detect_enabled()               # highlight Auto-detect (#16)
        self.render_page()
        self.status_msg(f"Detected {self._union.width:.0f}×{self._union.height:.0f} px "
                        f"crop over {len(boxes)} page(s).")

    def clear_detect(self) -> None:
        self.auto_active = False
        self._union = None
        self._detect_cache.clear()
        self._applied.clear()
        self._suspend = True
        for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            var.set(0.0)
        self._suspend = False
        self._sync_ratio_label()
        self._refresh_detect_enabled()               # un-highlight Auto-detect (#16)
        self.render_page()

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
        if self.keep_ratio_var.get():                # lock height = width / ratio (#14)
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
        of accepting absurd numbers like 100000 (#7). Done by round-tripping the crop
        through clamp_box and reading each edge back out as its offset."""
        if not (self.auto_active and self._union):   # no live crop → just bound to ±100
            self._suspend = True
            for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
                try:
                    v = float(var.get())
                except (tk.TclError, ValueError):
                    v = 0.0
                var.set(round(max(-100.0, min(100.0, v)), 1))
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
        lb = b.x0 if self.auto_left_var.get() else u.x0
        tb = b.y0 if self.auto_top_var.get() else u.y0
        self._suspend = True
        self.left_off.set(round((lb - rect.x0) / w * 100.0, 1))
        self.top_off.set(round((tb - rect.y0) / h * 100.0, 1))
        self.right_off.set(round((rect.x1 - (lb + u.width)) / w * 100.0, 1))
        if not self.keep_ratio_var.get():            # B is inert (derived) when ratio is locked
            self.bottom_off.set(round((rect.y1 - (tb + u.height)) / h * 100.0, 1))
        else:
            try:
                bv = float(self.bottom_off.get())
            except (tk.TclError, ValueError):
                bv = 0.0
            self.bottom_off.set(round(max(-100.0, min(100.0, bv)), 1))
        self._suspend = False
        self.render_page()

    def _on_anchor(self):
        self._refresh_detect_enabled()               # both anchors OFF ⇒ detect inactive (#4)
        self.render_page()

    def _on_ratio_toggle(self):
        self._sync_ratio_label()
        self.render_page()

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
        if applied:                                  # show committed crop (first box), not full page (#13)
            box = applied[0]
            ix, iy = work.width / w, work.height / h
            work = work.crop((round(box.x0 * ix), round(box.y0 * iy),
                              round(box.x1 * ix), round(box.y1 * iy)))
            w, h = box.width, box.height
        self.scale = min((cw - CANVAS_MARGIN) / w, (ch - CANVAS_MARGIN) / h)
        disp = work.resize((max(1, round(w * self.scale)), max(1, round(h * self.scale))),
                           Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(disp)
        self.img_x = max(0, (cw - disp.width) // 2)
        self.img_y = max(0, (ch - disp.height) // 2)
        self.canvas.delete("all")
        self.canvas.create_image(self.img_x, self.img_y, anchor="nw", image=self.tk_image)
        if not applied:                              # no handles/overlay over a committed crop
            self._draw_overlay()
        self.page_var.set(str(self.current_page + 1))
        self.page_total.configure(text=f"/ {self.page_count()}")
        if not self._busy:
            self.status.configure(text=f"page {self.current_page + 1} / {self.page_count()}")
        self._set_controls_enabled(not self._busy)

    def _draw_overlay(self) -> None:
        t = self._theme()
        split = self.split_count > 1
        if self._draw_rect is not None:               # rubber-band for a new crop area (B#2)
            dx0, dy0 = self._pdf_to_canvas(self._draw_rect.x0, self._draw_rect.y0)
            dx1, dy1 = self._pdf_to_canvas(self._draw_rect.x1, self._draw_rect.y1)
            self.canvas.create_rectangle(dx0, dy0, dx1, dy1, outline=CROP_BLUE, width=2, dash=(4, 3))
            return
        for i, box in enumerate(self._preview_boxes()):
            if box is None:
                continue
            color = SPLIT_BLUE if split else CROP_BLUE
            width = 4 if split else 3                  # split lines 30% thicker, absolute (#12)
            x0, y0 = self._pdf_to_canvas(box.x0, box.y0)
            x1, y1 = self._pdf_to_canvas(box.x1, box.y1)
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=width, dash=(6, 4))
            for hx, hy in self._handle_positions(box).values():
                self.canvas.create_polygon(hx, hy - HANDLE_R, hx + HANDLE_R, hy, hx, hy + HANDLE_R,
                                           hx - HANDLE_R, hy, fill=t["HANDLE_FILL"],
                                           outline=t["HANDLE"], width=2)
            if split:                                 # big number, no circle, dark blue (#12)
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
        if self._applied.pop(self.current_page, None) is not None:   # editing resumes full page
            self.render_page()
        if self.split_count > 1:
            self._press_split(event)
        else:
            self._press_auto(event)

    def _press_auto(self, event):
        box = self._crop_rect(self.current_page)
        px, py = self._canvas_to_pdf(event.x, event.y)
        handle = self._hit_handle(box, event.x, event.y) if box is not None else None
        w, h = self._page_dims(self.current_page)
        b = self._detect_cache.get(self.current_page) or Box(0, 0, w, h)
        u = self._union or Box(0, 0, w, h)
        base = dict(rect0=box, start=(px, py), w=w, h=h,
                    left_base=b.x0 if self.auto_left_var.get() else u.x0,
                    top_base=b.y0 if self.auto_top_var.get() else u.y0)
        if handle is not None:                       # resize one edge
            self._drag = dict(kind="auto", handle=handle, **base)
            self.canvas.configure(cursor=HANDLE_CURSOR[handle])
        elif box is not None and point_in_box(box, px, py):   # move the whole crop (#10)
            self._drag = dict(kind="auto-move", **base)
            self.canvas.configure(cursor="fleur")
        else:                                        # empty area → draw a fresh crop (B#2)
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
        px, py = self._canvas_to_pdf(event.x, event.y)
        dx, dy = px - self._drag["start"][0], py - self._drag["start"][1]
        k = self._drag["kind"]
        if k == "auto":
            d = self._drag
            self._write_auto_offsets(resize_by_handle(d["rect0"], d["handle"], dx, dy, d["w"], d["h"]))
        elif k == "auto-move":                       # translate the whole auto crop (#10)
            d = self._drag
            self._write_auto_offsets(move_box(d["rect0"], dx, dy, d["w"], d["h"]))
        elif k == "split-edge":
            self._drag_split_edge(dx, dy)
        elif k == "split-move":
            self._drag_split_move(dx, dy)
        else:                                        # "draw" — live rubber-band rectangle
            w, h = self._page_dims(self.current_page)
            sx, sy = self._drag["start"]
            self._draw_rect = clamp_box(Box(min(sx, px), min(sy, py),
                                            max(sx, px), max(sy, py)), w, h)
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
                ratio = self._rect_ratio[i] if i < len(self._rect_ratio) else None
                if ratio:
                    box = self.crop_rects[i]
                    _, h = self._page_dims(self.current_page)
                    self.crop_rects[i] = Box(box.x0, box.y0, box.x1,
                                             box.y0 + min(box.width / ratio, h - box.y0))
            if self.same_size_var.get():
                self._apply_same_size(i)
            self.render_page()
        elif d and d["kind"] == "draw":
            self._commit_drawn_rect()
        self._drag = None
        self.canvas.configure(cursor="crosshair")

    def _commit_drawn_rect(self):
        """Adopt the rubber-band rectangle as the crop (replacing any previous one)."""
        r = self._draw_rect
        self._draw_rect = None
        if r is None or r.width < 2 * MIN_RECT or r.height < 2 * MIN_RECT:
            self.render_page()
            return
        if not (self.auto_left_var.get() or self.auto_top_var.get()):
            self.auto_left_var.set(True)             # need an anchor for the crop to show (#4)
        idx = self.current_page
        self._detect_cache[idx] = r                  # this page's content edge = drawn corner
        self._union = Box(r.x0, r.y0, r.x1, r.y1)    # constant W/H = drawn size
        self.auto_active = True
        self._applied.pop(idx, None)
        self._suspend = True
        for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            var.set(0.0)
        self._suspend = False
        self._sync_ratio_label()
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg("New crop area set — drag handles to fine-tune.")

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
        parts.append(f"page {self.current_page + 1} / {self.page_count()}")
        self.status.configure(text="     ".join(parts))

    # ════════════════════════════════════════════════════════════════════
    #  SPLIT
    # ════════════════════════════════════════════════════════════════════
    def set_split(self, n: int):
        self.split_count = n
        if n == 1:
            self.crop_rects.clear()
            self._rect_ratio.clear()
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
        self._rect_ratio = [r.width / r.height if r.height else None for r in self.crop_rects]

    def _on_same_size(self, _v=None):
        if self.same_size_var.get() and self.split_count > 1:
            self._auto_layout_split(self.split_count)
            self.render_page()

    def _sync_split_ui(self):
        if self.split_count in (2, 4):
            self.same_size_row.pack(fill="x", pady=(8, 0))
        else:
            self.same_size_row.pack_forget()
        self.root.after_idle(self._reflow_bottom_bar)
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
        re-pressable at any time so re-running after editing the crop always works (#2)."""
        one_anchor = self.auto_left_var.get() or self.auto_top_var.get()
        ok = self.split_count == 1 and one_anchor and not self._busy
        if hasattr(self, "btn_detect"):
            self.btn_detect.configure(state="normal" if ok else "disabled")
            self._set_active(self.btn_detect, False)

    # ════════════════════════════════════════════════════════════════════
    #  SCAN PROCESSING
    # ════════════════════════════════════════════════════════════════════
    def run_dewarp(self):
        if self._busy:
            return
        self.dewarp_on = not self.dewarp_on
        self._refresh_scan_buttons()
        self._snapshot_history()
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Dewarp & Deskew", "Empty Pages selection.")
            return
        for i in indices:
            self._processed.setdefault(i, {})["dewarp"] = self.dewarp_on
        self._work_cache.clear()
        if self.dewarp_on and imaging.unwarp_available():     # warm the model on the main thread
            try:                                              # so the 1st batch run isn't skipped (#8)
                imaging.unwarp_bgr(np.full((32, 32, 3), 255, np.uint8))
            except Exception:
                pass
        self._threaded_map(indices, self._work_image, lambda _r: self.render_page(),
                           "Dewarp & Deskew")

    def set_clean_mode(self, mode: str):
        if self._busy:
            return
        self.clean_mode = "none" if self.clean_mode == mode else mode
        self._refresh_scan_buttons()
        self._run_clean()

    def set_clean_strength(self, n: int):
        self.clean_strength = n
        if self.clean_mode != "none":
            self._run_clean()

    def _refresh_scan_buttons(self):
        self._set_active(self.btn_dewarp, self.dewarp_on)
        self._set_active(self.btn_bw, self.clean_mode == "bw")
        self._set_active(self.btn_gray, self.clean_mode == "gray")

    def _run_clean(self):
        self._snapshot_history()
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Clean", "Empty Pages selection.")
            return
        clean = None if self.clean_mode == "none" else (self.clean_mode, self.clean_strength)
        for i in indices:
            self._processed.setdefault(i, {})["clean"] = clean
        self._work_cache.clear()
        self._threaded_map(indices, self._work_image, lambda _r: self.render_page(), "Cleaning pages")

    def _threaded_map(self, indices, work_fn, on_done, title):
        if len(indices) <= 1:                        # multi-page ⇒ show progress (#12, #17)
            on_done({i: work_fn(i) for i in indices})
            return
        for i in indices:                            # render PyMuPDF rasters on the MAIN thread;
            self._source_image(i)                    # workers then touch only cached np/cv2 (inv.#10)
        self._busy = True
        self._set_controls_enabled(False)
        q: "queue.Queue" = queue.Queue()
        cancel = threading.Event()
        self.ov_cancel_evt = cancel
        total = len(indices)
        self._show_progress(title, total)

        def worker():
            res = {}
            for n, i in enumerate(indices):
                if cancel.is_set():
                    q.put(("cancel", None)); return
                try:
                    res[i] = work_fn(i)
                except Exception as exc:
                    q.put(("error", str(exc))); return
                q.put(("progress", n + 1))
            q.put(("done", res))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "progress":
                        self.ov_bar.set(payload / total)
                        self.ov_count.configure(text=f"{payload} / {total}")
                    elif kind == "cancel":
                        self._hide_progress(); self._finish_busy(); return
                    elif kind == "error":
                        self._hide_progress(); self._finish_busy()
                        messagebox.showerror(title, payload); return
                    elif kind == "done":
                        self._hide_progress(); self._finish_busy(); on_done(payload); return
            except queue.Empty:
                self.root.after(PROGRESS_POLL_MS, poll)

        poll()

    def _finish_busy(self):
        self._busy = False
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in (getattr(self, n, None) for n in
                  ("btn_apply", "btn_detect", "btn_dewarp", "btn_bw", "btn_gray")):
            if b is not None:
                try:
                    b.configure(state=state)
                except Exception:
                    pass

    # ════════════════════════════════════════════════════════════════════
    #  PAGES / RESIZE
    # ════════════════════════════════════════════════════════════════════
    def set_pages_mode(self, value: str):
        self.pages_mode = {"All": "all", "Odd": "odd", "Even": "even", "Selected": "select"}[value]
        self._sync_pages_ui()

    def _sync_pages_ui(self):
        if self.pages_mode == "select":
            self.select_row.pack(fill="x", pady=(8, 0))
        else:
            self.select_row.pack_forget()
        self.root.after_idle(self._reflow_bottom_bar)

    def _sync_resize_ui(self):
        if self.resize_var.get() == "Custom…":
            self.custom_row.pack(fill="x", pady=(8, 0))
        else:
            self.custom_row.pack_forget()
        self.root.after_idle(self._reflow_bottom_bar)

    def _target_size(self, w, h):
        val = self.resize_var.get()
        if val == RESOLUTIONS[0]:
            return w, h
        if val == "Custom…":
            cw, ch = float(self.custom_w.get()), float(self.custom_h.get())
            if cw <= 0 or ch <= 0:
                raise ValueError("Custom width/height must be positive numbers.")
            return cw, ch
        m = re.search(r"\((\d+)\D(\d+)\)", val)
        return (float(m.group(1)), float(m.group(2))) if m else (w, h)

    # ════════════════════════════════════════════════════════════════════
    #  APPLY / EXPORT / ROTATE
    # ════════════════════════════════════════════════════════════════════
    def _page_crop_boxes(self, i: int) -> List[Box]:
        """Crop box(es) for page i in page coords (split → N rects, auto → the crop rect)."""
        w, h = self._page_dims(i)
        if self.split_count > 1:
            return list(self.crop_rects)
        return [self._crop_rect(i) or Box(0, 0, w, h)]

    def apply_crop(self):
        if self._busy or self.page_count() == 0:
            return
        if self.split_count > 1 and len(self.crop_rects) != self.split_count:
            messagebox.showwarning("Apply Crop", f"Draw exactly {self.split_count} rectangle(s).")
            return
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Apply Crop", "Empty Pages selection.")
            return
        self._snapshot_history()
        for i in indices:                            # commit the crop state per page (#7, #13, #18)
            self._applied[i] = self._page_crop_boxes(i)
        self.render_page()
        self.status_msg(f"✓ Cropped {len(indices)} page(s). Export PDF to save.")

    def _output_images(self, i: int) -> List[Image.Image]:
        """Render page i to its committed output image(s); uncommitted pages export whole."""
        img = self._work_image(i)
        w, h = self._page_dims(i)
        sx, sy = img.width / w, img.height / h
        boxes = self._applied.get(i) or [Box(0, 0, w, h)]
        out = []
        for box in boxes:
            crop = img.crop((round(box.x0 * sx), round(box.y0 * sy),
                             round(box.x1 * sx), round(box.y1 * sy)))
            tw, th = self._target_size(box.width, box.height)
            if (round(tw), round(th)) != (crop.width, crop.height):
                crop = crop.resize((max(1, round(tw)), max(1, round(th))), Image.LANCZOS)
            out.append(crop)
        return out

    def save_pdf(self):
        if self._busy or self.page_count() == 0:
            return
        if not self._applied:                        # nothing committed yet → commit selection now
            indices = self._resolve_pages()
            if not indices:
                messagebox.showwarning("Export PDF", "Empty Pages selection.")
                return
            for i in indices:
                self._applied[i] = self._page_crop_boxes(i)
        suggested = "output_cropped.pdf"            # suggest <orig>_cropped.pdf (#10)
        if self._pdf_path:
            suggested = os.path.splitext(os.path.basename(self._pdf_path))[0] + "_cropped.pdf"
        path = filedialog.asksaveasfilename(title="Export PDF", defaultextension=".pdf",
                                            initialfile=suggested, filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        pages = list(range(self.page_count()))       # every page (committed = cropped, else whole)
        self._threaded_map(pages, self._output_images,
                           lambda res: self._write_pdf(path, pages, res), "Exporting pages")

    def _write_pdf(self, path, pages, results):
        try:
            out_doc = fitz.open()
            n = 0
            for i in pages:
                for img in results.get(i, []):
                    pg = out_doc.new_page(width=img.width, height=img.height)
                    pg.insert_image(pg.rect, stream=_pil_to_bytes(img))
                    n += 1
            out_doc.save(path, garbage=4, deflate=True)
            out_doc.close()
        except Exception as exc:
            messagebox.showerror("Export PDF", str(exc))
            return
        self.status_msg(f"✓ Exported {n} page(s).")
        messagebox.showinfo("Export PDF", f"Saved {n} page(s) to:\n{path}")

    def rotate_pages(self):
        if self._busy or self.page_count() == 0:
            return
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Rotate", "Empty Pages selection.")
            return
        self._snapshot_history()
        for i in indices:                            # angle-map rotate: undoable, works in scan mode
            w, h = self._page_dims(i)                # page size BEFORE this 90° step
            self._rotation[i] = (self._rotation.get(i, 0) + 90) % 360
            for d in (self._source_cache, self._work_cache):
                d.pop(i, None)                       # re-render at the new angle
            if i in self._applied:                   # carry the committed crop through the turn (#6)
                self._applied[i] = [rotate_box_cw(b, w, h) for b in self._applied[i]]
            if i in self._detect_cache:              # keep the detected content box too
                self._detect_cache[i] = rotate_box_cw(self._detect_cache[i], w, h)
        if self.auto_active and self._detect_cache:  # rebuild the live frame from rotated boxes
            self._union = union_box(list(self._detect_cache.values()))
            self._suspend = True                     # L/T/R/B map to rotated edges → reset to 0
            for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
                var.set(0.0)
            self._suspend = False
            self._sync_ratio_label()
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg(f"Rotated {len(indices)} page(s) 90° CW; crop preserved.")

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
                    dewarp=self.dewarp_on, clean=self.clean_mode, strength=self.clean_strength)

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
        self.dewarp_on, self.clean_mode, self.clean_strength = st["dewarp"], st["clean"], st["strength"]
        self._source_cache.clear()                   # rotation changed → re-render rasters
        self._work_cache.clear()
        self._refresh_scan_buttons()
        self._refresh_detect_enabled()
        self.strength_seg.set(str(self.clean_strength))
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
                  self._applied, self._rotation):    # full per-page reset incl. scan processing (#15)
            d.pop(idx, None)
        self.render_page()
        self.status_msg(f"Reset page {idx + 1} to original.")

    def delete_pages(self):
        """Delete the Pages selection from the document (#10)."""
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
            dewarp, rotation, detection) on the kept pages are preserved, not wiped (#8)."""
            return {o - sum(1 for x in idxs if x < o): v
                    for o, v in d.items() if o not in deleted}
        self._source_cache = _reindex(self._source_cache)
        self._work_cache = _reindex(self._work_cache)
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
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg(f"Deleted {len(idxs)} page(s). {self.page_count()} remain.")

    # ════════════════════════════════════════════════════════════════════
    #  NAV
    # ════════════════════════════════════════════════════════════════════
    def prev_page(self):
        if self.page_count() and self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.page_count() and self.current_page < self.page_count() - 1:
            self.current_page += 1
            self.render_page()

    def jump_to_page(self, _e=None):
        try:
            n = int(self.page_var.get())
        except ValueError:
            n = -1
        if 1 <= n <= self.page_count():
            self.current_page = n - 1
            self.render_page()
        else:
            self.page_var.set(str(self.current_page + 1))

    # ════════════════════════════════════════════════════════════════════
    #  SETTINGS / HELP
    # ════════════════════════════════════════════════════════════════════
    def _toplevel(self, title: str, width=620, height=None) -> ctk.CTkToplevel:
        win = ctk.CTkToplevel(self.root)
        win.title(title)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + 80
        y = self.root.winfo_rooty() + 20
        if height:
            win.geometry(f"{width}x{height}+{x}+{y}")
        else:
            win.geometry(f"+{x}+{y}")
        win.transient(self.root)
        win.after(60, win.lift)
        return win

    def open_settings(self):
        win = self._toplevel("Settings — SmartCrop PDF")
        ctk.CTkLabel(win, text="⚙  Settings", font=ctk.CTkFont(self.sys_font, 21, "bold")
                     ).pack(anchor="w", padx=24, pady=(20, 4))
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=(0, 8))

        def group(title):
            ctk.CTkLabel(body, text=title, font=self.font_title, anchor="w").pack(
                anchor="w", pady=(14, 4))

        def row(label):
            r = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=label, font=self.font_base, anchor="w", width=190).pack(
                side="left", padx=14, pady=10)
            return r

        def menu(label, var, values, cmd):
            ctk.CTkOptionMenu(row(label), variable=var, values=values, font=self.font_base,
                              fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                              button_hover_color=ACCENT, text_color=SECONDARY_TEXT,
                              width=110, command=cmd).pack(side="right", padx=14)

        group("Appearance")
        r = row("Colour scheme")
        seg = ctk.CTkSegmentedButton(r, values=["☀ Light", "🌙 Dark", "🖥 System"],
                                     font=self.font_base, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, fg_color=SEG_UNSEL,
                                     text_color=ACCENT_TEXT, command=self._set_theme)
        seg.set({"Light": "☀ Light", "Dark": "🌙 Dark", "System": "🖥 System"}[self.theme_choice.get()])
        seg.pack(side="right", padx=14)
        menu("Font size", self.font_size_var,
             ["12", "13", "14", "15", "16", "17", "18", "20", "22"], self._set_font_size)
        menu("Zoom (UI scale)", self.zoom_var,
             ["80%", "90%", "100%", "110%", "125%", "150%", "175%", "200%"], self._set_zoom)

        group("Output")
        r = row("Default resolution")
        ctk.CTkOptionMenu(r, variable=self.resize_var, values=list(RESOLUTIONS), font=self.font_base,
                          fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                          button_hover_color=ACCENT, text_color=SECONDARY_TEXT,
                          command=lambda _v: self._sync_resize_ui()).pack(side="right", padx=14)

        group("Behaviour")
        ctk.CTkSwitch(row("Confirm before overwrite"), text="", variable=self.confirm_overwrite,
                      progress_color=ACCENT).pack(side="right", padx=14)
        ctk.CTkSwitch(row("Remember last folder"), text="", variable=self.remember_folder,
                      progress_color=ACCENT).pack(side="right", padx=14)
        ctk.CTkEntry(row("Undo / redo depth"), textvariable=self.undo_depth_var, width=90,
                     font=self.font_base).pack(side="right", padx=14)

        group("Scan")
        for label, var in [("Dewarp supersample", self.dewarp_ss_var),
                           ("Worker threads", self.workers_var)]:
            ctk.CTkEntry(row(label), textvariable=var, width=90, font=self.font_base).pack(
                side="right", padx=14)
        win.update_idletasks()                         # size to content (CTk rejects geometry(""))
        h = body.winfo_y() + body.winfo_reqheight() + 18
        win.geometry(f"620x{h}")

    def _set_theme(self, value: str):
        name = {"☀ Light": "Light", "🌙 Dark": "Dark", "🖥 System": "System"}[value]
        self.theme_choice.set(name)
        ctk.set_appearance_mode(name)
        self.root.after(40, self.render_page)

    def open_help(self):
        win = self._toplevel("Help — SmartCrop PDF", width=680,
                             height=max(620, self.root.winfo_height()))
        ctk.CTkLabel(win, text="?  Help & Quick-Start",
                     font=ctk.CTkFont(self.sys_font, 22, "bold")).pack(
            anchor="w", padx=24, pady=(18, 0))
        ctk.CTkLabel(win, text="Crop, straighten, and clean PDFs and scans for e-readers.",
                     font=self.font_help, text_color=MUTED, anchor="w").pack(
            anchor="w", padx=24, pady=(2, 8))
        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        link_fg = ("#0F6CBD", "#4FA6E0")

        # Section blocks first, so the TOC buttons can scroll to them.
        blocks: Dict[str, ctk.CTkFrame] = {}
        for key, title, text in HELP_SECTIONS:
            blk = ctk.CTkFrame(body, fg_color="transparent")
            ctk.CTkLabel(blk, text=title, font=self.font_title, anchor="w").pack(anchor="w")
            ctk.CTkLabel(blk, text=text, font=self.font_help, justify="left", anchor="w",
                         wraplength=600).pack(anchor="w", pady=(2, 0))
            blocks[key] = blk

        toc = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
        ctk.CTkLabel(toc, text="Contents", font=self.font_title, anchor="w").pack(
            anchor="w", padx=12, pady=(8, 2))
        for key, title, _ in HELP_SECTIONS:
            ctk.CTkButton(toc, text=f"›  {title}", anchor="w", height=30, corner_radius=6,
                          fg_color="transparent", hover_color=SECONDARY_HOVER,
                          text_color=link_fg, font=self.font_help,
                          command=lambda k=key: self._scroll_to(body, blocks[k])).pack(
                fill="x", padx=8, pady=1)
        ctk.CTkLabel(toc, text="", height=4).pack()

        # Pack order: TOC at the top of the scroll area, then the section blocks.
        toc.pack(fill="x", pady=(0, 10))
        for key, _, _ in HELP_SECTIONS:
            blocks[key].pack(fill="x", padx=4, pady=(2, 10))

    def _scroll_to(self, scroll: ctk.CTkScrollableFrame, widget) -> None:
        scroll.update_idletasks()
        inner = widget.master                       # the scrollable inner frame (content)
        total = max(1, inner.winfo_height())
        y = widget.winfo_rooty() - inner.winfo_rooty()   # offset within content, scroll-stable
        scroll._parent_canvas.yview_moveto(max(0.0, min(1.0, y / total)))


def main() -> None:
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()

    def report_exception(exc, val, tb):              # never crash on a callback (#5)
        import traceback
        traceback.print_exception(exc, val, tb)
        try:
            messagebox.showerror("SmartCrop PDF", f"{exc.__name__}: {val}")
        except Exception:
            pass
    root.report_callback_exception = report_exception

    TestUIApp(root)
    root.mainloop()
