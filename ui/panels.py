"""Left-panel widget construction + refresh (spec §6/§7). Cards in the spec §6 layout order:
Document, Pages-to-Process, Scan Processing (scanned only), Split, Detect Text Borders, Advanced
(collapsed by default), Actions (Crop/Rotate/Delete), Output Quality, Export. Each card's refresh()
reads raw model properties + the window's busy flag; no business logic lives here — the handful
of commands that need a dialog (load/export/delete) are supplied as callbacks by app_window.py.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Literal

import customtkinter as ctk

from core.batch import BatchJob
from core.constants import COLOUR_MODES, DPI_PRESETS
from core.enums import FilterMode, Mode, PagesMode
from core.model import AppModel
from ui.constants import THEMES
from ui.ui_build import (
    Fonts,
    _seg_kwargs,
    card,
    export_split_button,
    highlight_button,
    labeled_row,
    offset_spinner,
    option_menu,
    set_active,
    set_entry_text,
    tooltip,
)

Dispatch = Callable[[Callable[[], None]], None]
DispatchJob = Callable[[Callable[[], BatchJob]], None]

_PAGES_LABELS: dict[PagesMode, str] = {
    PagesMode.ALL: "All", PagesMode.ODD: "Odd", PagesMode.EVEN: "Even",
    PagesMode.SELECT: "Selected",
}
_PAGES_BY_LABEL: dict[str, PagesMode] = {v: k for k, v in _PAGES_LABELS.items()}


@dataclass(frozen=True)
class PanelCallbacks:
    """The handful of commands that need more than a raw model call (a dialog or a confirm)."""
    dispatch: Dispatch
    dispatch_job: DispatchJob
    on_load_files: Callable[[], None]
    on_delete: Callable[[], None]
    on_export: Callable[[], None]
    on_pick_format: Callable[[str], None]


def _set_visible(widget: ctk.CTkBaseClass, visible: bool, **pack_opts: object) -> None:
    """Show/hide a packed widget without losing its position among siblings (pass `before=`/
    `after=` an always-present sibling so re-showing reinserts it in the right slot)."""
    mapped = bool(widget.winfo_manager())
    if visible and not mapped:
        widget.pack(**pack_opts)
    elif not visible and mapped:
        widget.pack_forget()


def _set_state(widgets: tuple[ctk.CTkBaseClass, ...], enabled: bool) -> None:
    state = "normal" if enabled else "disabled"
    for w in widgets:
        if w.cget("state") != state:
            w.configure(state=state)


class LeftPanel:
    def __init__(self, parent: ctk.CTkBaseClass, model: AppModel, fonts: Fonts,
                 callbacks: PanelCallbacks) -> None:
        self.model = model
        self.fonts = fonts
        self._cb = callbacks
        self.scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.scroll.pack(side="top", fill="both", expand=True)
        self._build_document()
        self._build_pages()
        self._build_scan()
        self._build_split()
        self._build_detect()
        self._build_advanced()
        self._build_actions()
        self._build_compress()
        self._build_export()
        self.refresh(busy=False)

    # ── Document & State (§7.1) ───────────────────────────────────────────────
    def _build_document(self) -> None:
        outer = ctk.CTkFrame(self.scroll, fg_color=THEMES["card"], border_width=1,
                              border_color=THEMES["card_border"], corner_radius=10)
        outer.pack(fill="x", pady=(0, 10))
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(head, text="Document & State", anchor="w", font=self.fonts.bold).pack(
            side="left")
        self.mode_badge = ctk.CTkLabel(head, text="", font=self.fonts.bold,
                                        fg_color=("#2D6E4E", "#1F5C3A"),
                                        text_color=("#FFFFFF", "#FFFFFF"),
                                        corner_radius=6)
        self.mode_badge.pack(side="right", padx=(16, 0))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_load = highlight_button(body, "Load PDF/Image Files",
                                          self._cb.on_load_files, self.fonts)
        self.btn_load.pack(fill="x")
        tooltip(self.btn_load, "Open one or many PDFs/images, combined in pick order (Ctrl+O)",
                self.fonts)

    def _refresh_document(self, busy: bool) -> None:
        scan = self.model.mode.value == "scanned"
        self.mode_badge.configure(
            text=self.model.mode.value.upper(), padx=8,
            fg_color=("#7A4D1D", "#7A3F10") if scan else ("#2D6E4E", "#1F5C3A"))
        _set_state((self.btn_load,), not busy)

    # ── Pages to Process (§7.5, §11) ──────────────────────────────────────────
    def _build_pages(self) -> None:
        outer, body = card(self.scroll, "Pages to Process", self.fonts)
        outer.pack(fill="x", pady=(0, 10))
        self.seg_pages = ctk.CTkSegmentedButton(
            body, values=list(_PAGES_BY_LABEL), font=self.fonts.base,
            command=lambda v: self._cb.dispatch(
                lambda: self.model.set_pages_mode(_PAGES_BY_LABEL[v])),
            **_seg_kwargs())
        self.seg_pages.pack(fill="x")
        tooltip(self.seg_pages, "Choose which pages actions apply to", self.fonts)
        self.pattern_row = ctk.CTkFrame(body, fg_color="transparent")
        ctk.CTkLabel(self.pattern_row, text="Pattern", font=self.fonts.base).pack(side="left")
        self.btn_current = highlight_button(self.pattern_row, "Current", self._toggle_current,
                                             self.fonts, width=84)
        self.btn_current.pack(side="right", padx=(0, 0))
        self.entry_pattern = ctk.CTkEntry(self.pattern_row, font=self.fonts.base)
        self.entry_pattern.pack(side="left", padx=(4, 4), fill="x", expand=True)
        self.entry_pattern.bind("<Return>", self._commit_pattern)
        self.entry_pattern.bind("<FocusOut>", self._commit_pattern)
        tooltip(self.entry_pattern, "1,3,5-9 or Python-style start:stop:step slices", self.fonts)
        tooltip(self.btn_current, "Follow the page you're viewing", self.fonts)

    def _commit_pattern(self, _event: object = None) -> None:
        self._cb.dispatch(lambda: self.model.set_select_pattern(self.entry_pattern.get()))

    def _toggle_current(self) -> None:
        self._cb.dispatch(lambda: self.model.set_current_follow(not self.model.current_follow))

    def _refresh_pages(self, busy: bool) -> None:
        m = self.model
        new_pages = _PAGES_LABELS[m.pages_mode]
        if self.seg_pages.get() != new_pages:
            # Suppress command= during programmatic set to prevent re-entrant dispatch (#14)
            self.seg_pages.configure(command=None)
            self.seg_pages.set(new_pages)
            self.seg_pages.configure(
                command=lambda v: self._cb.dispatch(
                    lambda: self.model.set_pages_mode(_PAGES_BY_LABEL[v])))
        show_pattern = m.pages_mode == PagesMode.SELECT
        _set_visible(self.pattern_row, show_pattern, fill="x", pady=(6, 0))
        if show_pattern:
            set_entry_text(self.entry_pattern, m.select_pattern)
        set_active(self.btn_current, m.current_follow)
        _set_state((self.seg_pages, self.btn_current, self.entry_pattern), not busy)

    # ── Scan Processing (§7.2, scanned mode only) ─────────────────────────────
    def _build_scan(self) -> None:
        self.scan_outer, body = card(self.scroll, "Scan Processing", self.fonts)
        self.btn_dewarp = highlight_button(
            body, "Dewarp & Deskew", lambda: self._cb.dispatch_job(self.model.run_dewarp),
            self.fonts)
        self.btn_dewarp.pack(fill="x")
        tooltip(self.btn_dewarp, "Straighten page curl and skew (idempotent from source)",
                self.fonts)
        filt_outer, filt_body = card(body, "Filter", self.fonts)
        filt_outer.pack(fill="x", pady=(8, 0))
        self._build_filter_buttons(filt_body)
        self._build_strength_row(filt_body)

    def _build_filter_buttons(self, parent: ctk.CTkBaseClass) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        self.btn_bw = highlight_button(
            row, "B/W", lambda: self._cb.dispatch_job(
                lambda: self.model.set_filter_mode(FilterMode.BW)), self.fonts)
        self.btn_bw.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tooltip(self.btn_bw, "Convert to pure black & white", self.fonts)
        self.btn_sharpen = highlight_button(
            row, "Sharpen", lambda: self._cb.dispatch_job(
                lambda: self.model.set_filter_mode(FilterMode.SHARPEN)), self.fonts)
        self.btn_sharpen.pack(side="left", fill="x", expand=True, padx=(4, 0))
        tooltip(self.btn_sharpen, "Flatten uneven lighting and sharpen; keeps gray tones",
                self.fonts)

    def _build_strength_row(self, parent: ctk.CTkBaseClass) -> None:
        ctk.CTkLabel(parent, text="Strength", font=self.fonts.base, anchor="w").pack(
            fill="x", pady=(6, 2))
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x")
        btn_row.columnconfigure((0, 1, 2), weight=1, uniform="str")
        self.strength_buttons: dict[int, ctk.CTkButton] = {}
        _strength_tips = {1: "Cautious", 2: "Default", 3: "Aggressive"}
        for col, n in enumerate((1, 2, 3)):
            b = highlight_button(btn_row, str(n), self._make_strength_handler(n), self.fonts)
            b.grid(row=0, column=col, sticky="ew", padx=(0, 4) if col < 2 else 0)
            tooltip(b, _strength_tips[n], self.fonts)
            self.strength_buttons[n] = b

    def _make_strength_handler(self, n: int) -> Callable[[], None]:
        return lambda: self._cb.dispatch_job(lambda: self.model.set_filter_strength(n))

    def _refresh_scan(self, busy: bool) -> None:
        m = self.model
        _set_visible(self.scan_outer, m.mode == Mode.SCANNED, fill="x", pady=(0, 10),
                     before=self.split_outer)
        # Use selection-based state: highlight only when every selected page has that processing
        set_active(self.btn_dewarp, m.selection_dewarp_on)
        sel_filter = m.selection_filter     # (mode, strength) or None
        fmode = sel_filter[0] if sel_filter else FilterMode.NONE
        fstrength = sel_filter[1] if sel_filter else m.filter_strength
        set_active(self.btn_bw, fmode == FilterMode.BW)
        set_active(self.btn_sharpen, fmode == FilterMode.SHARPEN)
        for n, btn in self.strength_buttons.items():
            set_active(btn, fstrength == n)
        _set_state((self.btn_dewarp, self.btn_bw, self.btn_sharpen), not busy)
        _set_state(tuple(self.strength_buttons.values()), not busy)  # always enabled (#13)

    # ── Split Each Page Into (§7.3, §9.6) + Keep ratio (§7.4, placed here per §6) ─────────
    def _build_split(self) -> None:
        self.split_outer, body = card(self.scroll, "Split Each Page Into", self.fonts)
        self.split_outer.pack(fill="x", pady=(0, 10))
        self.seg_split = ctk.CTkSegmentedButton(
            body, values=["1", "2", "4"],
            font=self.fonts.base,
            command=lambda v: self._cb.dispatch(lambda: self.model.set_split(int(v))),
            **_seg_kwargs())
        self.seg_split.set("1")
        self.seg_split.pack(fill="x")
        # Tooltip after widget creation (#2) — was incorrectly placed before in prior version
        tooltip(self.seg_split, "Split each source page into 1, 2, or 4 output pages", self.fonts)
        self._build_same_size_row(body)
        self._build_keep_ratio_row(body)

    def _build_same_size_row(self, parent: ctk.CTkBaseClass) -> None:
        self.same_size_row = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(self.same_size_row, text="Same size", anchor="w", font=self.fonts.base,
                     width=120).pack(side="left")
        self._same_size_var = tk.BooleanVar(value=self.model.same_size)
        self.switch_same_size = ctk.CTkSwitch(
            self.same_size_row, text="", variable=self._same_size_var, font=self.fonts.base,
            command=lambda: self._cb.dispatch(
                lambda: self.model.set_same_size(bool(self._same_size_var.get()))))
        self.switch_same_size.pack(side="left")
        tooltip(self.switch_same_size, "Keep all split windows the same dimensions", self.fonts)

    def _build_keep_ratio_row(self, parent: ctk.CTkBaseClass) -> None:
        self.keep_ratio_row = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(self.keep_ratio_row, text="Keep ratio", anchor="w", font=self.fonts.base,
                     width=120).pack(side="left")
        self._keep_ratio_var = tk.BooleanVar(value=self.model.keep_ratio)
        self.switch_keep_ratio = ctk.CTkSwitch(
            self.keep_ratio_row, text="", variable=self._keep_ratio_var, font=self.fonts.base,
            command=self._on_keep_ratio_toggle)
        self.switch_keep_ratio.pack(side="left")
        tooltip(self.switch_keep_ratio, "Lock crop height to width ÷ ratio", self.fonts)
        self.entry_ratio = ctk.CTkEntry(self.keep_ratio_row, width=70, font=self.fonts.base)
        self.entry_ratio.pack(side="left", padx=(6, 0))
        self.entry_ratio.bind("<Return>", self._commit_ratio)
        self.entry_ratio.bind("<FocusOut>", self._commit_ratio)
        tooltip(self.entry_ratio, "Aspect ratio (width / height); editable", self.fonts)
        self.keep_ratio_row.pack(fill="x", pady=(6, 0))

    def _on_keep_ratio_toggle(self) -> None:
        on = bool(self._keep_ratio_var.get())
        ratio = self._typed_ratio()
        self._cb.dispatch(lambda: self.model.set_keep_ratio(on, ratio))

    def _commit_ratio(self, _event: object = None) -> None:
        ratio = self._typed_ratio()
        if ratio is not None:
            self._cb.dispatch(lambda: self.model.set_keep_ratio(self.model.keep_ratio, ratio))

    def _typed_ratio(self) -> float | None:
        try:
            v = float(self.entry_ratio.get())
        except ValueError:
            return None
        return v if v > 0 else None

    def _refresh_split(self, busy: bool) -> None:
        m = self.model
        new_split = str(m.split_count) if m.split_count in (1, 2, 4) else "1"
        if self.seg_split.get() != new_split:
            # Suppress command= during programmatic set to prevent re-entrant dispatch (#14)
            self.seg_split.configure(command=None)
            self.seg_split.set(new_split)
            self.seg_split.configure(
                command=lambda v: self._cb.dispatch(lambda: self.model.set_split(int(v))))
        _set_visible(self.same_size_row, m.split_count in (2, 4), fill="x", pady=(6, 0),
                     before=self.keep_ratio_row)
        self._same_size_var.set(m.same_size)
        self._keep_ratio_var.set(m.keep_ratio)
        ratio_val = m.ratio if m.ratio is not None else m.default_ratio
        set_entry_text(self.entry_ratio, f"{ratio_val:.3f}" if ratio_val else "")
        _set_state((self.seg_split, self.switch_same_size, self.switch_keep_ratio,
                    self.entry_ratio), not busy)

    # ── Detect Text Borders (§7.4, §8) ────────────────────────────────────────
    def _build_detect(self) -> None:
        outer, body = card(self.scroll, "Detect Text Borders", self.fonts)
        outer.pack(fill="x", pady=(0, 10))
        self.btn_detect = highlight_button(
            body, "✦  Auto-detect",
            lambda: self._cb.dispatch_job(self.model.detect_content), self.fonts)
        self.btn_detect.pack(fill="x")
        tooltip(self.btn_detect, "Detect each page's content box over the Pages selection",
                self.fonts)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self._anchor_left_var = tk.BooleanVar(value=self.model.anchor_left)
        self.switch_anchor_left = ctk.CTkSwitch(
            row, text="Anchor Left", variable=self._anchor_left_var,
            font=self.fonts.base, progress_color=THEMES["accent"],
            command=lambda: self._cb.dispatch(
                lambda: self.model.set_anchor(left=bool(self._anchor_left_var.get()))))
        self.switch_anchor_left.pack(side="left", padx=(0, 16))
        tooltip(self.switch_anchor_left, "Pin the left crop edge to each page's own content",
                self.fonts)
        self._anchor_top_var = tk.BooleanVar(value=self.model.anchor_top)
        self.switch_anchor_top = ctk.CTkSwitch(
            row, text="Anchor Top", variable=self._anchor_top_var,
            font=self.fonts.base, progress_color=THEMES["accent"],
            command=lambda: self._cb.dispatch(
                lambda: self.model.set_anchor(top=bool(self._anchor_top_var.get()))))
        self.switch_anchor_top.pack(side="left")
        tooltip(self.switch_anchor_top, "Pin the top crop edge to each page's own content",
                self.fonts)

    def _refresh_detect(self, busy: bool) -> None:
        m = self.model
        self.btn_detect.configure(state="normal" if (m.can_detect and not busy) else "disabled")
        self._anchor_left_var.set(m.anchor_left)
        self._anchor_top_var.set(m.anchor_top)
        _set_state((self.switch_anchor_left, self.switch_anchor_top), not busy)

    # ── Advanced — offsets (§7.4a, collapsible) ───────────────────────────────
    def _build_advanced(self) -> None:
        self.advanced_open = False
        outer = ctk.CTkFrame(self.scroll, fg_color=THEMES["card"], border_width=1,
                              border_color=THEMES["card_border"], corner_radius=10)
        outer.pack(fill="x", pady=(0, 10))
        self.btn_advanced = ctk.CTkButton(
            outer, text="▶ Advanced", anchor="w", font=self.fonts.bold,
            fg_color="transparent", hover_color=THEMES["secondary_hover"],
            text_color=THEMES["secondary_text"], command=self._toggle_advanced)
        self.btn_advanced.pack(fill="x", padx=12, pady=(10, 2))
        tooltip(self.btn_advanced, "Fine-tune crop edges by percentage offset", self.fonts)
        self.advanced_body = ctk.CTkFrame(outer, fg_color="transparent")
        ctk.CTkLabel(self.advanced_body, text="Set offsets", anchor="w",
                     text_color=THEMES["muted"],
                     font=self.fonts.base).pack(fill="x", pady=(0, 4))
        offsets_row = ctk.CTkFrame(self.advanced_body, fg_color="transparent")
        offsets_row.pack(fill="x")
        self.offset_entries: dict[str, ctk.CTkEntry] = {}
        edges: tuple[Literal["L", "T", "R", "B"], ...] = ("L", "T", "R", "B")
        for i, edge in enumerate(edges):
            frame, entry = self._build_offset_spinner(offsets_row, edge)
            frame.pack(side="left", padx=(0, 3) if i < 3 else 0)
            self.offset_entries[edge] = entry

    def _build_offset_spinner(
            self, parent: ctk.CTkBaseClass,
            edge: Literal["L", "T", "R", "B"]) -> tuple[ctk.CTkFrame, ctk.CTkEntry]:
        field = {"L": "left", "T": "top", "R": "right", "B": "bottom"}[edge]
        start = getattr(self.model.offsets, field)

        def _commit(value: float) -> None:
            def _do() -> None:
                self.model.set_offset(edge, value)
                self.model.commit_offsets()
            self._cb.dispatch(_do)

        frame, entry = offset_spinner(parent, edge, start, _commit, self.fonts)
        tooltip(entry, f"{field.capitalize()} offset — positive shrinks, negative expands (%)",
                self.fonts)
        return frame, entry

    def _toggle_advanced(self) -> None:
        self.advanced_open = not self.advanced_open
        arrow = "▼" if self.advanced_open else "▶"
        self.btn_advanced.configure(text=f"{arrow} Advanced")
        _set_visible(self.advanced_body, self.advanced_open, fill="x", padx=12, pady=(0, 12))

    def _refresh_advanced(self, busy: bool) -> None:
        o = self.model.offsets
        for edge, val in (("L", o.left), ("T", o.top), ("R", o.right), ("B", o.bottom)):
            set_entry_text(self.offset_entries[edge], f"{val:.1f}")
        _set_state(tuple(self.offset_entries.values()), not busy)

    # ── Actions: Crop / Rotate / Delete (§7.7) ────────────────────────────────
    def _build_actions(self) -> None:
        outer, body = card(self.scroll, "Actions", self.fonts)
        outer.pack(fill="x", pady=(0, 10))
        self.btn_crop = highlight_button(
            body, "✂  Crop",
            lambda: self._cb.dispatch(self.model.apply_crop), self.fonts)
        self.btn_crop.pack(fill="x")
        tooltip(self.btn_crop, "Commit and show the crop (Ctrl+Enter)", self.fonts)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.btn_rotate = highlight_button(
            row, "↻  Rotate",
            lambda: self._cb.dispatch(self.model.rotate_pages), self.fonts)
        self.btn_rotate.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tooltip(self.btn_rotate, "Rotate the Pages selection 90° CW", self.fonts)
        self.btn_delete = highlight_button(
            row, "🗑  Delete", self._cb.on_delete, self.fonts)
        self.btn_delete.pack(side="left", fill="x", expand=True, padx=(4, 0))
        tooltip(self.btn_delete, "Delete the Pages selection", self.fonts)

    def _refresh_actions(self, busy: bool) -> None:
        m = self.model
        self.btn_crop.configure(text="✂  Split & Crop" if m.split_count in (2, 4) else "✂  Crop")
        self.btn_crop.configure(state="normal" if (m.can_apply and not busy) else "disabled")
        enabled = m.has_document and not busy
        _set_state((self.btn_rotate, self.btn_delete), enabled)

    # ── Output Quality (§7.6) ─────────────────────────────────────────────────
    def _build_compress(self) -> None:
        outer, body = card(self.scroll, "Output Quality", self.fonts)
        outer.pack(fill="x", pady=(0, 10))
        row = labeled_row(body, "Compress to", self.fonts)
        self.menu_compress = option_menu(
            row, self.fonts, values=list(DPI_PRESETS), width=140,
            command=lambda v: self._cb.dispatch(lambda: self.model.set_compress_preset(v)))
        self.menu_compress.pack(side="right")
        tooltip(self.menu_compress, "Resample output to a target DPI — reduces file size",
                self.fonts)
        row.pack(fill="x", pady=4)
        row = labeled_row(body, "Colour", self.fonts)
        self.menu_colours = option_menu(
            row, self.fonts, values=COLOUR_MODES, width=140,
            command=lambda v: self._cb.dispatch(lambda: self.model.set_output_colours(v)))
        self.menu_colours.pack(side="right")
        tooltip(self.menu_colours, "Output colour space: Original or Grayscale", self.fonts)
        row.pack(fill="x", pady=4)

    def _refresh_compress(self, busy: bool) -> None:
        m = self.model
        self.menu_compress.set(m.compress_preset)
        self.menu_colours.set(m.output_colours)
        _set_state((self.menu_compress, self.menu_colours), not busy)

    # ── Export (§7.7a, §12.7) ─────────────────────────────────────────────────
    def _build_export(self) -> None:
        outer, body = card(self.scroll, "Export", self.fonts)
        outer.pack(fill="x")
        self.export_frame, self.btn_export, self.menu_format = export_split_button(
            body, self.model.export_format, self.fonts, self._cb.on_export,
            self._cb.on_pick_format)
        self.export_frame.pack(fill="x")
        tooltip(self.btn_export, "Export in the chosen format (Ctrl+S)", self.fonts)

    def _refresh_export(self, busy: bool) -> None:
        m = self.model
        self.btn_export.configure(text=f"💾  Export {m.export_format}")
        self.menu_format.set(m.export_format)
        enabled = m.has_document and not busy
        _set_state((self.btn_export, self.menu_format), enabled)

    # ── aggregate refresh (ARCHITECTURE §3: AppWindow.refresh_all -> panel.refresh) ──────────
    def refresh_pages(self, busy: bool) -> None:
        """Fast-path for navigation: only the pages section tracks current page position."""
        self._refresh_pages(busy)

    def refresh(self, busy: bool) -> None:
        self._refresh_document(busy)
        self._refresh_pages(busy)
        self._refresh_scan(busy)
        self._refresh_split(busy)
        self._refresh_detect(busy)
        self._refresh_advanced(busy)
        self._refresh_actions(busy)
        self._refresh_compress(busy)
        self._refresh_export(busy)