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
    THEMES,
    UI_SCALE_MAX,
    UI_SCALE_MIN,
)
from ui.help_content import INTRO, SECTIONS


class Fonts:
    def __init__(self, base_size: int) -> None:
        self.base = ctk.CTkFont(size=base_size)
        self.bold = ctk.CTkFont(size=base_size, weight="bold")
        self.title = ctk.CTkFont(size=base_size + 2, weight="bold")
        self.help = ctk.CTkFont(size=base_size + 1)

    def resize(self, base_size: int) -> None:
        self.base.configure(size=base_size)
        self.bold.configure(size=base_size)
        self.title.configure(size=base_size + 2)
        self.help.configure(size=base_size + 1)


class Tooltip:
    def __init__(self, widget: ctk.CTkBaseClass, text: str) -> None:
        self._widget = widget
        self._text = text
        self._win = ctk.CTkToplevel(widget)
        self._win.wm_overrideredirect(True)
        self._win.withdraw()
        ctk.CTkLabel(self._win, text=text, corner_radius=6, padx=8, pady=4,
                     fg_color=THEMES["card"]).pack()
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Destroy>", self._destroy, add="+")

    def _show(self, _event: tk.Event[tk.Misc]) -> None:
        if not self._text:
            return
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        self._win.wm_geometry(f"+{x}+{y}")
        self._win.deiconify()

    def _hide(self, _event: tk.Event[tk.Misc]) -> None:
        self._win.withdraw()

    def _destroy(self, _event: tk.Event[tk.Misc]) -> None:
        self._win.destroy()


def tooltip(widget: ctk.CTkBaseClass, text: str) -> None:
    Tooltip(widget, text)


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
    button.configure(fg_color=THEMES["accent"] if active else THEMES["secondary"],
                      hover_color=THEMES["accent_hover"] if active else THEMES["secondary_hover"],
                      text_color=THEMES["accent_text"] if active else THEMES["secondary_text"])


def option_menu(parent: ctk.CTkBaseClass, fonts: Fonts, **kwargs: object) -> ctk.CTkOptionMenu:
    """CTkOptionMenu with THEMES colours — neutral (secondary) at rest, never accent blue."""
    return ctk.CTkOptionMenu(
        parent, font=fonts.base,
        fg_color=THEMES["secondary"], button_color=THEMES["secondary"],
        button_hover_color=THEMES["secondary_hover"], text_color=THEMES["secondary_text"],
        **kwargs)


def labeled_row(parent: ctk.CTkBaseClass, label: str, fonts: Fonts) -> ctk.CTkFrame:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(row, text=label, anchor="w", font=fonts.base, width=140).pack(side="left")
    return row


def offset_spinner(parent: ctk.CTkBaseClass, label: str, value: float,
                    on_commit: Callable[[float], None],
                    fonts: Fonts) -> tuple[ctk.CTkFrame, ctk.CTkEntry]:
    """One offset field: label + numeric entry. Commits on Return/blur. No up/down buttons."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(frame, text=label, width=16, font=fonts.base,
                 text_color=THEMES["muted"]).pack(side="left")
    entry = ctk.CTkEntry(frame, width=64, font=fonts.base)
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
    # Size to content — no large hardcoded floor
    w = max(460, body.winfo_reqwidth() + 40)
    h = body.winfo_reqheight() + 40
    win.geometry(f"{w}x{h}")
    win.minsize(w, h)
    return win


def _seg_kwargs() -> dict:
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

    row = _srow(sec, "Output folder", fonts)
    ctk.CTkButton(row, text="…", width=36, font=fonts.base, command=lambda: _pick_folder(row, entry, settings),
                  fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                  text_color=THEMES["secondary_text"]).pack(side="right")
    entry = ctk.CTkEntry(row, font=fonts.base, placeholder_text="same as source")
    entry.insert(0, settings.output_folder or "")
    entry.pack(side="right", fill="x", expand=True, padx=(8, 6))

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
    entry = ctk.CTkEntry(row, width=60, font=fonts.base)
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
    win.geometry("640x720")
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


# ── Export split button ──────────────────────────────────────────────────────
def export_split_button(
        parent: ctk.CTkBaseClass, fmt: str, fonts: Fonts, on_export: Callable[[], None],
        on_pick_format: Callable[[str], None]) -> tuple[ctk.CTkFrame, ctk.CTkButton]:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    main = ctk.CTkButton(frame, text=f"💾  Export {fmt}", command=on_export, font=fonts.base,
                          fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                          text_color=THEMES["secondary_text"])
    main.pack(side="left", fill="x", expand=True)

    def _pick(choice: str) -> Callable[[], None]:
        return lambda: on_pick_format(choice)

    def _open_menu() -> None:
        menu = tk.Menu(frame, tearoff=False)
        for choice in EXPORT_FORMATS:
            menu.add_command(label=choice, command=_pick(choice))
        menu.tk_popup(frame.winfo_pointerx(), frame.winfo_pointery())

    # Show current format + arrow so the user can see what format is active
    fmt_btn = ctk.CTkButton(frame, text=f"{fmt} ▾", width=72, font=fonts.base,
                             command=_open_menu,
                             fg_color=THEMES["secondary"], hover_color=THEMES["secondary_hover"],
                             text_color=THEMES["secondary_text"])
    fmt_btn.pack(side="left", padx=(4, 0))
    return frame, main


def update_export_fmt_btn(frame: ctk.CTkFrame, fmt: str) -> None:
    """Update the format label on the ▾ button when format changes."""
    for child in frame.winfo_children():
        if isinstance(child, ctk.CTkButton) and "▾" in (child.cget("text") or ""):
            child.configure(text=f"{fmt} ▾")
            break


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