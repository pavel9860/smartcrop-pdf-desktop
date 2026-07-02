"""Widget construction helpers — build separate from logic."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog

import customtkinter as ctk

from core.batch import BatchJob
from core.constants import DPI_PRESETS, EXPORT_FORMATS
from core.settings import Settings
from ui.config import UIConfig
from ui.constants import (
    FONT_SIZE_MAX,
    FONT_SIZE_MIN,
    OFFSET_FIELD_W,
    THEMES,
    UI_SCALE_MAX,
    UI_SCALE_MIN,
)
from ui.help_content import INTRO, SECTIONS


class Fonts:
    def __init__(self, base_size: int) -> None:
        self.base = ctk.CTkFont(size=base_size)
        self.bold = ctk.CTkFont(size=base_size, weight="bold")
        self.title = ctk.CTkFont(size=base_size, weight="bold")
        self.help = ctk.CTkFont(size=base_size)

    def resize(self, base_size: int) -> None:
        self.base.configure(size=base_size)
        self.bold.configure(size=base_size)
        self.title.configure(size=base_size)
        self.help.configure(size=base_size)


class Tooltip:
    """Hover tooltip. The toplevel is created **lazily on first hover** — building ~40 eager
    toplevels at startup measurably slows construction and flickers on some window managers."""

    def __init__(self, widget: ctk.CTkBaseClass, text: str, fonts: Fonts | None = None) -> None:
        self._widget = widget
        self._text = text
        self._fonts = fonts
        self._win: ctk.CTkToplevel | None = None
        try:
            widget.bind("<Enter>", self._show, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<Destroy>", self._destroy, add="+")
        except NotImplementedError:
            pass                     # widget doesn't support bind; no tooltip

    def _build(self) -> ctk.CTkToplevel:
        win = ctk.CTkToplevel(self._widget)
        win.wm_overrideredirect(True)
        win.withdraw()
        ctk.CTkLabel(win, text=self._text, corner_radius=6, padx=8, pady=4,
                     fg_color=THEMES["card"],
                     font=self._fonts.base if self._fonts is not None else None).pack()
        return win

    def _show(self, _event: tk.Event[tk.Misc]) -> None:
        if not self._text:
            return
        if self._win is None:
            self._win = self._build()
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        self._win.wm_geometry(f"+{x}+{y}")
        self._win.deiconify()

    def _hide(self, _event: tk.Event[tk.Misc]) -> None:
        if self._win is not None:
            self._win.withdraw()

    def _destroy(self, _event: tk.Event[tk.Misc]) -> None:
        if self._win is not None:
            self._win.destroy()
            self._win = None


def tooltip(widget: ctk.CTkBaseClass, text: str, fonts: Fonts | None = None) -> None:
    Tooltip(widget, text, fonts)


def card(parent: ctk.CTkBaseClass, title: str, fonts: Fonts) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    outer = ctk.CTkFrame(parent, fg_color=THEMES["card"], border_width=1,
                          border_color=THEMES["card_border"], corner_radius=10)
    ctk.CTkLabel(outer, text=title, anchor="w", font=fonts.bold).pack(
        fill="x", padx=12, pady=(10, 2))
    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="x", padx=12, pady=(0, 12))
    return outer, body


def highlight_button(parent: ctk.CTkBaseClass, text: str, command: Callable[[], None],
                      fonts: Fonts, **kwargs: object) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, command=command, font=fonts.base,
                          fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                          text_color=THEMES["secondary_text"], **kwargs)


def set_active(button: ctk.CTkButton, active: bool) -> None:
    """Highlight/unhighlight, reconfiguring only on a real change — an unconditional configure
    repaints the widget and makes every refresh blink and drag the scroll (#8, #14)."""
    fg = THEMES["accent"] if active else THEMES["secondary"]
    if button.cget("fg_color") == fg:
        return
    button.configure(fg_color=fg,
                      hover_color=THEMES["accent_hover"] if active else THEMES["secondary_hover"],
                      text_color=THEMES["accent_text"] if active else THEMES["secondary_text"])


def set_text(widget: ctk.CTkBaseClass, text: str) -> None:
    """configure(text=…) only when it changed (same no-repaint rationale as set_active)."""
    if widget.cget("text") != text:
        widget.configure(text=text)


def set_menu(menu: ctk.CTkOptionMenu, value: str) -> None:
    """menu.set(…) only when it changed (same no-repaint rationale as set_active)."""
    if menu.get() != value:
        menu.set(value)


def option_menu(parent: ctk.CTkBaseClass, fonts: Fonts, **kwargs: object) -> ctk.CTkOptionMenu:
    """Themed option menu; the dropdown list uses the shared base font (#17 — same size as the
    rest of the UI), via the public `dropdown_font` parameter."""
    return ctk.CTkOptionMenu(parent, font=fonts.base, dropdown_font=fonts.base,
        fg_color=THEMES["secondary"], button_color=THEMES["secondary"],
        button_hover_color=THEMES["secondary_hover"], text_color=THEMES["secondary_text"],
        **kwargs)

def labeled_row(parent: ctk.CTkBaseClass, label: str, fonts: Fonts) -> ctk.CTkFrame:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(row, text=label, anchor="w", font=fonts.base, width=140).pack(side="left")
    return row


def export_split_button(
        parent: ctk.CTkBaseClass, fmt: str, fonts: Fonts, on_export: Callable[[], None],
        on_pick_format: Callable[[str], None]
) -> tuple[ctk.CTkFrame, ctk.CTkButton, ctk.CTkOptionMenu]:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    main = ctk.CTkButton(frame, text=f"💾  Export {fmt}", command=on_export, font=fonts.base,
                          fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                          text_color=THEMES["secondary_text"])
    main.pack(side="left", fill="x", expand=True)
    fmt_menu = option_menu(frame, fonts, values=list(EXPORT_FORMATS), command=on_pick_format,
                            width=90, dynamic_resizing=False)
    fmt_menu.set(fmt)
    fmt_menu.pack(side="left", padx=(4, 0))
    return frame, main, fmt_menu


def offset_spinner(parent: ctk.CTkBaseClass, label: str, value: float,
                    on_commit: Callable[[float], None],
                    fonts: Fonts) -> tuple[ctk.CTkFrame, ctk.CTkEntry]:
    """One offset field: label + numeric entry. Commits on Return/blur. No up/down buttons."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(frame, text=label, width=16, font=fonts.base,
                 text_color=THEMES["muted"]).pack(side="left")
    entry = ctk.CTkEntry(frame, width=OFFSET_FIELD_W, font=fonts.base)
    entry.insert(0, f"{value:.1f}")
    entry.pack(side="left", padx=(2, 0))

    def _commit(_event: object = None) -> None:
        try:
            on_commit(float(entry.get()))
        except ValueError:
            pass

    entry.bind("<Return>", _commit)
    entry.bind("<FocusOut>", _commit)
    return frame, entry


def set_entry_text(entry: ctk.CTkEntry, text: str) -> None:
    if entry.get() != text:
        entry.delete(0, "end")
        entry.insert(0, text)


# ── Settings window ─────────────────────────────────────────────────────────
def build_settings_window(parent: ctk.CTk, settings: Settings, ui_config: UIConfig, fonts: Fonts,
                           *, on_appearance: Callable[[str], None],
                           on_font_size: Callable[[int], None],
                           on_scale: Callable[[float], None],
                           on_compress: Callable[[str], None],
                           on_format: Callable[[str], None],
                           on_undo_depth: Callable[[int], None]) -> ctk.CTkToplevel:
    win = ctk.CTkToplevel(parent)
    win.title("Settings — SmartCrop PDF")
    win.transient(parent)
    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=16, pady=16)

    _appearance_section(body, ui_config, fonts, on_appearance, on_font_size, on_scale)
    _output_section(body, settings, fonts, on_compress, on_format)
    _behaviour_section(body, settings, ui_config, fonts, on_undo_depth)
    _scan_section(body, settings, fonts)

    win.update_idletasks()
    # Size to content — no large hardcoded floor; open over the left panel, aligned to the main
    # window's top-left corner (§15, inv 31).
    w = max(320, body.winfo_reqwidth())
    h = body.winfo_reqheight() + 40
    win.geometry(f"{w}x{h}+{parent.winfo_rootx()}+{parent.winfo_rooty()}")
    win.minsize(w, h)
    return win


def _seg_kwargs() -> dict[str, object]:
    """Shared CTkSegmentedButton theme kwargs."""
    return dict(
        selected_color=THEMES["accent"],
        selected_hover_color=THEMES["accent_hover"],
        unselected_color=THEMES["seg_unsel"],
        unselected_hover_color=THEMES["secondary_hover"],
        text_color=THEMES["accent_text"],
        text_color_disabled=THEMES["muted"],
    )


def _appearance_section(body: ctk.CTkBaseClass, ui_config: UIConfig, fonts: Fonts,
                         on_appearance: Callable[[str], None],
                         on_font_size: Callable[[int], None],
                         on_scale: Callable[[float], None]) -> None:
    outer, sec = card(body, "Appearance", fonts)
    outer.pack(fill="x", pady=(0, 10))

    row = _srow(sec, "Colour scheme", fonts)
    seg = ctk.CTkSegmentedButton(row, values=["Light", "Dark", "System"],
                                  command=on_appearance, font=fonts.base, **_seg_kwargs())
    seg.set(ui_config.theme)
    seg.pack(side="right")
    row.pack(fill="x", pady=4)

    row = _srow(sec, "Font size", fonts)
    sizes = [str(n) for n in range(FONT_SIZE_MIN, FONT_SIZE_MAX + 1)]
    m = option_menu(row, fonts, values=sizes, command=lambda v: on_font_size(int(v)), width=140)
    m.set(str(ui_config.font_size))
    m.pack(side="right")
    row.pack(fill="x", pady=4)

    row = _srow(sec, "Zoom (UI scale)", fonts)
    scale_presets = (UI_SCALE_MIN, 0.85, 1.0, 1.15, 1.3, 1.5, UI_SCALE_MAX)
    pct = [f"{round(p * 100)}%" for p in scale_presets]
    zm = option_menu(row, fonts, values=pct, width=140,
                     command=lambda v: on_scale(int(v.rstrip("%")) / 100.0))
    nearest = min(scale_presets, key=lambda p: abs(p - ui_config.ui_scale))
    zm.set(f"{round(nearest * 100)}%")
    zm.pack(side="right")
    row.pack(fill="x", pady=4)


def _output_section(body: ctk.CTkBaseClass, settings: Settings, fonts: Fonts,
                     on_compress: Callable[[str], None], on_format: Callable[[str], None]) -> None:
    outer, sec = card(body, "Output", fonts)
    outer.pack(fill="x", pady=(0, 10))

    row = _srow(sec, "Compress to", fonts)
    m = option_menu(row, fonts, values=list(DPI_PRESETS), command=on_compress, width=180)
    m.set(settings.compress_preset)
    m.pack(side="right")
    row.pack(fill="x", pady=4)

    row = _srow(sec, "Default format", fonts)
    fm = option_menu(row, fonts, values=EXPORT_FORMATS, command=on_format, width=140)
    fm.set(settings.export_format)
    fm.pack(side="right")
    row.pack(fill="x", pady=4)

    row = _srow(sec, "Output Folder", fonts)
    entry = ctk.CTkEntry(row, font=fonts.base, placeholder_text="same as source", width=180)
    entry.insert(0, settings.output_folder or "")
    ctk.CTkButton(row, text="…", width=36, font=fonts.base,
                  command=lambda: _pick_folder(row, entry, settings),
                  fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                  text_color=THEMES["secondary_text"]).pack(side="right")
    entry.pack(side="right", fill="x", padx=(8, 6))

    def _commit_folder(_event: object = None) -> None:
        value = entry.get().strip()
        settings.output_folder = "" if value == "same as source" else value

    entry.bind("<Return>", _commit_folder)
    entry.bind("<FocusOut>", _commit_folder)
    row.pack(fill="x", pady=4)

    row = _srow(sec, "Output postfix", fonts)
    pentry = ctk.CTkEntry(row, width=120, font=fonts.base)
    pentry.insert(0, settings.output_postfix)
    pentry.bind("<Return>", lambda _e: setattr(settings, "output_postfix", pentry.get()))
    pentry.bind("<FocusOut>", lambda _e: setattr(settings, "output_postfix", pentry.get()))
    pentry.pack(side="right")
    row.pack(fill="x", pady=4)


def _pick_folder(parent: ctk.CTkBaseClass, entry: ctk.CTkEntry, settings: Settings) -> None:
    chosen = filedialog.askdirectory(parent=parent)
    if chosen:
        settings.output_folder = chosen
        set_entry_text(entry, chosen)


def _behaviour_section(body: ctk.CTkBaseClass, settings: Settings, ui_config: UIConfig,
                        fonts: Fonts, on_undo_depth: Callable[[int], None]) -> None:
    outer, sec = card(body, "Behaviour", fonts)
    outer.pack(fill="x", pady=(0, 10))

    _settings_switch(sec, "Confirm before overwrite", ui_config.confirm_overwrite, fonts,
                      lambda v: setattr(ui_config, "confirm_overwrite", v))
    _settings_switch(sec, "Remember last folder", ui_config.remember_folder, fonts,
                      lambda v: setattr(ui_config, "remember_folder", v))

    row = _srow(sec, "Undo / redo depth", fonts)
    entry = ctk.CTkEntry(row, width=60, font=fonts.base)
    entry.insert(0, str(settings.undo_depth))

    def _commit(_event: object = None) -> None:
        try:
            on_undo_depth(int(entry.get()))
        except ValueError:
            pass

    entry.bind("<Return>", _commit)
    entry.bind("<FocusOut>", _commit)
    entry.pack(side="right")
    row.pack(fill="x", pady=4)


def _scan_section(body: ctk.CTkBaseClass, settings: Settings, fonts: Fonts) -> None:
    outer, sec = card(body, "Scan", fonts)
    outer.pack(fill="x")

    row = _srow(sec, "Dewarp supersample", fonts)
    entry = ctk.CTkEntry(row, width=48, font=fonts.base)
    entry.insert(0, str(settings.dewarp_supersample))

    def _commit(_event: object = None) -> None:
        try:
            v = float(entry.get())
            if v < 1.0:
                raise ValueError
        except ValueError:
            set_entry_text(entry, str(settings.dewarp_supersample))
            return
        settings.dewarp_supersample = v

    entry.bind("<Return>", _commit)
    entry.bind("<FocusOut>", _commit)
    entry.pack(side="right")
    row.pack(fill="x", pady=4)


def _srow(parent: ctk.CTkBaseClass, label: str, fonts: Fonts) -> ctk.CTkFrame:
    """Settings row: label left (auto-width), control packs right."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(row, text=label, anchor="w", font=fonts.base).pack(side="left")
    return row


def _settings_switch(parent: ctk.CTkBaseClass, label: str, on: bool, fonts: Fonts,
                      apply: Callable[[bool], None]) -> None:
    row = _srow(parent, label, fonts)
    var = tk.BooleanVar(value=on)
    ctk.CTkSwitch(row, text="", variable=var, font=fonts.base,
                  progress_color=THEMES["accent"],
                  command=lambda: apply(bool(var.get()))).pack(side="right")
    row.pack(fill="x", pady=4)


# ── Help window ─────────────────────────────────────────────────────────────
def build_help_window(parent: ctk.CTk, fonts: Fonts) -> ctk.CTkToplevel:
    win = ctk.CTkToplevel(parent)
    win.title("Help & Quick-Start")
    # Over the left panel: main window's top-left corner, main window's height (§16, inv 31).
    height = max(400, parent.winfo_height())
    win.geometry(f"640x{height}+{parent.winfo_rootx()}+{parent.winfo_rooty()}")
    win.transient(parent)
    win.after(100, lambda: (win.lift(), win.focus_force()))
    ctk.CTkLabel(win, text=INTRO, justify="left", wraplength=580, font=fonts.help).pack(
        anchor="w", padx=16, pady=(16, 8))

    body = ctk.CTkScrollableFrame(win, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    anchors: dict[str, ctk.CTkFrame] = {}

    def _scroll_to(title: str) -> None:
        body.update_idletasks()
        target = anchors[title]
        inner = target.master
        total = max(1, inner.winfo_height())
        y = target.winfo_rooty() - inner.winfo_rooty()
        body._parent_canvas.yview_moveto(max(0.0, min(1.0, y / total)))

    contents_outer, contents_body = card(body, "Contents", fonts)
    contents_outer.pack(fill="x", pady=(0, 12))
    for section in SECTIONS:
        ctk.CTkButton(contents_body, text=f"›  {section.title}", anchor="w", font=fonts.base,
                      fg_color="transparent", text_color=THEMES["secondary_text"],
                      command=lambda t=section.title: _scroll_to(t)).pack(fill="x", pady=2)

    for section in SECTIONS:
        frame = ctk.CTkFrame(body, fg_color="transparent")
        frame.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(frame, text=section.title, anchor="w", font=fonts.title).pack(fill="x")
        ctk.CTkLabel(frame, text=section.body, anchor="w", justify="left", wraplength=560,
                      font=fonts.help).pack(fill="x", pady=(2, 0))
        anchors[section.title] = frame
    return win


# ── Progress overlay ─────────────────────────────────────────────────────────
class ProgressCard:
    def __init__(self, canvas_parent: ctk.CTkBaseClass, fonts: Fonts,
                 on_cancel: Callable[[], None]) -> None:
        self.frame = ctk.CTkFrame(canvas_parent, corner_radius=10)
        self.title = ctk.CTkLabel(self.frame, text="", font=fonts.bold)
        self.title.pack(padx=28, pady=(18, 8))
        self.bar = ctk.CTkProgressBar(self.frame, width=220,
                                       progress_color=THEMES["accent"])
        self.bar.set(0)
        self.bar.pack(padx=28, pady=4)
        self.counter = ctk.CTkLabel(self.frame, text="", font=fonts.base)
        self.counter.pack(pady=(2, 10))
        ctk.CTkButton(self.frame, text="Cancel", font=fonts.base, command=on_cancel,
                      fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                      text_color=THEMES["secondary_text"]).pack(pady=(0, 18))

    def place(self) -> None:
        self.frame.place(relx=0.5, rely=0.5, anchor="center")

    def hide(self) -> None:
        self.frame.place_forget()

    def paint(self, job: BatchJob) -> None:
        self.title.configure(text=f"{job.title}...")
        self.bar.set(job.done / job.total if job.total else 1.0)
        self.counter.configure(text=f"{job.done} / {job.total}")
