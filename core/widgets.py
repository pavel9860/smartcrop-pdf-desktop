"""Reusable CustomTkinter widgets: hover tooltip and a compact offset stepper."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk


class ToolTip:
    def __init__(self, widget, text: str, app):
        self.w, self.text, self.app = widget, text, app
        self.win = None
        self.job = None
        try:
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")
            widget.bind("<ButtonPress>", self._leave, add="+")
            # Strict lifecycle: if the widget is destroyed (view rebuilt, modal closed) while a
            # show-timer is pending or the tip is up, cancel the job and tear the tip down so no
            # phantom callback fires on a dead widget and no orphan Toplevel leaks.
            widget.bind("<Destroy>", self._leave, add="+")
        except (NotImplementedError, tk.TclError):
            pass   # some CTk composite widgets reject .bind; tooltip silently skipped

    def _enter(self, _e=None):
        self.job = self.w.after(450, self._show)

    def _show(self):
        self.job = None
        try:
            if not self.w.winfo_exists():            # widget gone before the timer fired
                return
            x = self.w.winfo_rootx() + 14
            y = self.w.winfo_rooty() + self.w.winfo_height() + 6
        except tk.TclError:
            return
        self.win = tw = tk.Toplevel(self.w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except tk.TclError:
            pass
        dark = ctk.get_appearance_mode() == "Dark"
        lbl = tk.Label(tw, text=self.text, justify="left", wraplength=320,
                       bg="#2b2b30" if dark else "#f4f4f6", fg="#ededee" if dark else "#1a1a1a",
                       relief="solid", bd=1, padx=10, pady=6, font=("Segoe UI", 12))
        lbl.pack()

    def _leave(self, _e=None):
        if self.job:
            try:
                self.w.after_cancel(self.job)        # cancel the pending show-timer explicitly
            except (tk.TclError, ValueError):
                pass
            self.job = None
        if self.win:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


class Spin(ctk.CTkFrame):
    """Compact offset stepper: bigger-font entry, wheel + arrow-key stepping (±100, 0.1)."""
    def __init__(self, master, var: tk.DoubleVar, app, lo=-100.0, hi=100.0, step=0.1, width=64):
        super().__init__(master, fg_color="transparent")
        self.var, self.lo, self.hi, self.step = var, lo, hi, step
        self.entry = ctk.CTkEntry(self, textvariable=var, width=width, justify="center",
                                  font=app.font_offset)
        self.entry.pack(fill="x")
        self.entry.bind("<MouseWheel>", self._wheel)          # Windows / macOS
        self.entry.bind("<Button-4>", lambda _e: self._scroll(+1))   # X11 (Linux) wheel up
        self.entry.bind("<Button-5>", lambda _e: self._scroll(-1))   # X11 (Linux) wheel down
        self.entry.bind("<Up>", lambda _e: self._bump(self.step))
        self.entry.bind("<Down>", lambda _e: self._bump(-self.step))

    def _wheel(self, e):
        return self._scroll(1 if e.delta > 0 else -1)         # MouseWheel sign → direction

    def _scroll(self, direction: int):
        self._bump(self.step * direction)
        return "break"

    def _bump(self, d):
        try:
            v = float(self.var.get())
        except (tk.TclError, ValueError):
            v = 0.0
        self.var.set(round(min(self.hi, max(self.lo, v + d)), 1))

    def configure_state(self, state):
        self.entry.configure(state=state)
