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
    assert app.btn_next.cget("state") == "disabled"
    assert app.entry_page.cget("state") == "disabled"
    app._current_job = None
    app.refresh_all()
    assert app.btn_next.cget("state") == "normal"   # (Prev stays off: page 1 bound, inv 37)


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
    assert app.btn_next.cget("state") == "normal"   # (Prev stays off: page 1 bound, inv 37)


# ── auto-detect never highlighted ─────────────────────────────────────────────────────────────
def test_auto_detect_button_never_highlighted(app):
    before = app.panel.btn_detect.cget("fg_color")
    app.dispatch_job(app.model.detect_content)
    _pump(app)
    after = app.panel.btn_detect.cget("fg_color")
    assert before == after


# ── glyph-led labels end with the control's exact name (§19, inv 23) ─────────────────────────
def test_history_labels_glyph_led_and_end_with_name(app):
    for btn, name in ((app.btn_undo, "Undo"), (app.btn_redo, "Redo"), (app.btn_reset, "Reset")):
        text = btn.cget("text")
        assert text.endswith(name)           # tests key off the suffix, never the glyph
        assert text != name                  # glyph-led: something precedes the name


def test_action_labels_end_with_name(app):
    assert app.panel.btn_crop.cget("text").endswith("Crop")
    assert app.panel.btn_rotate.cget("text").endswith("Rotate")
    assert app.panel.btn_delete.cget("text").endswith("Delete")
    assert app.panel.btn_detect.cget("text").endswith("Auto-detect")


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


def _card_of(widget, siblings):
    """Climb to the ancestor that is one of the scroll frame's packed cards."""
    w = widget
    while w is not None and w not in siblings:
        w = w.master
    assert w is not None, "widget is not inside any packed card"
    return w


def test_actions_card_before_compress_card(app):
    siblings = app.panel.scroll.pack_slaves()
    assert siblings.index(_card_of(app.panel.btn_crop, siblings)) < siblings.index(
        _card_of(app.panel.menu_compress, siblings))


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
# `event_generate` for key events needs a mapped, focused window, which a withdrawn root does not
# reliably provide on every platform (fails under X11/xvfb). The bindings therefore route through
# `app.shortcut_actions` — tests assert the Tk binding exists, then invoke the action directly.

_SPEC21_SEQUENCES = ("<Control-o>", "<Control-Return>", "<Control-s>", "<Control-z>",
                     "<Control-y>", "<Left>", "<Right>", "<Prior>", "<Next>",
                     "<Control-plus>", "<Control-equal>", "<Control-minus>", "<Control-0>",
                     "<Escape>")


def test_all_spec21_shortcuts_are_bound(app):
    for seq in _SPEC21_SEQUENCES:
        assert seq in app.shortcut_actions, f"{seq} missing from shortcut map"
        assert app.root.bind_all(seq), f"{seq} has no Tk binding"


def test_ctrl_o_triggers_load_dialog(app, monkeypatch):
    called = []
    monkeypatch.setattr("ui.app_window.filedialog.askopenfilenames",
                         lambda **k: called.append(True) or ())
    app.shortcut_actions["<Control-o>"]()
    assert called == [True]


def test_ctrl_s_triggers_export_dialog(app, monkeypatch):
    called = []
    monkeypatch.setattr("ui.app_window.filedialog.asksaveasfilename",
                         lambda **k: called.append(True) or "")
    app.shortcut_actions["<Control-s>"]()
    assert called == [True]


def test_ctrl_enter_dispatches_apply_crop(app):
    app.shortcut_actions["<Control-Return>"]()
    assert app.errors == []  # no-source apply is a silent no-op (inv 25), never an error


def test_arrow_keys_navigate_when_not_typing(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: None)
    app.shortcut_actions["<Right>"]()
    assert app.entry_page.get() == "2"


def test_arrow_keys_noop_while_typing_target_focused(app, monkeypatch):
    monkeypatch.setattr(app.root, "focus_get", lambda: app.entry_page._entry)
    app.shortcut_actions["<Right>"]()
    assert app.entry_page.get() == "1"


def test_escape_cancels_drag(app, monkeypatch):
    called = []
    monkeypatch.setattr(app.canvas_view, "cancel_drag", lambda: called.append(True))
    app.shortcut_actions["<Escape>"]()
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


# ── no text on the page image; cursor read-out in the pane corner (§6, §19; inv 32) ───────────
def test_nothing_drawn_over_the_page_image(app):
    app.canvas_view.redraw()
    canvas = app.canvas_view.canvas
    text_items = [i for i in canvas.find_all() if canvas.type(i) == "text"]
    assert text_items == []                      # inv 32: the page image stays clean
    assert app.lbl_total.cget("text").startswith("/ ")   # n/total lives in the nav bar instead


def test_cursor_readout_label_fills_and_clears(app):
    import types
    view = app.canvas_view
    snap = view.redraw()
    assert view.coords_label.winfo_manager() == "place"  # pane corner, not the canvas
    assert view.coords_label.place_info()["anchor"] == "se"
    cx, cy = view._to_canvas(snap.page_w / 2, snap.page_h / 2)
    view._motion(types.SimpleNamespace(x=cx, y=cy))
    assert "x 50.0%" in view.coords_label.cget("text")
    assert view.coords_label.cget("text_color") == "#FFFFFF"
    view._pointer_left(types.SimpleNamespace(x=-1, y=-1))
    assert view.coords_label.cget("text") == ""


# ── hover nav arrows on the canvas edges (§6; inv 34) ─────────────────────────────────────────
def test_nav_arrows_appear_on_hover_and_navigate(app, monkeypatch):
    view = app.canvas_view
    assert view.btn_arrow_prev.winfo_manager() == ""       # hidden at rest
    view._show_arrows()
    assert view.btn_arrow_prev.winfo_manager() == "place"
    assert view.btn_arrow_next.winfo_manager() == "place"
    view.btn_arrow_next.cget("command")()                  # ▶ turns one page
    assert app.entry_page.get() == "2"
    holder = view.canvas.master
    monkeypatch.setattr(holder, "winfo_pointerxy", lambda: (999999, 999999))
    view._hide_arrows()
    assert view.btn_arrow_prev.winfo_manager() == ""


# ── progress overlay fully painted before the first heavy step (§14; bugs #8) ─────────────────
def test_overlay_painted_before_first_step(app):
    from core.batch import PageJob
    seen = []

    def step(_i):
        seen.append((app.progress.counter.cget("text"), app.progress.frame.winfo_manager()))

    job = PageJob("Slow work", [0, 1], step)
    app._start_job(job)
    _pump(app)
    assert seen[0] == ("0 / 2", "place")         # counter/bar painted and placed pre-step


# ── Advanced offsets: one line, all four visible (§7.4a; bugs #1) ─────────────────────────────
def test_offsets_on_one_line_and_compact(app):
    from ui.constants import OFFSET_FIELD_W, PANEL_WIDTH
    app.panel._toggle_advanced()
    rows = {e.master.master for e in app.panel.offset_entries.values()}
    assert len(rows) == 1                            # all four share one row container
    for e in app.panel.offset_entries.values():
        assert e.master.winfo_manager() == "pack"    # packed side by side, not gridded
        assert e.cget("width") == OFFSET_FIELD_W
    # 4 × (label 16 + gap 2 + entry) + 3 × 3 padding must fit the panel minus card chrome
    assert 4 * (16 + 2 + OFFSET_FIELD_W) + 9 <= PANEL_WIDTH - 44


def test_ratio_row_is_compact_and_field_wide(app):
    from ui.constants import PANEL_WIDTH, RATIO_FIELD_W, ROW_LABEL_W, SWITCH_W
    assert app.panel.entry_ratio.cget("width") >= RATIO_FIELD_W
    assert app.panel.switch_keep_ratio.cget("width") == SWITCH_W
    # label + switch + field + paddings fit the panel, so the field is never starved (#2)
    assert ROW_LABEL_W + SWITCH_W + RATIO_FIELD_W + 20 <= PANEL_WIDTH - 44


# ── navigation repaint uses the photo cache (§17; bugs #10) ───────────────────────────────────
def test_redraw_reuses_photo_for_same_page(app):
    app.canvas_view.redraw()
    first = app.canvas_view._photo
    app.canvas_view.redraw()                     # same page, same size → cache hit
    assert app.canvas_view._photo is first
    app.model.next_page()
    app.canvas_view.redraw()
    assert app.canvas_view._photo is not first   # different page → different bitmap


# ── Crop gating in the panel (§7.7; inv 25) ────────────────────────────────────────────────────
def test_crop_button_disabled_until_detect(app):
    assert app.panel.btn_crop.cget("state") == "disabled"
    app.dispatch_job(app.model.detect_content)
    _pump(app)
    assert app.panel.btn_crop.cget("state") == "normal"


def test_crop_button_enabled_by_drawn_window(app):
    assert app.panel.btn_crop.cget("state") == "disabled"
    app.model.begin_drag(50, 50, 3.0)            # draw a window (§9.4) — a crop source
    app.model.update_drag(250, 550)
    app.model.end_drag()
    app.refresh_all()
    assert app.panel.btn_crop.cget("state") == "normal"


# ── Settings / Help placement (§15, §16; inv 31) ───────────────────────────────────────────────
def test_settings_window_opens_at_main_top_left(app):
    app._open_settings()
    app._settings_win.update_idletasks()
    geo = app._settings_win.geometry()
    assert geo.endswith(f"+{app.root.winfo_rootx()}+{app.root.winfo_rooty()}")
    app._settings_win.destroy()


def test_help_window_opens_at_main_top_left_and_never_below_bottom(app):
    app.root.update_idletasks()                  # settle root geometry before capturing it
    app._open_help()
    app._help_win.deiconify()                    # CTkToplevel defers mapping; force it so the
    app._help_win.update()                       # requested geometry is actually applied
    geo = app._help_win.geometry()
    assert geo.endswith(f"+{app.root.winfo_rootx()}+{app.root.winfo_rooty()}")
    # inv 31: Help's outer bottom edge must not pass the main window's bottom edge. Outer top is
    # at rooty; add its own decoration + height and compare (headless WMs may report decoration
    # 0 — the assertion holds in both cases; the pixel truth is additionally screenshot-checked).
    height = int(geo.split("x")[1].split("+")[0])
    decoration = max(0, app._help_win.winfo_rooty() - app._help_win.winfo_y())
    help_bottom = app.root.winfo_rooty() + decoration + height
    main_bottom = app.root.winfo_rooty() + app.root.winfo_height()
    assert help_bottom <= main_bottom
    app._help_win.destroy()


def test_help_contains_about_with_version(app):
    from ui.constants import APP_VERSION
    from ui.help_content import SECTIONS
    assert SECTIONS[-1].title == "About"         # inv 36: last section, always present
    assert APP_VERSION in SECTIONS[-1].body
    app._open_help()                             # and the window builds with it
    assert app._help_win.winfo_exists()
    app._help_win.destroy()


# ── navigation disables at the bounds on every path (§7.8; inv 37) ────────────────────────────
def test_nav_disabled_at_bounds_via_every_path(app):
    assert app.panel is not None
    assert app.btn_prev.cget("state") == "disabled"          # page 1: Prev + ◀ off
    assert app.canvas_view.btn_arrow_prev.cget("state") == "disabled"
    assert app.btn_next.cget("state") == "normal"
    app.shortcut_actions["<Right>"]()                        # keyboard path refreshes states
    assert app.btn_prev.cget("state") == "normal"
    app.dispatch(lambda: app.model.jump_to_output_page(app.model.view_total))   # jump path
    assert app.btn_next.cget("state") == "disabled"          # last page: Next + ▶ off
    assert app.canvas_view.btn_arrow_next.cget("state") == "disabled"
    assert app.btn_prev.cget("state") == "normal"
    app.canvas_view._wheel_prev(None)                        # wheel path refreshes states
    assert app.btn_next.cget("state") == "normal"


def test_nav_disabled_both_ways_on_one_page_doc(app, tmp_path):
    import fitz
    p = tmp_path / "one.pdf"
    d = fitz.open()
    d.new_page(width=300, height=400)
    d.save(str(p))
    d.close()
    app.dispatch(lambda: app.model.load_files([str(p)]))
    assert app.btn_prev.cget("state") == "disabled"
    assert app.btn_next.cget("state") == "disabled"
    assert app.canvas_view.btn_arrow_prev.cget("state") == "disabled"
    assert app.canvas_view.btn_arrow_next.cget("state") == "disabled"
