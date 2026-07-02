# SmartCrop PDF — Architecture

Status: **proposed, not yet implemented** (Step-2 deliverable, revised). Defines the target
package layout, state ownership, the UI/core interface, threading model and error taxonomy —
before any Step 3/4 code.

`docs/SmartCrop_PDF_Specification.md` §4–§22 (behavior) is unchanged. Only §3 (Architecture &
modules) is obsoleted and will be rewritten to match this doc once approved (§11).

## 1. Why

`SmartCropApp` (`core/app.py` + 5 mixins) is one class with ~950 internal `self.*` references,
three places mutable state can live (plain attrs, `tk.Variable`s, widget display state synced by
convention), and business logic that directly mutates ~60 named CustomTkinter widgets. No
UI/core boundary exists. Full findings: Step-1 report in conversation.

## 2. Target package layout

```
main.py                  entry point only: ui.app_window.main()
core/                     Tk-free domain layer. A tkinter/customtkinter/ui import here is a
                          build failure (tests/test_architecture.py, §7).
  constants.py            DOMAIN tunables only (SRC_DPI, NORMAL_DPI, MODE_TEXT_MIN, DESKEW_MAX_DEG,
                           BORDER_FRAC, MIN_COMP_FRAC, DETECT_MAX_PX, CACHE_WINDOW, CLEAN_AMOUNT,
                           FULL_PAGE_FRAC, OFFSET_LIMIT, SYNTH_PAGES, DPI_PRESETS, COLOUR_MODES,
                           EXPORT_FORMATS, IMAGE_LOAD_EXT, JPEG_QUALITY).  UI tunables -> ui/constants.py
  enums.py geometry.py parsing.py imaging.py render.py viewmodel.py lru.py     unchanged
  errors.py        NEW    typed error taxonomy (§6)
  drag.py          NEW    DragState tagged union, replaces `_drag: dict` (§5.4)
  history.py       NEW    History — bounded undo/redo of DocumentState copies (§5.3)
  settings.py      NEW    Settings dataclass — live, non-undoable OUTPUT/behaviour settings that a
                           domain command consumes (compress, colours, format, folder, postfix,
                           undo_depth, dewarp_supersample) (§5.2)
  document_state.py NEW   DocumentState + Offsets + PageProcessIntent dataclasses; snapshot() (§5.1)
  batch.py         NEW    BatchJob protocol + BatchResult (Ok/Cancelled/Failed) + PageJob (the one
                           concrete job, parameterised by per-command closures) (§5.5)
  model.py         NEW    AppModel — the single facade: owns state, commands, queries (§5)
  detect.py        NEW    per-page content-box detection helpers (§8) — pure, stateless
  export.py        NEW    export job builders + per-page embed encoders (§12.5–§12.7)
  synthetic.py     NEW    the placeholder demo document (§1) — sizes, text boxes, rasters
ui/                NEW. May import core.*; core/ never imports ui/.
  app_window.py            AppWindow: root window, owns one AppModel, dispatch() (§6), drives
                           BatchJobs via root.after, report_callback_exception recovery, main()
  canvas_view.py            page canvas: paint from AppModel.view_snapshot(); Tk mouse events ->
                           page-unit coords -> model.begin_drag/update_drag/end_drag/cancel_drag
  overlay.py               progress overlay, driven by a BatchJob handle
  panels/
    crop.py                Split + Detect + Advanced(offsets) + Actions cards
    pages.py               Document + Pages-to-Process cards
    output.py              Scan-Processing + Compress + Export cards
  settings_window.py help_window.py widgets.py theme.py help_content.py
  config.py         NEW    UIConfig dataclass — runtime UI-only state that drives NO domain
                           computation: theme, font_size, ui_scale, confirm_overwrite,
                           remember_folder. Owned by AppWindow (§5.2).
  constants.py      NEW    UI tunables (HANDLE_R, HANDLE_SLACK, CANVAS_MARGIN, WINDOW_SIZE,
                           WINDOW_MIN, PANEL_WIDTH, SETTINGS_MIN_W, STATUS_IDLE_MS,
                           SCALE_THROTTLE_MS, UI_SCALE_MIN/MAX, FONT_SIZE_MIN/MAX/DEFAULT, THEMES)
tests/
  core/  conftest.py + per-module unit tests       no Tk; a `model` fixture (§8)
  ui/    conftest.py + wiring tests                withdrawn CTk root; a `window` fixture (§8)
  helpers.py            PDF/raster generators — Tk-free, reused (§8)
  test_pdf.py           REWRITTEN to drive AppModel, not DocumentMixin (§8)
  test_real_pdfs.py     unchanged (uses core.imaging only)
  test_architecture.py NEW import-graph guard (§7)
  assets/ bench/        unchanged
```

### File-by-file migration map

| Today | Becomes | Notes |
|---|---|---|
| `core/app.py` | `core/model.py` (state+history+commands) + `ui/app_window.py` (construction, shortcuts, scaling, main) | split by UI-ness |
| `core/document.py`, `detect.py`, `export.py` | `core/model.py` (+ `core/batch.py` for the batch jobs) | strip all widget/`messagebox` calls |
| `core/canvas.py` | `core/model.py` (hit-test, gesture, `view_snapshot()`) + `ui/canvas_view.py` (paint, event translation) | split |
| `core/ui_build.py` | `ui/panels/{crop,pages,output}.py`, `ui/{settings,help}_window.py`, `ui/overlay.py` | relocated, logic intact |
| `core/widgets.py theme.py help_content.py` | `ui/...` | moved as-is |
| `core/constants.py` | `core/constants.py` (domain) + `ui/constants.py` (presentation) | split |
| `core/geometry parsing render viewmodel lru enums imaging` | unchanged, stay in `core/` | already compliant |
| — | `core/{errors,drag,history,settings,document_state,batch,model}.py` | new |

## 3. State ownership model

**One owner: `AppModel`.** It holds exactly:

```
AppModel
 ├─ document : DocumentState      # the ONLY undoable state; replaced wholesale on Load/Reset/Undo
 ├─ settings : Settings           # session-long output/behaviour settings a domain command reads;
 │                                #   structurally outside History (§5.2)
 ├─ history  : History            # the undo/redo machinery (§5.3)
 ├─ drag        : DragState | None }  transient interaction state — per-gesture, NOT per-document.
 ├─ draw_rect   : Box | None      }  Lives on AppModel, never snapshotted. (Rule: if it isn't
 ├─ prev_applied: list[Box] | None}  snapshotted, it is not document state — so it isn't in
 ├─ source_cache: LRUCache        }  DocumentState.) Raster caches are rebuildable from
 └─ work_cache  : LRUCache        }  doc+rotation, so they're transient too.

AppWindow  (ui/, owns the one AppModel)
 ├─ ui_config    : UIConfig          # theme/font/scale/confirm-overwrite/remember-folder (§5.2)
 └─ _current_job : BatchJob | None   # the ONLY home of "is a batch running" (busy). AppModel never
                                     #   knows a job is running — it hands back a job and is done.
```

The defining rule, made structural: **`DocumentState` contains undoable fields and nothing
else.** There is no "frozen subset" twin to keep in sync — a `DocumentState.snapshot()` method
returns a deep copy of itself, and `History` stores those copies (§5.3). One schema, one place
to add a field.

No `tk.Variable` anywhere in `core/`. Every value that is a `DoubleVar`/`BooleanVar`/`StringVar`
today (offsets, anchors, keep-ratio, pages pattern, compress DPI, output colours, export format,
undo depth, ...) is a plain dataclass field. This is what makes the model testable headless and
is the direct fix for the top Step-1 finding.

No widget mirrors model state, and there is no `PanelState` struct. After every command the UI
re-reads the model and re-sets its own widgets unconditionally (the policy `render_page()`
already uses for the canvas, extended to the whole left panel) via
`AppWindow.refresh_all()`, which calls `panel.refresh(model, busy=self._current_job is not None)`.
Panels read **raw model properties** (`model.has_document`, `model.split_count`,
`model.auto_active`, `model.can_apply`, ...) and combine them with the window's `busy` flag to
compute their own widget enable/visible/highlight locally — that is wiring, not business logic,
and it keeps the interface narrow instead of forcing core to enumerate every widget's presentation
state. Two distinctions kept deliberate:
- *operation-validity* (domain, on the model: `can_apply`/`can_detect`) vs. *widget* facts (UI, in
  the panel: `same_size_row_visible` derived from `split_count in (2,4)`).
- *domain validity* (`can_detect`, pure — knows nothing about jobs) vs. *busy* (a UI fact owned by
  `AppWindow`). A control is enabled iff `can_X and not busy`; the model supplies `can_X`, the
  window supplies `busy`. The model never learns a batch is running (§5.5/§6), satisfying spec
  §14's "while busy, controls are disabled" without leaking job state into core.

No `hasattr(self, "btn_x")` construction-order guards: `AppModel` is fully built and testable
before `AppWindow` creates any widget, and no model method touches a widget, so "is the UI built
yet?" never arises in `core/`.

## 4. Dependency graph (target)

```
            core/  (zero tkinter / customtkinter / ui imports, ever)
              geometry parsing render viewmodel lru enums imaging constants   (pure leaves)
                         ▲      ▲       ▲
              errors  drag  history  settings  document_state  batch          (new, pure)
                         ▲──────┴────────┴───────────┴──────────┘
                                      AppModel  ◄── public surface = the interface (§5)
            ─────────────────────────────┼──────────────────────────  (one direction only)
            ui/  (imports core.*; core never imports ui.*)
              app_window  canvas_view  panels/{crop,pages,output}  overlay
              settings_window  help_window  widgets  theme
                                           │
                                        main.py
```

`core.render.output_image` stays the **one** image path, called from `AppModel` (export) and
`ui/canvas_view.py` (preview).

## 5. The explicit interface — `AppModel`

One implementation, so no Protocol/ABC. The contract: **`ui/` calls only public methods of
`AppModel` and reads only the frozen data objects they return; it never reaches past them.**
Enforced structurally (returned data objects are frozen) and mechanically (§7).

### 5.1 `DocumentState` (core/document_state.py)

```python
@dataclass(frozen=True)
class Offsets:                             # per-edge crop offsets, percent of page dim (§9)
    left: float = 0.0; top: float = 0.0; right: float = 0.0; bottom: float = 0.0

@dataclass(frozen=True)
class PageProcessIntent:                   # one page's scan-processing intent (§10) — typed,
    dewarp: bool = False                   #   replaces today's dict[int, dict]
    filter: tuple[FilterMode, int] | None = None     # (mode, strength) or None

@dataclass
class DocumentState:                       # exactly the 11 undoable fields — and nothing else
    applied: dict[int, list[Box]] = ...    # committed crop(s) per page — the saved state
    crop_rects: list[Box] = ...            # live split rectangles
    rotation: dict[int, int] = ...         # page → degrees CW
    processed: dict[int, PageProcessIntent] = ...
    detect_cache: dict[int, Box] = ...     # undoable (see note below)
    union: Box | None = ...                # undoable (see note below)
    auto_active: bool = ...
    offsets: Offsets = ...
    dewarp_on: bool = ...
    filter_mode: FilterMode = ...
    filter_strength: int = ...

    def snapshot(self) -> "DocumentState":
        """Return an undo copy: DEEP-copy the per-page maps/lists (applied, crop_rects, rotation,
        processed, detect_cache) and share the frozen scalars (offsets, union, enums, flags). `Box`
        is replaced, never mutated in place, so the shallow per-list copies are safe."""
```

**Field scope (narrowing decision).** This list is the *spec-snapshot set* — precisely the fields
spec §13 enumerates as captured by a snapshot, which is authoritative on what Undo reverts (only
crop / draw / rotate / dewarp / filter, §22 inv 4). The wider field list in earlier drafts of this
section (which also pulled in `doc`, `page_sizes`, `current_page`, `mode`, anchors, keep-ratio,
`split_count`, `same_size`, the pages selection, …) was over-inclusive: those values are **not**
undoable per the spec, so they live on `AppModel` directly, not in `DocumentState`. The rule
"`DocumentState` contains undoable fields and nothing else" is preserved — using the spec's
definition of "undoable." `drag`, `draw_rect`, `prev_applied`, the open `doc` and the raster caches
are likewise on `AppModel`, because they aren't snapshotted.

**Why keeping `doc` off the snapshot is sound (mutability).** `fitz.Document` is mutable in place,
so snapshotting a shared handle would be unsafe if any undoable command mutated it. It doesn't:
rotation is tracked in the `rotation` dict and applied to the rendered raster (never to `doc`), and
the only in-place `doc` mutation is `delete_pages`, which is **deliberately non-undoable** — spec
§13 lists the snapshotted ops (crop, draw, rotate, dewarp/filter) and delete is not among them; the
command clears history. So no surviving snapshot can ever observe a `doc` mutated underneath it.

**`detect_cache`/`union` are intentionally undoable.** They are part of the crop *setup*, so
undoing back past the Auto-detect that produced them correctly reverts the live auto-crop frame
(consistent with the crop state of that moment). **Auto-detect pushes exactly one snapshot per
press** (spec §13), so every detect — including the first — is a clean single Undo/Redo step that
restores both the detection state and any committed crops the press refreshed. The button stays a
stateless action (§7.4); only its result is undoable state.

### 5.2 `Settings` (core/settings.py) and `UIConfig` (ui/config.py)

The split criterion: **a value belongs in `core/Settings` iff a domain command reads it**; if it
only gates a dialog or styles a widget, it is UI and belongs in `ui/UIConfig`.

```python
# core/settings.py — every field is consumed by a domain command
@dataclass
class Settings:
    compress_preset: str = "Original resolution"   # -> render target size (_target_size)
    output_colours: str = "Original colors"        # -> render.output_image(remove_colours=)
    export_format: str = "PDF"                      # -> export() / ExportJob
    output_folder: str = ""                         # -> suggested_export_name()
    output_postfix: str = "_cropped"                # -> suggested_export_name()
    undo_depth: int = 4                             # -> History.set_depth
    dewarp_supersample: float = 2.0                 # -> dewarp imaging (§10.1)
```

```python
# ui/config.py — drives NO domain computation; owned by AppWindow
@dataclass
class UIConfig:
    theme: str = "Dark"                  # appearance only
    font_size: int = DEFAULT_FONT_SIZE   # widget font only
    ui_scale: float = 1.0                # CTk widget scaling only
    confirm_overwrite: bool = True       # gates a UI overwrite dialog before export
    remember_folder: bool = True         # UI policy: write the chosen folder back to Settings
```

`Settings` is mutated only via `AppModel` setters that validate (e.g. clamp `undo_depth`).
`History` has no reference to `Settings`, so "Compress DPI / Output colours survive Undo" (spec
inv. 22) is true by construction. `UIConfig` is mutated by `AppWindow` (font/scale applied live to
widgets; `confirm_overwrite`/`remember_folder` read at export time) and is invisible to `core/`.
(`theme`/`font_size`/`ui_scale`/`confirm_overwrite`/`remember_folder` were in `Settings` in the
prior draft — moved here because none feed a domain computation.)

### 5.3 `History` (core/history.py)

Not generic — there is one snapshot type ever, `DocumentState`:

```python
class History:
    def __init__(self, depth: int) -> None: ...
    def set_depth(self, depth: int) -> None: ...
    def push(self, state: DocumentState) -> None: ...     # stores state.snapshot(); clears redo
    def undo(self, current: DocumentState) -> DocumentState | None: ...   # None if empty
    def redo(self, current: DocumentState) -> DocumentState | None: ...
    @property
    def can_undo(self) -> bool: ...
    @property
    def can_redo(self) -> bool: ...
```

Flow: a mutating command calls `history.push(self.document)` (stores a pre-mutation copy) then
mutates `self.document` in place. `undo(current)` pushes a copy of `current` to the redo stack
and returns the popped undo copy, which `AppModel` assigns to `self.document` and then clears the
raster caches. The stack only ever holds copies; the live object is always unique.

### 5.4 `DragState` (core/drag.py) — replaces `_drag: Optional[dict]`

```python
@dataclass(frozen=True)
class AutoDrag:                       # resize (handle set) or move (handle None) the live auto-crop
    handle: str | None
    rect0: Box
    start: tuple[float, float]
    page_w: float; page_h: float
    offsets0: Offsets
    left_base: float; top_base: float

@dataclass(frozen=True)
class SplitDrag:
    idx: int; handle: str | None; rect0: Box; start: tuple[float, float]

@dataclass(frozen=True)
class DrawDrag:      start: tuple[float, float]
@dataclass(frozen=True)
class CropEditDrag:  start: tuple[float, float]

DragState = AutoDrag | SplitDrag | DrawDrag | CropEditDrag
```

`AppModel.begin_drag(px, py)` hit-tests (via `geometry.hit_handle`/`point_in_box`) against its
own overlay boxes and constructs the right variant — the dispatch that lives in
`canvas.py:_on_press/_press_auto/_press_split` today, moved into the model on page-unit coords
(no Tk event object).

### 5.5 `BatchJob` (core/batch.py) — the threading model

Single-threaded (CLAUDE.md: no threads/async for Tk/PyMuPDF; spec §14/§17). "Non-blocking to the
event loop" = cooperative stepping. `core/` owns the step semantics; `ui/` owns the scheduling.

```python
# core/batch.py
@dataclass(frozen=True)
class Ok: ...
@dataclass(frozen=True)
class Cancelled: ...
@dataclass(frozen=True)
class Failed:
    error: SmartCropError
BatchResult = Ok | Cancelled | Failed

class BatchJob(Protocol):
    title: str
    total: int
    done: int
    def step(self) -> None: ...        # do exactly one page; advance `done`
    def is_finished(self) -> bool: ...
    def cancel(self) -> None: ...
    def result(self) -> BatchResult: ...   # valid once finished
```

Commands that process pages **always return a `BatchJob`** (no `BatchResult | BatchJob` union —
that bifurcated every call site). A one-page job is a job whose `total == 1`; the driver
suppresses the overlay when `total <= 1` and otherwise shows it. Concrete implementation: a single
`PageJob` (one concrete `BatchJob` for all three cases — detect, scan dewarp/filter, and export),
parameterised by the model with a per-page `step_one` closure plus `on_success`/`on_abort` commit
and cleanup callbacks. Three near-identical job classes would be duplication; one mechanism + the
per-command closures the model already has is less code (LESS-IS-MORE), and the differences
(aggregate union / commit intents / save a file) live where they belong — in the model.

`ui/app_window.py`'s whole role for any long op: get the job, `root.after(1, drive)` where
`drive` calls `job.step()` once, repaints the overlay from `job.done/job.total` (skipping it when
`total <= 1`), reschedules until `is_finished()`; Cancel calls `job.cancel()`; on finish it
inspects `result()`. No business logic in the scheduler, no Tk in the job.

**Mid-batch failure is fail-fast (decided).** When a page's `step()` hits an `ImagingError` (or a
malformed-page error), the job transitions straight to finished with `result() == Failed(error)`
and **commits nothing** — consumers only apply results on `Ok`, so the document is untouched. The
driver renders `Failed.error` through the same `dispatch()` error path as any expected error. This
is not a new policy: it matches spec §14 ("a per-page exception … ends the batch cleanly") and
§20 ("the operation aborts, the document is untouched"). Skip-and-continue is explicitly rejected
— a half-detected/half-filtered document would violate the idempotency and crop invariants.

### 5.6 Commands and queries (representative; Step 3 completes from spec §7–§13)

```python
class AppModel:
    # document
    def load_files(self, paths: list[str]) -> None: ...      # raises DocumentLoadError
    def reset(self) -> None: ...
    def delete_pages(self) -> None: ...                       # raises EmptySelectionError / DeleteAllPagesError
    def rotate_pages(self) -> None: ...

    # crop / detect
    def detect_content(self) -> BatchJob: ...
    def set_anchor(self, left: bool | None, top: bool | None) -> None: ...
    def set_offset(self, edge: Literal["L","T","R","B"], value: float) -> None: ...
    def commit_offsets(self) -> None: ...                     # the snap-to-page-limit step (§9)
    def set_keep_ratio(self, on: bool, ratio: float | None = None) -> None: ...
    def set_split(self, n: int) -> None: ...
    def apply_crop(self) -> None: ...                         # raises InvalidSplitError / EmptySelectionError

    # gesture (page-unit coords from ui/canvas_view.py)
    def begin_drag(self, px: float, py: float) -> None: ...
    def update_drag(self, px: float, py: float) -> None: ...
    def end_drag(self) -> None: ...
    def cancel_drag(self) -> None: ...

    # scan processing
    def run_dewarp(self) -> BatchJob: ...
    def set_filter_mode(self, mode: FilterMode) -> BatchJob: ...
    def set_filter_strength(self, n: int) -> BatchJob: ...

    # pages / nav
    def set_pages_mode(self, mode: PagesMode) -> None: ...
    def set_select_pattern(self, pattern: str) -> None: ...
    def set_current_follow(self, on: bool) -> None: ...
    def next_page(self) -> None: ...
    def prev_page(self) -> None: ...
    def jump_to_output_page(self, n: int) -> None: ...

    # history / settings / output
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def set_compress_preset(self, name: str) -> None: ...
    def set_output_colours(self, mode: str) -> None: ...
    def set_export_format(self, fmt: str) -> None: ...
    def suggested_export_name(self) -> tuple[str, str]: ...   # (filename, folder) — pure, no dialog
    def export(self, path: Path) -> BatchJob: ...

    # queries — read-only, never raise on "nothing to show"
    def view_snapshot(self) -> ViewSnapshot: ...   # painted image, page w/h, overlay boxes (kind-tagged),
                                                    #   nav + status text — everything the canvas paints
    # raw state reads + operation-validity predicates that panels wire to widgets. These are PURE
    # domain validity — they know nothing about whether a batch is running ("busy" is the window's
    # fact, §3/§5.5; the panel ANDs `can_X` with the window's busy flag).
    @property
    def has_document(self) -> bool: ...
    @property
    def split_count(self) -> int: ...
    @property
    def auto_active(self) -> bool: ...
    @property
    def can_detect(self) -> bool: ...     # split==1 and >=1 anchor
    @property
    def can_apply(self) -> bool: ...      # has_document and (split==1 or len(crop_rects)==split)
    # ... mode, pages_mode, select_pattern, current_follow, offsets, keep_ratio, ratio,
    #     filter_mode, filter_strength, dewarp_on, same_size, compress_preset, output_colours,
    #     export_format, can_undo, can_redo  — all plain read-only properties.
    # NO `busy` property: the model returns a BatchJob and is done; it never tracks job lifetime.
```

`ViewSnapshot` is the one structured query result (frozen): it exists because the canvas needs a
coherent bundle to paint in one pass, and `kind`-tagging the overlay boxes lets the painter pick
colour/badge without re-deriving `auto_active`/`split_count` itself. The left panel needs no such
bundle — individual property reads suffice, so there is no `PanelState`.

## 6. Error taxonomy (core/errors.py)

```python
class SmartCropError(Exception): ...
class NoDocumentError(SmartCropError): ...
class EmptySelectionError(SmartCropError): ...
class InvalidSplitError(SmartCropError): ...           # wrong rectangle count at Apply
class DeleteAllPagesError(SmartCropError): ...
class DocumentLoadError(SmartCropError): ...            # malformed PDF/image; wraps the cause
class ImagingError(SmartCropError): ...                 # one page's imaging step failed in a batch
class MissingDependencyError(SmartCropError): ...       # docuwarp absent
```

`core/` raises these for every expected failure (spec §20) and never imports `messagebox`.
`ui/app_window.py` has two dispatch paths — one for plain commands, one for the `BatchJob`-returning
ones (`detect_content`, `run_dewarp`, `set_filter_mode`, `set_filter_strength`, `export`) — so both
type-check under mypy strict (a single `Callable[[], None]` wrapper could not accept a
`Callable[[], BatchJob]`):

```python
def dispatch(self, command: Callable[[], None]) -> None:
    try:
        command()                          # may raise SmartCropError (pre-flight validation)
    except SmartCropError as e:
        messagebox.showerror(type(e).__name__, str(e))
    self.refresh_all()

def dispatch_job(self, make_job: Callable[[], BatchJob]) -> None:
    try:
        job = make_job()                   # pre-flight (empty selection, etc.) may raise here
    except SmartCropError as e:
        messagebox.showerror(type(e).__name__, str(e))
        self.refresh_all()
        return
    self._start_job(job)                   # sets self._current_job, drives it (below)

def _start_job(self, job: BatchJob) -> None:
    self._current_job = job
    if job.total > 1:
        self.overlay.show(job)             # spec §14: a single-page job (total<=1) skips the overlay
    self.refresh_all()                     # busy now True -> controls disable
    self.root.after(1, self._drive)

def _drive(self) -> None:
    job = self._current_job
    if job is None:
        return
    if not job.is_finished():
        job.step()                         # exactly one page of work on the main thread
        self.overlay.update(job)
        self.root.after(1, self._drive)
        return
    self.overlay.hide()
    self._current_job = None               # busy now False
    result = job.result()
    if isinstance(result, Failed):         # mid-batch fail-fast (§5.5): nothing committed
        messagebox.showerror(type(result.error).__name__, str(result.error))
    self.refresh_all()
```

This is the only expected-error site, replacing today's 19 inline `messagebox` calls in business
logic; `busy` is exactly `self._current_job is not None`. Truly *unexpected* exceptions are not
caught here — they reach Tk's `report_callback_exception`, wired to a recovery handler equivalent
to today's `handle_callback_error` (clear `_current_job`/transient state, repaint, surface one
dialog), relocated to `ui/app_window.py` unchanged in behavior (it's inherently a Tk concept).

## 7. Enforcing the boundary mechanically

`tests/test_architecture.py` (written in Step 3): walk every `core/**.py` via `ast` (no import
needed) and fail if any module imports `tkinter`, `customtkinter`, or `ui`/`ui.*`; also assert
no `core.app`-style upward import reappears in `ui/`.

`pyproject.toml` `[tool.mypy]` strict, **zero overrides for `core/`**; one narrow override scoped
to the customtkinter-importing modules only:

```toml
[[tool.mypy.overrides]]
module = "customtkinter.*"
ignore_missing_imports = true
```

If `core/` ever needs that override, that's itself a build-time signal the boundary broke.

## 8. Testing strategy (target shape; detail in Step 3/4)

The existing SmartCropApp-based test infra is **in scope for rewrite, not carried over**:

- `tests/test_app.py` (the `app` fixture + ~100 god-object tests) is **deleted**. Its behaviors
  move down to `tests/core/` (pure, fast — most needed Tk only because state lived in
  `tk.Variable`s) and a much smaller `tests/ui/` (wiring only). Old tests asserting on private
  attribute paths or widget internals are rewritten against `AppModel`/`view_snapshot()` or
  dropped if dated — feature coverage against spec §22 is the bar, not literal assertions.
- `tests/conftest.py` gains a `model` fixture: build an `AppModel` over an in-memory `fitz`
  document (or the synthetic doc) — no display. `tests/ui/conftest.py` keeps a withdrawn
  `ctk.CTk()` `window` fixture for wiring tests, dialogs monkeypatched.
- `tests/helpers.py` PDF/raster generators (`make_sample_pdf`, `text_image`, `render_page_bgr`)
  are **Tk-free and reused as-is** — they never touched SmartCropApp.
- `tests/test_pdf.py` is **rewritten**: it currently imports `core.document.DocumentMixin` and
  calls `DocumentMixin._combine_files`, which ceases to exist — it will drive the equivalent
  `AppModel` command / combine helper instead.
- `tests/test_real_pdfs.py` is unchanged (imports `core.imaging` only).
- `hypothesis` added for `geometry.py`/`parsing.py` property tests (e.g. four `rotate_box_cw`
  applications restore the box — today checked at one fixed input).
- `pytest-cov` added; ≥90% on `core/`, ≥80% overall.
- Every spec §22 invariant has ≥1 test exercising it through `AppModel` directly.

## 9. Local CI-equivalent command (added Step 5; named now so Step 3 targets it)

```
mypy core ui && ruff check . && pytest --cov=core --cov=ui --cov-fail-under=80 -q
```

## 10. What does NOT change

Spec §4–§22 behavior verbatim; `render.output_image` as the one image path; main-thread-only
PyMuPDF/Tk; the crop-never-dropped invariant (§9.5/§12.4) and its stash-on-press/restore-on-noop
mechanism (relocated into `AppModel.begin_drag/end_drag`); all `docs/` sections except §3.

## 11. Follow-up after approval

`docs/SmartCrop_PDF_Specification.md` §3 still describes the mixin layout. Once this is approved
I'll rewrite §3 (module table + dependency rule) as its own small diff before Step 3 code. The
same diff adds the one-line §13 note that Auto-detect's result (`detect_cache`/`union`) is
undoable state (§5.1). Flagged so neither is silently skipped; not done pre-approval.
