"""UI construction for SmartCrop PDF: every CustomTkinter widget, the left control
stack, the Settings and Help windows, and the in-canvas progress overlay. Mixed into
SmartCropApp — pure layout, no document logic. See core/app.py for the orchestration class.
"""
from __future__ import annotations

from typing import Dict

import tkinter as tk
import customtkinter as ctk

from core.constants import (DPI_PRESETS, COLOUR_MODES, EXPORT_FORMATS, PANEL_WIDTH,
                            SETTINGS_MIN_W)
from core.enums import FilterMode
from core.theme import (ACCENT, ACCENT_HOVER, ACCENT_TEXT, CARD, CARD_BORDER, MUTED,
                        SECONDARY, SECONDARY_HOVER, SECONDARY_TEXT, SEG_UNSEL, STATUS_FG)
from core.help_content import HELP_SECTIONS, OFFSET_TIP, SPLIT_TIP
from core.widgets import ToolTip, Spin


class UIBuildMixin:
    """Widget construction for SmartCropApp (no state of its own)."""

    def _build_ui(self) -> None:
        t = self._theme()
        self.paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=8, bd=0,
                                    bg=t["SASH"], sashrelief="flat")
        self.paned.pack(fill="both", expand=True, padx=10, pady=10)

        left = ctk.CTkFrame(self.paned, fg_color="transparent", width=PANEL_WIDTH)
        left.pack_propagate(False)                    # hold the panel width
        self._left_panel = left
        self.paned.add(left, minsize=380, stretch="never", width=PANEL_WIDTH)
        # Settings/Help + nav is pinned to the panel bottom (packed first, side=bottom) so it
        # is always visible when there is room and never floats directly under Export or needs
        # scrolling to reach. The scrollable control stack fills the space above it.
        self._build_bottom_bar(left)
        self.controls = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.controls.pack(side="top", fill="both", expand=True)

        self._build_doc_section()
        self._build_pages_section()      # scope declared once, near the top (§6)
        self._build_scan_section()
        self._build_split_section()
        self._build_detect_section()
        self._build_advanced_section()   # collapsible offsets, separate from Detect (§7.4a)
        self._build_actions_section()    # Crop / Rotate / Delete, after the crop setup (§6, §7.7)
        self._build_compress_section()
        self._build_export_section()     # Export split button in its own row (§6, §7.7a)

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
        # Wheel turns pages — never magnifies (the page is always fit-to-window, §5).
        self.canvas.bind("<MouseWheel>", self._on_canvas_wheel)                 # Windows / macOS
        self.canvas.bind("<Button-4>", lambda _e: self._on_canvas_wheel(type("E", (), {"delta": 1})()))
        self.canvas.bind("<Button-5>", lambda _e: self._on_canvas_wheel(type("E", (), {"delta": -1})()))
        self.canvas.bind("<ButtonPress-3>", self._cancel_drag)   # right-click cancels a drag (§9.3)
        self.root.bind("<Escape>", self._cancel_drag)            # Esc cancels a drag (§9.3, §21)

        self.status = ctk.CTkLabel(right, text="", text_color=STATUS_FG, justify="right",
                                   font=ctk.CTkFont(self.sys_mono, self.fs - 1),
                                   fg_color=CARD, corner_radius=6)
        self.status.place(relx=1.0, rely=1.0, x=-12, y=-10, anchor="se")
        self._build_overlay(right)
        self._refresh_mode_badge()
        self._sync_split_ui()
        self._sync_pages_ui()

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
        # _set_active. `primary` kept for call-site intent but no longer fills.
        kw.setdefault("height", 36)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", CARD_BORDER)
        return ctk.CTkButton(master, text=text, command=cmd, fg_color=SECONDARY,
                             hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT,
                             font=self.font_base, corner_radius=8, **kw)

    def _set_active(self, btn, on: bool):
        """Highlight a button only while it represents an active state."""
        btn.configure(fg_color=ACCENT if on else SECONDARY,
                      text_color=ACCENT_TEXT if on else SECONDARY_TEXT,
                      hover_color=ACCENT_HOVER if on else SECONDARY_HOVER)

    def _seg_tips(self, seg: ctk.CTkSegmentedButton, mapping: Dict[str, str]):
        for val, btn in getattr(seg, "_buttons_dict", {}).items():
            if val in mapping:
                ToolTip(btn, mapping[val], self)

    def _build_bottom_bar(self, parent) -> None:
        # Pinned to the bottom of the left panel, outside the scroll area: always visible,
        # never a floating duplicate below Export, never needs scrolling to reach.
        bar = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1,
                           border_color=CARD_BORDER)
        bar.pack(side="bottom", fill="x", padx=4, pady=(6, 2))
        self._nav_bar = bar
        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(10, 4))
        bs = self._btn(row1, "⚙  Settings", self.open_settings)
        bs.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ToolTip(bs, "Appearance, output, behaviour and scan settings.", self)
        bh = self._btn(row1, "?  Help", self.open_help)
        bh.pack(side="left", expand=True, fill="x", padx=(4, 0))
        ToolTip(bh, "Quick-start guide with an interactive table of contents.", self)
        # Undo / Redo / Reset, pinned directly below Settings/Help (§7.8). Each leads with its
        # glyph so the *word* is never the char nearest the rounded border (the Redo-label rule).
        rowh = ctk.CTkFrame(bar, fg_color="transparent")
        rowh.pack(fill="x", padx=10, pady=(0, 4))
        rowh.columnconfigure((0, 1, 2), weight=1, uniform="urr")
        self.btn_undo = bu = self._btn(rowh, "↩ Undo", self.undo)
        bu.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(bu, "Undo (Ctrl+Z).", self)
        self.btn_redo = br = self._btn(rowh, "↪ Redo", self.redo)
        br.grid(row=0, column=1, sticky="ew", padx=4)
        ToolTip(br, "Redo (Ctrl+Y).", self)
        self.btn_reset = brs = self._btn(rowh, "⟲ Reset", self.reset_document)
        brs.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        ToolTip(brs, "Re-open the whole document from its source files (§13).", self)
        # Page nav: arrows hug the edges, the page box gets the middle space so the
        # current/total page numbers stay fully visible up to 4 digits.
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

    def _build_doc_section(self) -> None:
        def badge(head):
            # A detection *marker*, not a button: same pill look, but not interactive.
            self.mode_badge = ctk.CTkLabel(head, text="NORMAL", font=self.font_badge,
                                           corner_radius=11, width=88, height=26,
                                           text_color="white")
            self.mode_badge.pack(side="right", padx=(16, 0))     # gap after the title
            ToolTip(self.mode_badge, "Detected document mode (Normal = vector, "
                    "Scanned = raster). Set automatically on load.", self)
        body = self._card("Document & State", badge)
        bl = self._btn(body, "\U0001F4C2   Load Files", self.load_files, primary=True, height=40)
        bl.pack(fill="x", pady=(2, 8))
        ToolTip(bl, "Open one or many PDFs and/or images (Ctrl+O); they combine into one document "
                "in selection order. Classifies Normal vs Scanned automatically.", self)

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
        filt = ctk.CTkFrame(body, fg_color="transparent", border_width=1,
                            border_color=CARD_BORDER, corner_radius=10)
        filt.pack(fill="x")
        ctk.CTkLabel(filt, text="Filter", font=self.font_title, anchor="w").pack(
            anchor="w", padx=12, pady=(10, 4))
        crow = ctk.CTkFrame(filt, fg_color="transparent")
        crow.pack(fill="x", padx=12)
        crow.columnconfigure((0, 1), weight=1)
        self.btn_bw = self._btn(crow, "B/W", lambda: self.set_filter_mode(FilterMode.BW))
        self.btn_bw.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_bw, "B/W filter — bilevel black/white threshold. Press again to turn off.", self)
        self.btn_sharpen = self._btn(crow, "Sharpen", lambda: self.set_filter_mode(FilterMode.SHARPEN))
        self.btn_sharpen.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(self.btn_sharpen, "Sharpen filter — flatten + denoise + unsharp, keeps continuous "
                "tone. Mutually exclusive with B/W.", self)
        ctk.CTkLabel(filt, text="Strength", font=self.font_title, anchor="w").pack(
            anchor="w", padx=12, pady=(8, 2))
        self.strength_seg = ctk.CTkSegmentedButton(
            filt, values=["1", "2", "3"], font=self.font_base,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=SEG_UNSEL, text_color=ACCENT_TEXT,
            command=lambda v: self.set_filter_strength(int(v)))
        self.strength_seg.set("2")
        self.strength_seg.pack(fill="x", padx=12, pady=(0, 12))
        self._seg_tips(self.strength_seg, {v: f"Strength {v} — "
                       f"{['cautious', 'normal', 'aggressive'][i]} filtering."
                       for i, v in enumerate(["1", "2", "3"])})

    def _build_split_section(self) -> None:
        body = self._card("Split Each Page Into")
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
        body = self._card("Detect Text Borders")
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

    def _build_advanced_section(self) -> None:
        # Collapsible Advanced card holding the per-edge offsets, separate from Detect Text Borders
        # and collapsed by default (§7.4a). The arrow only hides/shows the fields; the offsets keep
        # driving the live crop whether the card is open or closed.
        card = ctk.CTkFrame(self.controls, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=CARD_BORDER)
        card.pack(fill="x", padx=4, pady=6)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 2))
        self.advanced_open = False
        self.btn_advanced = ctk.CTkButton(head, text="▸ Advanced", anchor="w", height=26,
                                          fg_color="transparent", hover_color=SECONDARY_HOVER,
                                          text_color=SECONDARY_TEXT, font=self.font_title,
                                          command=self._toggle_advanced)
        self.btn_advanced.pack(side="left")
        self.advanced_body = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.advanced_body, text="Set offsets  ↳", font=self.font_base,
                     text_color=MUTED, anchor="w").pack(anchor="w", padx=14, pady=(0, 2))
        grid = ctk.CTkFrame(self.advanced_body, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 12))
        grid.columnconfigure((0, 1, 2, 3), weight=1, uniform="off")
        self._off_spins = []
        for col, (lab, var) in enumerate([("L", self.left_off), ("T", self.top_off),
                                          ("R", self.right_off), ("B", self.bottom_off)]):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(cell, text=lab, font=self.font_base, text_color=MUTED,
                         width=14).pack(side="left", padx=(0, 4))
            sp = Spin(cell, var, self, width=48)
            sp.pack(side="left", fill="x", expand=True)
            ToolTip(sp.entry, OFFSET_TIP[lab], self)
            sp.entry.bind("<FocusOut>", self._clamp_offsets, add="+")   # snap to page limits
            sp.entry.bind("<Return>", self._clamp_offsets, add="+")
            self._off_spins.append(sp)
        for var in (self.left_off, self.top_off, self.bottom_off):
            var.trace_add("write", lambda *_: self._on_offset_change())
        self.right_off.trace_add("write", lambda *_: self._on_right_change())

    def _toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        self.btn_advanced.configure(text="▾ Advanced" if self.advanced_open else "▸ Advanced")
        if self.advanced_open:
            self.advanced_body.pack(fill="x")
        else:
            self.advanced_body.pack_forget()

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
        body = self._card("Pages to Process")
        self.pages_card = body.master                # Scan Processing packs after this card (§6)
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
        # Styled like the Selected segment (blue highlight when active), no circle glyph.
        self.btn_current = self._btn(self.select_row, "Current", self._select_current,
                                     width=96, height=30)
        self.btn_current.pack(side="right", padx=(8, 0))
        ToolTip(self.btn_current, "Follow the current page: fills Pattern with the page you are "
                "on and keeps it updated as you navigate. Highlights while active; click again "
                "(or edit Pattern) to stop.", self)
        se = ctk.CTkEntry(self.select_row, textvariable=self.select_var, font=self.font_mono)
        se.pack(side="left", fill="x", expand=True, padx=(8, 0))
        se.bind("<Key>", self._on_pattern_typed, add="+")     # a manual edit ends follow mode
        ToolTip(se, "Pages 1,3,5-9,12 — commas, ranges (a-b) and slices (a:b) accepted.", self)

    def _select_current(self):
        """Toggle 'follow current page': ON switches to Selected, fills Pattern with the
        current page and keeps it synced while navigating (button highlighted); OFF leaves
        the pattern untouched and unhighlights."""
        self.current_follow = not self.current_follow
        if self.current_follow:
            self.set_pages_mode("Selected")                   # also lights the Selected segment
            self.select_var.set(str(self.current_page + 1))
        self._refresh_current_btn()
        self.render_page()

    def _on_pattern_typed(self, _e=None):
        if self.current_follow:                               # typing a pattern ends follow mode
            self.current_follow = False
            self._refresh_current_btn()

    def _refresh_current_btn(self):
        if hasattr(self, "btn_current"):
            self._set_active(self.btn_current, self.current_follow)

    def _build_compress_section(self) -> None:
        body = self._card("Compress Document")
        dpi = ctk.CTkOptionMenu(body, variable=self.compress_var, values=list(DPI_PRESETS),
                                command=lambda _v: self.render_page(), font=self.font_base,
                                fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                                button_hover_color=ACCENT, text_color=SECONDARY_TEXT)
        dpi.pack(fill="x")
        ToolTip(dpi, "Resample every output image to this DPI, applied last (after crop). "
                "Original resolution keeps native crop pixels.", self)
        col = ctk.CTkOptionMenu(body, variable=self.colours_var, values=list(COLOUR_MODES),
                                command=lambda _v: self.render_page(), font=self.font_base,
                                fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                                button_hover_color=ACCENT, text_color=SECONDARY_TEXT)
        col.pack(fill="x", pady=(8, 0))
        ToolTip(col, "Grayscale desaturates every output page (tone kept, no thresholding); "
                "Original colors leaves each page untouched.", self)

    def _build_actions_section(self) -> None:
        body = self._card("Actions")
        self.btn_apply = self._btn(body, "✂   Crop", self.apply_crop, primary=True, height=44)
        self.btn_apply.pack(fill="x")                 # one full-width action button (§7.7)
        ToolTip(self.btn_apply, "Apply the crop to the Pages selection (Ctrl+Enter).", self)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        row.columnconfigure((0, 1), weight=1, uniform="act")
        brot = self._btn(row, "↻  Rotate", self.rotate_pages, height=42)
        brot.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(brot, "Rotate the Pages selection 90° CW; the filter survives rotation.", self)
        bdel = self._btn(row, "🗑  Delete", self.delete_pages, height=42)
        bdel.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(bdel, "Delete the Pages selection from the document.", self)

    def _build_export_section(self) -> None:
        body = ctk.CTkFrame(self.controls, fg_color="transparent")
        body.pack(fill="x", padx=4, pady=(2, 10))
        # Export split button: main face exports the current format; the ▾ menu picks it (§7.7a).
        exrow = ctk.CTkFrame(body, fg_color="transparent")
        exrow.pack(fill="x")
        self.btn_export = self._btn(exrow, f"\U0001F4BE   Export {self.format_var.get()}",
                                    self.export, primary=True, height=44)
        self.btn_export.pack(side="left", fill="x", expand=True)
        ToolTip(self.btn_export, "Export the document in the chosen format (Ctrl+S).", self)
        self.export_fmt = ctk.CTkOptionMenu(exrow, values=list(EXPORT_FORMATS), width=72, height=44,
                                            variable=self.format_var, command=self._on_format_change,
                                            font=self.font_base, fg_color=SECONDARY,
                                            button_color=SECONDARY_HOVER, button_hover_color=ACCENT,
                                            text_color=SECONDARY_TEXT)
        self.export_fmt.pack(side="left", padx=(6, 0))
        ToolTip(self.export_fmt, "Choose the export format: PDF · JPG · PNG · TIFF.", self)

    def _on_format_change(self, fmt: str) -> None:
        self.format_var.set(fmt)
        self.btn_export.configure(text=f"\U0001F4BE   Export {fmt}")

    def _pick_output_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Output folder")
        if folder:
            self.output_folder_var.set(folder)

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
        self._btn(self.overlay, "Cancel", self._cancel_progress).pack(pady=(6, 20), padx=28)

    def _show_progress(self, title, total):
        self.ov_title.configure(text=f"{title}…")
        self.ov_bar.set(0)
        self.ov_count.configure(text=f"0 / {total}")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.overlay.lift()
        # Lay out + flush idle redraws, then a full update() so the overlay is FULLY painted —
        # never partially — before the first heavy page (§14). update_idletasks alone leaves a
        # freshly-placed CTk overlay half-drawn on some platforms.
        self.root.update_idletasks()
        try:
            self.root.update()
        except Exception:
            pass

    def _cancel_progress(self):
        self._cancelled = True                        # checked between pages by _run_batch

    def _hide_progress(self):
        self.overlay.place_forget()


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
            # No fixed label width: the label sizes to its text so it is never clipped at any
            # Font-size step (§15, §19); the window's reqwidth (below) grows to fit it.
            ctk.CTkLabel(r, text=label, font=self.font_base, anchor="w").pack(
                side="left", padx=14, pady=10)
            return r

        def menu(label, var, values, cmd):
            # dynamic_resizing (CTk default) grows the menu to fit the longest value, so long
            # presets like "Original resolution" / "Medium — 150 dpi" are never clipped.
            ctk.CTkOptionMenu(row(label), variable=var, values=values, font=self.font_base,
                              fg_color=SECONDARY, button_color=SECONDARY_HOVER,
                              button_hover_color=ACCENT, text_color=SECONDARY_TEXT,
                              width=160, command=cmd).pack(side="right", padx=14)

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
        menu("Compress to", self.compress_var, list(DPI_PRESETS),
             lambda _v: self.render_page())
        menu("Default format", self.format_var, list(EXPORT_FORMATS), self._on_format_change)
        fr = row("Output folder")
        self._btn(fr, "…", self._pick_output_folder, width=40, height=30).pack(
            side="right", padx=(0, 14))
        ctk.CTkEntry(fr, textvariable=self.output_folder_var, font=self.font_base,
                     placeholder_text="same as source").pack(side="right", fill="x",
                                                              expand=True, padx=(0, 6), pady=8)
        ctk.CTkEntry(row("Output postfix"), textvariable=self.output_postfix_var, width=110,
                     font=self.font_base).pack(side="right", padx=14)

        group("Behaviour")
        ctk.CTkSwitch(row("Confirm before overwrite"), text="", variable=self.confirm_overwrite,
                      progress_color=ACCENT).pack(side="right", padx=14)
        ctk.CTkSwitch(row("Remember last folder"), text="", variable=self.remember_folder,
                      progress_color=ACCENT).pack(side="right", padx=14)
        ctk.CTkEntry(row("Undo / redo depth"), textvariable=self.undo_depth_var, width=90,
                     font=self.font_base).pack(side="right", padx=14)

        group("Scan")
        ctk.CTkEntry(row("Dewarp supersample"), textvariable=self.dewarp_ss_var, width=90,
                     font=self.font_base).pack(side="right", padx=14)
        # Size to the content's intrinsic request in BOTH axes (CTk rejects geometry("")), so a
        # larger Font size or high OS-DPI scaling grows the window instead of clipping rows. The
        # minsize keeps the content from being squeezed; the window can still grow.
        win.update_idletasks()
        w = max(SETTINGS_MIN_W, body.winfo_reqwidth() + 40)
        h = body.winfo_y() + body.winfo_reqheight() + 18
        win.geometry(f"{w}x{h}")
        win.minsize(w, h)

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


