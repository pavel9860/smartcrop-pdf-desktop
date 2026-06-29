# CLAUDE.md — SmartCrop PDF

## Source of truth
`docs/SmartCrop_PDF_Specification.md` is the behavioral contract. Code conforms to it,
not the reverse. Any behavior change requires updating the spec FIRST, then tests, then
code — in that order, with sign-off on the spec diff before code changes start.

## Gates — must pass before every commit
```
mypy core ui && ruff check . && pytest --cov-fail-under=80 -q
```
All four in one line. If any fails, the commit is blocked. No exceptions.

## Hard rules (mechanical — not principles)
- `core/` never imports `tkinter`, `customtkinter`, or `ui` — enforced by
  `tests/test_architecture.py`. A violation is a CI failure, not a style note.
- Every `AppModel` public method has ≥1 test that uses only the public interface.
  No private attribute assertions in tests (`model.document.*`, `model.drag`, etc.).
- No function over 30 lines without a why-comment explaining why it cannot be split.
- Cyclomatic complexity > 10 is a `ruff C901` error — fix before committing.
- No magic numbers inline — all tunables in `core/constants.py` (domain) or
  `ui/constants.py` (presentation).
- `core/render.py` is the ONE image path for preview and export (WYSIWYG §12.1).
  Never add a second rendering path.
- Everything runs on the main thread (Tk/PyMuPDF requirement). No threads, no asyncio.
- `fitz` is PyMuPDF's import name — never let `pip install fitz` (wrong package) in.

## Architecture
See `ARCHITECTURE.md`. The file map, dependency rules, and state split are defined there.

## AppModel public interface (what ui/ calls — complete list)
```python
# document
load_files(paths: list[str]) -> None
reset() -> None
page_count() -> int
has_document: bool                    # property

# navigation
next_page() / prev_page() -> None
jump_to_output_page(n: int) -> None
view_total: int                       # property
view_position: int                    # property

# queries
view_snapshot() -> ViewSnapshot       # side-effect-free
can_detect: bool / can_apply: bool    # properties
can_undo: bool / can_redo: bool       # properties
auto_active: bool                     # property (reads document state)
offsets: Offsets                      # property
dewarp_on: bool                       # property
filter_mode: FilterMode               # property
filter_strength: int                  # property

# pages selection
set_pages_mode(mode: PagesMode) -> None
set_select_pattern(pattern: str) -> None
set_current_follow(on: bool) -> None
resolve_pages() -> list[int]

# crop / detect
detect_content() -> BatchJob
apply_crop() -> None
set_anchor(left: bool | None, top: bool | None) -> None
set_offset(edge: Literal["L", "T", "R", "B"], value: float) -> None
commit_offsets() -> None
set_keep_ratio(on: bool, ratio: float | None = None) -> None

# split
set_split(n: int) -> None
set_same_size(on: bool) -> None

# scan processing
run_dewarp() -> BatchJob
set_filter_mode(mode: FilterMode) -> BatchJob
set_filter_strength(n: int) -> BatchJob

# gestures (page-unit coords)
begin_drag(px: float, py: float, tol: float) -> None
update_drag(px: float, py: float) -> None
end_drag() -> None
cancel_drag() -> None

# history
undo() -> None
redo() -> None

# output settings (outside History — survive Undo)
set_compress_preset(name: str) -> None
set_output_colours(mode: str) -> None
set_export_format(fmt: str) -> None
set_undo_depth(depth: int) -> None

# export
suggested_export_name() -> tuple[str, str]
export(path: Path) -> BatchJob
```
In Step 4 sessions: read this block instead of all 1066 lines of model.py.

## ViewSnapshot fields (what canvas_view reads)
```python
image: Image.Image      # page raster or committed-crop output image
page_w: float           # coordinate space the overlay/draw_rect live in
page_h: float
overlay: tuple[OverlayBox, ...]   # empty on a committed page
draw_rect: Box | None             # live rubber-band
position: int           # 1-based output-page position
total: int              # output-page total
status: str             # e.g. "page 3 / 12" or "page 3 / 12  (page 2 split 1/2)"
```

## BatchJob protocol (what dispatch_job drives)
```python
title: str
total: int
done: int
step() -> None          # one page of work per call
is_finished() -> bool
cancel() -> None
result() -> Ok | Cancelled | Failed
```
`root.after` calls `step()` once per tick. Progress bar repaints after each tick via
`root.update_idletasks()`. Cancel before the first tick writes no file.

## Process
- Read CLAUDE.md + the ≤6 files actually needed for the task. Never load the whole
  codebase into a single session.
- Bug reports: diagnose root cause before fixing when the cause is ambiguous between
  two plausible sites.
- After any fix: re-verify all §22 invariants, not just the one related to the bug.
- Spec violations and correctness issues flagged directly — no softening or hedging.
- State confidence explicitly on non-obvious diagnoses: [high]/[med]/[low].
- Do not rewrite spec or test prose unrelated to the change.
- New behaviour → unit test for the pure part first; integration test in test_app.py
  if it spans the UI.

## Coherence checks — run at phase boundaries only
After Step 4 green, and before any public release. Feed the review loop these questions
across the full codebase:
1. Every function over 30 lines in core/ and ui/: is it doing one thing?
2. Every pair of functions across files doing the same thing differently.
3. Every public method on AppModel the UI never calls.
4. Every place core/ and ui/ share a concept under different names.
5. Every test asserting on private attributes.

## Style
Senior-level, compact. No explanatory preamble. No bullet lists unless the content is
genuinely enumerable. Numbers over adjectives. Confidence calibrated explicitly.
