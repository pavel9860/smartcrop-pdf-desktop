"""Integration tests for `SmartCropApp` (Test Spec §2). A withdrawn CTk root, no mainloop,
dialogs monkeypatched. Pure-logic invariants (split commits, keep-ratio, rotate/offset/delete
behaviour, dewarp/filters, classification, etc.) already have unit coverage against `AppModel`
directly in `tests/core/`; this file covers what only exists once `ui/` is wired up: dispatch's
single error-catch site, the batch-drive loop, layout/pinning, shortcuts, and UI-state recovery.

Lesson learned the hard way: `root.update()` in a tight loop does NOT reliably fire
`root.after(1, ...)`-scheduled callbacks, so batch jobs are driven by calling `app._drive()`
directly. `focus_get()` is unreliable on a withdrawn root, so typing-target checks monkeypatch it.
`event_generate()` + `root.update()` DOES reliably fire `bind_all` handlers on a withdrawn root.
"""
from __future__ import annotations

import customtkinter as ctk
import pytest

from core.batch import Cancelled, Ok
from core.constants import SYNTH_PAGES
from ui.app_window import SmartCropApp
from ui.constants import FONT_SIZE_MAX, UI_SCALE_MAX, UI_SCALE_MIN


@pytest.fixture(scope="module")
def root():
    """One Tk interpreter for the whole file — repeatedly creating/destroying `ctk.CTk()`
    instances destabilizes the Tcl interpreter on Windows (observed as a stray failure to
    fire `bind_all` handlers, escalating to a `tcl_findLibrary` crash after a real fitz
    document load). Each test gets a fresh `SmartCropApp` by clearing the root's children."""
    r = ctk.CTk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def app(root, monkeypatch):
    for child in root.winfo_children():
        child.destroy()
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr("ui.app_window.messagebox.showerror",
                         lambda title, msg: errors.append((title, msg)))
    monkeypatch.setattr("ui.app_window.messagebox.askyesno", lambda *a, **k: True)
    # customtkinter's global ScalingTracker walks every widget it has ever seen, including
    # ones from prior tests' torn-down SmartCropApp — it never unregisters a destroyed
    # DropdownMenu, so a real rescale crashes with a stale Tk-path TclError. Not our bug.
    monkeypatch.setattr("ui.app_window.ctk.set_widget_scaling", lambda v: None)
    a = SmartCropApp(root)
    a.errors = errors  # type: ignore[attr-defined]
    return a


def _pump(app: SmartCropApp, limit: int = SYNTH_PAGES + 5) -> None:
    """Drive the current job to completion via direct `_drive()` calls (see module docstring)."""
    for _ in range(limit):
        if app._current_job is None:
            return
        app._drive()
    raise AssertionError("job did not finish within the tick budget")


# ── construction / refresh ────────────────────────────────────────────────────────────────────
def test_construction_refreshes_nav_bar(app):
    assert app.lbl_total.cget("text") == f"/ {SYNTH_PAGES}"
    assert app.entry_page.get() == "1"


def test_refresh_all_disables_controls_while_busy(app):
    app._current_job = object()  # any non-None sentinel marks busy
    app.refresh_all()
    assert app.btn_prev.cget("state") == "disabled"
    assert app.entry_page.cget("state") == "disabled"
    app._current_job = None
    app.refresh_all()
    assert app.btn_prev.cget("state") == "normal"


# ── dispatch / dispatch_job — the only two SmartCropError catch sites ────────────────────────
def test_dispatch_runs_command_and_refreshes(app):
    app.dispatch(app.model.next_page)
    assert app.entry_page.get() == "2"


def test_dispatch_catches_smartcroperror_and_refreshes(app):
    def boom():
        from core.errors import EmptySelectionError
        raise EmptySelectionError("nope")
    app.dispatch(boom)
    assert app.errors == [("EmptySelectionError", "nope")]
    assert app.entry_page.get() == "1"  # state not stuck — refresh still ran


def test_dispatch_job_catches_error_from_make_job(app):
    def boom():
        from core.errors import NoDocumentError
        raise NoDocumentError("no doc")
    app.dispatch_job(boom)
    assert app.errors == [("NoDocumentError", "no doc")]
    assert app._current_job is None


# ── batch drive loop ──────────────────────────────────────────────────────────────────────────
def test_dispatch_job_places_progress_for_multi_page_job(app):
    app.dispatch_job(app.model.detect_content)
    assert app._current_job is not None
    assert app.progress.frame.winfo_manager() == "place"
    _pump(app)
    assert app._current_job is None
    assert app.progress.frame.winfo_manager() == ""


def test_failed_job_shows_error_and_clears_job(app, monkeypatch, tmp_path):
    monkeypatch.setattr("core.model.AppModel._render_page_outputs",
                         lambda self, i: (_ for _ in ()).throw(
                             __import__("core.errors", fromlist=["ImagingError"])
                             .ImagingError("boom")))
    app.dispatch_job(lambda: app.model.export(tmp_path / "out.pdf"))
    _pump(app)
    assert app._current_job is None
    assert app.errors and app.errors[0][0] == "ImagingError"


def test_cancel_before_first_tick_writes_no_file(app, tmp_path):
    path = tmp_path / "out.pdf"
    job = app.model.export(path)
    app._start_job(job)
    app._cancel_job()
    _pump(app)
    assert isinstance(job.result(), Cancelled)
    assert not path.exists()


def test_export_completes_and_writes_file(app, tmp_path):
    path = tmp_path / "out.pdf"
    job = app.model.export(path)
    app._start_job(job)
    _pump(app)
    assert isinstance(job.result(), Ok)
    assert app._current_job is None
    assert path.exists()


# ── error recovery (spec §20) ─────────────────────────────────────────────────────────────────
def test_handle_callback_error_unsticks_ui(app):
    app.dispatch_job(app.model.detect_content)
    assert app._current_job is not None
    app._handle_callback_error(ValueError, ValueError("kaboom"), None)
    assert app._current_job is None
    assert app.progress.frame.winfo_manager() == ""
    assert app.errors and app.errors[-1] == ("ValueError", "kaboom")
    assert app.btn_prev.cget("state") == "normal"


# ── auto-detect never highlighted ─────────────────────────────────────────────────────────────
def test_auto_detect_button_never_highlighted(app):
    before = app.panel.btn_detect.cget("fg_color")
    app.dispatch_job(app.model.detect_content)
    _pump(app)
    after = app.panel.btn_detect.cget("fg_color")
    assert before == after


# ── Redo label stays pure text (§19) ──────────────────────────────────────────────────────────
def test_redo_undo_reset_labels_have_no_glyph(app):
    assert app.btn_undo.cget("text") == "Undo"
    assert app.btn_redo.cget("text") == "Redo"
    assert app.btn_reset.cget("text") == "Reset"


# ── layout: nav bar / history buttons pinned (§7.8, #4) ───────────────────────────────────────
def test_nav_bar_is_not_inside_the_scroll_frame(app):
    assert app.nav_bar.master is not app.panel.scroll
    assert app.btn_undo.master.master is app.nav_bar


def test_history_row_directly_below_settings_help_row(app):
    rows = app.nav_bar.pack_slaves()
    settings_row = app.btn_settings.master
    history_row = app.btn_undo.master
    assert rows.index(settings_row) + 1 == rows.index(history_row)


# ── layout §6: Advanced collapsed by default, holds the offset steppers (#6) ─────────────────
def test_advanced_collapsed_by_default(app):
    assert app.panel.advanced_open is False
    assert app.panel.advanced_body.winfo_manager() == ""


def test_advanced_toggle_reveals_offset_steppers(app):
    app.panel._toggle_advanced()
    assert app.panel.advanced_open is True
    assert app.panel.advanced_body.winfo_manager() == "pack"
    for entry in app.panel.offset_entries.values():
        ancestor = entry
        while ancestor is not None and ancestor is not app.panel.advanced_body:
            ancestor = ancestor.master
        assert ancestor is app.panel.advanced_body


def test_actions_card_before_compress_card(app):
    actions_outer = app.panel.btn_crop.master.master
    compress_outer = app.panel.menu_compress.master.master
    siblings = app.panel.scroll.pack_slaves()
    assert siblings.index(actions_outer) < siblings.index(compress_outer)


# ── Settings at max font (#8) ─────────────────────────────────────────────────────────────────
def test_settings_window_builds_at_max_font(app):
    app.ui_config.font_size = FONT_SIZE_MAX
    app.fonts.resize(FONT_SIZE_MAX)
    app._open_settings()
    assert app._settings_win.winfo_exists()
    app._settings_win.destroy()


def test_help_window_builds(app):
    app._open_help()
    assert app._help_win.winfo_exists()
    app._help_win.destroy()


# ── load resets state (#3) ────────────────────────────────────────────────────────────────────
def test_load_files_dispatches_and_refreshes(app, monkeypatch, sample_pdf_path):
    monkeypatch.setattr("ui.app_window.filedialog.askopenfilenames",
                         lambda **k: (str(sample_pdf_path),))
    app._load_files()
    assert app.model.has_document
    assert app.model.input_paths == [str(sample_pdf_path)]


def test_load_files_no_selection_is_a_no_op(app, monkeypatch):
    monkeypatch.setattr("ui.app_window.filedialog.askopenfilenames", lambda **k: ())
    before = app.model.input_paths
    app._load_files()
    assert app.model.input_paths == before


# ── shortcuts (§21) ────────────────────────────────────────────────────────────────────────────
def test_ctrl_o_triggers_load_dialog(app, monkeypatch):
    called = []
    monkeypatch.setattr("ui.app_window.filedialog.askopenfilenames",
                         lambda **k: called.append(True) or ())
    app.root.event_generate("<Control-o>")
    app.root.update()
    assert called == [True]


def test_ctrl_s_triggers_export_dialog(app, monkeypatch):
    called = []
    monkeypatch.setattr("ui.app_window.filedialog.asksaveasfilename",
                         lambda **k: called.append(True) or "")
    app.root.event_generate("<Control-s>")
    app.root.update()
    assert called == [True]


def test_ctrl_enter_dispatches_apply_crop(app):
    app.root.event_generate("<Control-Return>")
    app.root.update()
    assert app.errors == []  # ran without raising; nothing to assert on the synthetic doc


def test_arrow_keys_navigate_when_not_typing(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: None)
    app.root.event_generate("<Right>")
    app.root.update()
    assert app.entry_page.get() == "2"


def test_arrow_keys_noop_while_typing_target_focused(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: app.entry_page._entry)
    app.root.event_generate("<Right>")
    app.root.update()
    assert app.entry_page.get() == "1"


def test_escape_cancels_drag(app, monkeypatch):
    called = []
    monkeypatch.setattr(app.canvas_view, "cancel_drag", lambda: called.append(True))
    app.root.event_generate("<Escape>")
    app.root.update()
    assert called == [True]


def test_is_typing_target_true_for_entry_focus(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: app.entry_page._entry)
    assert app._is_typing_target() is True


def test_is_typing_target_false_for_no_focus(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: None)
    assert app._is_typing_target() is False


# ── Ctrl +/- UI scale, throttled (§15, §21) ───────────────────────────────────────────────────
def test_scale_step_is_throttled_until_applied(app):
    start = app.ui_config.ui_scale
    app._scale_step(1)
    assert app.ui_config.ui_scale == start  # not applied yet — waiting on the throttle timer
    app._apply_pending_scale()
    assert app.ui_config.ui_scale == pytest.approx(start + 0.05)


def test_set_scale_clamps_to_bounds(app):
    app._set_scale(99.0)
    assert app.ui_config.ui_scale == UI_SCALE_MAX
    app._set_scale(-5.0)
    assert app.ui_config.ui_scale == UI_SCALE_MIN
