"""`SmartCropApp` — the root window (spec §6, ARCHITECTURE §6). Owns the one `AppModel`; `dispatch`
and `dispatch_job` are the only two places a `SmartCropError` is caught and shown. Long operations
are driven one `step()` per `root.after` tick (§14); everything else here is widget construction
and event wiring — domain logic stays in `AppModel`, presentation wiring stays in `panels.py`.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from types import TracebackType
from typing import Callable

import customtkinter as ctk

from core.batch import BatchJob, Failed
from core.constants import IMAGE_LOAD_EXT
from core.errors import SmartCropError
from core.model import AppModel, ViewSnapshot
from ui.canvas_view import CanvasView
from ui.config import UIConfig
from ui.constants import (
    PANEL_WIDTH,
    SCALE_THROTTLE_MS,
    THEMES,
    UI_SCALE_MAX,
    UI_SCALE_MIN,
    WINDOW_MIN,
    WINDOW_SIZE,
)
from ui.panels import LeftPanel, PanelCallbacks
from ui.ui_build import (
    Fonts,
    ProgressCard,
    build_help_window,
    build_settings_window,
    highlight_button,
    set_entry_text,
)


class SmartCropApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.model = AppModel()
        self.ui_config = UIConfig()
        self.fonts = Fonts(self.ui_config.font_size)
        self._current_job: BatchJob | None = None
        self._scale_after_id: str | None = None
        self._pending_scale = self.ui_config.ui_scale

        root.title("SmartCrop PDF")
        root.geometry(WINDOW_SIZE)
        root.minsize(*WINDOW_MIN)
        ctk.set_appearance_mode(self.ui_config.theme)

        self._build_left_pane()
        self._build_right_pane()
        self._bind_shortcuts()
        root.report_callback_exception = self._handle_callback_error
        self.refresh_all()

    # ── construction (spec §6 layout) ─────────────────────────────────────────
    def _build_left_pane(self) -> None:
        left_outer = ctk.CTkFrame(self.root, width=PANEL_WIDTH)
        left_outer.pack_propagate(False)
        left_outer.pack(side="left", fill="y")
        self._build_pinned_bar(left_outer)        # packed side="bottom" first: claims its space
        cb = PanelCallbacks(dispatch=self.dispatch, dispatch_job=self.dispatch_job,
                             on_load_files=self._load_files, on_delete=self._delete_pages,
                             on_export=self._export, on_pick_format=self._pick_export_format)
        self.panel = LeftPanel(left_outer, self.model, self.fonts, cb)

    def _build_right_pane(self) -> None:
        right_outer = ctk.CTkFrame(self.root, fg_color="transparent")
        right_outer.pack(side="left", fill="both", expand=True)
        self.status_label = ctk.CTkLabel(right_outer, text="", font=self.fonts.base, anchor="e")
        self.status_label.pack(side="bottom", anchor="e", padx=10, pady=6)
        canvas_holder = ctk.CTkFrame(right_outer, fg_color="transparent")
        canvas_holder.pack(side="top", fill="both", expand=True)
        self.canvas_view = CanvasView(canvas_holder, self.model, self.refresh_all,
                                       self.status_label)
        self.progress = ProgressCard(canvas_holder, self.fonts, self._cancel_job)

    def _build_pinned_bar(self, parent: ctk.CTkBaseClass) -> None:
        """Settings/Help + Undo/Redo/Reset + page nav — pinned, NOT in the scroll frame (§7.8)."""
        self.nav_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self.nav_bar.pack(side="bottom", fill="x", padx=12, pady=12)
        self._build_settings_help_row()
        self._build_history_row()
        self._build_page_nav_row()

    def _build_settings_help_row(self) -> None:
        row = ctk.CTkFrame(self.nav_bar, fg_color="transparent")
        row.pack(fill="x")
        self.btn_settings = highlight_button(row, "⚙  Settings", self._open_settings, self.fonts)
        self.btn_settings.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_help = highlight_button(row, "?  Help", self._open_help, self.fonts)
        self.btn_help.pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_history_row(self) -> None:
        row = ctk.CTkFrame(self.nav_bar, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        row.columnconfigure((0, 1, 2), weight=1, uniform="urr")
        self.btn_undo = highlight_button(
            row, "↩  Undo", lambda: self.dispatch(self.model.undo), self.fonts)
        self.btn_undo.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_redo = highlight_button(
            row, "↪  Redo", lambda: self.dispatch(self.model.redo), self.fonts)
        self.btn_redo.grid(row=0, column=1, sticky="ew", padx=3)
        self.btn_reset = highlight_button(
            row, "↺  Reset", lambda: self.dispatch(self.model.reset), self.fonts)
        self.btn_reset.grid(row=0, column=2, sticky="ew", padx=(3, 0))

    def _build_page_nav_row(self) -> None:
        row = ctk.CTkFrame(self.nav_bar, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        row.columnconfigure(0, weight=0)
        row.columnconfigure(1, weight=1)
        row.columnconfigure(2, weight=0)
        self.btn_prev = highlight_button(row, "◀", lambda: self.dispatch(self.model.prev_page),
                                          self.fonts, width=36, height=36)
        self.btn_prev.grid(row=0, column=0, sticky="w")
        centre = ctk.CTkFrame(row, fg_color="transparent")
        centre.grid(row=0, column=1)
        self.entry_page = ctk.CTkEntry(centre, width=60, font=self.fonts.base, justify="center")
        self.entry_page.pack(side="left")
        self.entry_page.bind("<Return>", self._jump_to_page)
        self.lbl_total = ctk.CTkLabel(centre, text="/ 0", font=self.fonts.base,
                                       text_color=THEMES["muted"])
        self.lbl_total.pack(side="left", padx=(6, 0))
        self.btn_next = highlight_button(row, "▶", lambda: self.dispatch(self.model.next_page),
                                          self.fonts, width=36, height=36)
        self.btn_next.grid(row=0, column=2, sticky="e")

    # ── dispatch (ARCHITECTURE §6: the only two SmartCropError catch sites) ──────────────────
    def dispatch(self, command: Callable[[], None]) -> None:
        try:
            command()
        except SmartCropError as exc:
            messagebox.showerror(type(exc).__name__, str(exc))
        self.refresh_all()

    def dispatch_job(self, make_job: Callable[[], BatchJob]) -> None:
        try:
            job = make_job()
        except SmartCropError as exc:
            messagebox.showerror(type(exc).__name__, str(exc))
            self.refresh_all()
            return
        self._start_job(job)

    def _start_job(self, job: BatchJob) -> None:
        self._current_job = job
        if job.total > 1:
            self.progress.place()
        self.refresh_all()
        self.root.after(1, self._drive)

    def _drive(self) -> None:
        job = self._current_job
        if job is None:
            return
        if not job.is_finished():
            job.step()
            if job.total > 1:
                self.progress.paint(job)
            self.root.after(1, self._drive)
            return
        self.progress.hide()
        self._current_job = None
        result = job.result()
        if isinstance(result, Failed):
            messagebox.showerror(type(result.error).__name__, str(result.error))
        self.refresh_all()

    def _cancel_job(self) -> None:
        if self._current_job is not None:
            self._current_job.cancel()

    # ── refresh (ARCHITECTURE §3: re-read the model, re-set widgets unconditionally) ─────────
    def refresh_all(self) -> None:
        busy = self._current_job is not None
        self.panel.refresh(busy)
        snap = self.canvas_view.redraw()
        self._refresh_nav_bar(snap, busy)

    def _refresh_nav_bar(self, snap: ViewSnapshot, busy: bool) -> None:
        set_entry_text(self.entry_page, str(snap.position))
        self.lbl_total.configure(text=f"/ {snap.total}")
        self.btn_undo.configure(state="normal" if (self.model.can_undo and not busy)
                                 else "disabled")
        self.btn_redo.configure(state="normal" if (self.model.can_redo and not busy)
                                 else "disabled")
        for w in (self.btn_reset, self.btn_settings, self.btn_help, self.btn_prev,
                  self.btn_next, self.entry_page):
            w.configure(state="disabled" if busy else "normal")

    def _jump_to_page(self, _event: object = None) -> None:
        try:
            n = int(self.entry_page.get())
        except ValueError:
            return
        self.dispatch(lambda: self.model.jump_to_output_page(n))

    # ── commands needing a dialog (load / export / delete) ───────────────────
    def _load_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in IMAGE_LOAD_EXT)
        paths = filedialog.askopenfilenames(filetypes=[("PDF and images", patterns)])
        if paths:
            self.dispatch(lambda: self.model.load_files(list(paths)))

    def _delete_pages(self) -> None:
        if messagebox.askyesno("Delete pages",
                                "Delete the selected pages? This cannot be undone."):
            self.dispatch(self.model.delete_pages)

    def _export(self) -> None:
        name, folder = self.model.suggested_export_name()
        path_str = filedialog.asksaveasfilename(initialdir=folder or None, initialfile=name,
                                                  defaultextension=Path(name).suffix)
        if not path_str:
            return
        path = Path(path_str)
        if self.ui_config.confirm_overwrite and path.exists() and not messagebox.askyesno(
                "Overwrite?", f"{path.name} already exists. Overwrite?"):
            return
        if self.ui_config.remember_folder:
            self.model.settings.output_folder = str(path.parent)
        self.dispatch_job(lambda: self.model.export(path))

    def _pick_export_format(self, fmt: str) -> None:
        self.dispatch(lambda: self.model.set_export_format(fmt))

    # ── Settings / Help windows ───────────────────────────────────────────────
    def _open_settings(self) -> None:
        self._settings_win = build_settings_window(
            self.root, self.model.settings, self.ui_config, self.fonts,
            on_appearance=self._set_appearance, on_font_size=self._set_font_size,
            on_scale=self._set_scale,
            on_compress=lambda v: self.dispatch(lambda: self.model.set_compress_preset(v)),
            on_format=lambda v: self.dispatch(lambda: self.model.set_export_format(v)),
            on_undo_depth=lambda n: self.dispatch(lambda: self.model.set_undo_depth(n)))

    def _open_help(self) -> None:
        self._help_win = build_help_window(self.root, self.fonts)

    def _set_appearance(self, mode: str) -> None:
        self.ui_config.theme = mode
        ctk.set_appearance_mode(mode)

    def _set_font_size(self, size: int) -> None:
        self.ui_config.font_size = size
        self.fonts.resize(size)

    # ── Ctrl +/- UI scale (§15, §21), throttled via SCALE_THROTTLE_MS ─────────
    def _scale_step(self, direction: int) -> None:
        self._pending_scale = max(UI_SCALE_MIN, min(
            UI_SCALE_MAX, self.ui_config.ui_scale + direction * 0.05))
        if self._scale_after_id is not None:
            self.root.after_cancel(self._scale_after_id)
        self._scale_after_id = self.root.after(SCALE_THROTTLE_MS, self._apply_pending_scale)

    def _apply_pending_scale(self) -> None:
        self._scale_after_id = None
        self._set_scale(self._pending_scale)

    def _set_scale(self, scale: float) -> None:
        self.ui_config.ui_scale = max(UI_SCALE_MIN, min(UI_SCALE_MAX, scale))
        ctk.set_widget_scaling(self.ui_config.ui_scale)

    # ── shortcuts (§21) ────────────────────────────────────────────────────────
    def _is_typing_target(self) -> bool:
        return isinstance(self.root.focus_get(), tk.Entry)

    def _guarded(self, command: Callable[[], None]) -> Callable[[tk.Event[tk.Misc]], None]:
        """Wrap a page-nav/undo-redo shortcut so it yields to normal text-entry editing."""
        def _handler(_event: tk.Event[tk.Misc]) -> None:
            if not self._is_typing_target():
                self.dispatch(command)
        return _handler

    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind_all("<Control-o>", lambda _e: self._load_files())
        r.bind_all("<Control-Return>", lambda _e: self.dispatch(self.model.apply_crop))
        r.bind_all("<Control-s>", lambda _e: self._export())
        r.bind_all("<Control-z>", self._guarded(self.model.undo))
        r.bind_all("<Control-y>", self._guarded(self.model.redo))
        r.bind_all("<Left>", self._guarded(self.model.prev_page))
        r.bind_all("<Right>", self._guarded(self.model.next_page))
        r.bind_all("<Prior>", self._guarded(self.model.prev_page))
        r.bind_all("<Next>", self._guarded(self.model.next_page))
        r.bind_all("<Control-plus>", lambda _e: self._scale_step(1))
        r.bind_all("<Control-equal>", lambda _e: self._scale_step(1))
        r.bind_all("<Control-minus>", lambda _e: self._scale_step(-1))
        r.bind_all("<Control-0>", lambda _e: self._set_scale(1.0))
        r.bind_all("<Escape>", lambda _e: self.canvas_view.cancel_drag())

    # ── unexpected-exception recovery (spec §20; ARCHITECTURE §6) ─────────────
    def _handle_callback_error(self, exc: type[BaseException], val: BaseException,
                                tb: TracebackType | None) -> None:
        del tb
        self._current_job = None
        self.progress.hide()
        self.model.cancel_drag()
        self.refresh_all()
        messagebox.showerror(exc.__name__, str(val))


def main() -> None:
    root = ctk.CTk()
    SmartCropApp(root)
    root.mainloop()