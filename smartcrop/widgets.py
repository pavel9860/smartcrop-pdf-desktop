"""Reusable Tkinter widgets. Kept free of app logic; they take the app only for
theme/font lookups via the small protocol below (app exposes ._t and ._f/.FONT_SCALE)."""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional


class Tooltip:
    _DELAY = 500
    _WRAPLEN = 340

    def __init__(self, widget: tk.Widget, text: str, app) -> None:
        self._w, self._text, self._app = widget, text, app
        self._job: Optional[str] = None
        self._win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._job = self._w.after(self._DELAY, self._show)

    def _cancel(self, _e=None) -> None:
        if self._job:
            self._w.after_cancel(self._job)
            self._job = None
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None

    def _show(self) -> None:
        t = self._app._t
        fs = round(10 * self._app.FONT_SCALE)
        x = self._w.winfo_rootx() + 12
        y = self._w.winfo_rooty() + self._w.winfo_height() + 6
        self._win = tw = tk.Toplevel(self._w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(tw, text=self._text, justify=tk.LEFT, bg=t["PANEL_2"], fg=t["TEXT"],
                 font=("Segoe UI", fs), relief="solid", bd=1, padx=10, pady=6,
                 wraplength=self._WRAPLEN).pack()


class ToggleSwitch(tk.Canvas):
    W, H, R = 48, 24, 10

    def __init__(self, parent: tk.Widget, variable: tk.BooleanVar, app, **kw) -> None:
        t = app._t
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0,
                         bd=0, bg=t["PANEL"], **kw)
        self._var, self._app = variable, app
        self._enabled = True
        self._draw()
        variable.trace_add("write", lambda *_: self._draw())
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _e: self.configure(cursor="hand2" if self._enabled else ""))
        self.bind("<Leave>", lambda _e: self.configure(cursor=""))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._draw()

    def _draw(self) -> None:
        t, on = self._app._t, self._var.get()
        self.configure(bg=t["PANEL"])
        self.delete("all")
        if not self._enabled:
            col = t["SW_OFF"]
            r, w, h = self.R, self.W, self.H
            self.create_arc(1, 1, 2 * r + 1, h - 1, start=90, extent=180, fill=col, outline=col)
            self.create_arc(w - 2 * r - 1, 1, w - 1, h - 1, start=-90, extent=180, fill=col, outline=col)
            self.create_rectangle(r + 1, 1, w - r - 1, h - 1, fill=col, outline=col)
            kx = r + 3
            self.create_oval(kx - r + 2, 3, kx + r - 2, h - 3, fill=t["MUTED"], outline=t["MUTED"])
            return
        col = t["SW_ON"] if on else t["SW_OFF"]
        r, w, h = self.R, self.W, self.H
        self.create_arc(1, 1, 2 * r + 1, h - 1, start=90, extent=180, fill=col, outline=col)
        self.create_arc(w - 2 * r - 1, 1, w - 1, h - 1, start=-90, extent=180, fill=col, outline=col)
        self.create_rectangle(r + 1, 1, w - r - 1, h - 1, fill=col, outline=col)
        kx = w - r - 3 if on else r + 3
        knob = t["SW_KNOB_ON"] if on else t["SW_KNOB_OFF"]
        self.create_oval(kx - r + 2, 3, kx + r - 2, h - 3, fill=knob, outline=knob)

    def _toggle(self, _e=None) -> None:
        if not self._enabled:
            return
        self._var.set(not self._var.get())

    def refresh_colors(self) -> None:
        self._draw()


def make_toggle_row(parent: tk.Widget, label_text: str, var: tk.BooleanVar, app,
                    tooltip: str = "") -> ToggleSwitch:
    row = tk.Frame(parent, bg=app._t["PANEL"])
    row.pack(fill=tk.X, pady=2)
    sw = ToggleSwitch(row, var, app)
    sw.pack(side=tk.LEFT, padx=(0, 8))
    lbl = tk.Label(row, text=label_text, bg=app._t["PANEL"], fg=app._t["TEXT"],
                   font=("Segoe UI", round(14 * app.FONT_SCALE)))
    lbl.pack(side=tk.LEFT)
    if tooltip:
        for w in (sw, lbl, row):
            Tooltip(w, tooltip, app)
    return sw


class Segmented(tk.Frame):
    """Row of mutually-exclusive value buttons (strength / split / pages).
    Highlights the active value with the app's Selected.TButton style."""

    def __init__(self, parent: tk.Widget, app, values: List, labels: List[str],
                 on_select: Callable, initial=None, tooltip: str = "") -> None:
        from tkinter import ttk
        super().__init__(parent, bg=app._t["PANEL"])
        self._app = app
        self._on_select = on_select
        self._buttons: Dict[object, "ttk.Button"] = {}
        self._value = initial if initial is not None else values[0]
        for val, lab in zip(values, labels):
            b = ttk.Button(self, text=lab, width=max(3, len(lab)),
                           command=lambda v=val: self._pick(v))
            b.pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)
            self._buttons[val] = b
            if tooltip:
                Tooltip(b, tooltip, app)
        self._restyle()

    def _pick(self, val) -> None:
        self._value = val
        self._restyle()
        self._on_select(val)

    def set_value(self, val) -> None:
        self._value = val
        self._restyle()

    def get(self):
        return self._value

    def _restyle(self) -> None:
        for v, b in self._buttons.items():
            b.configure(style="Selected.TButton" if v == self._value else "TButton")

    def set_enabled(self, enabled: bool) -> None:
        for b in self._buttons.values():
            b.configure(state="normal" if enabled else "disabled")
