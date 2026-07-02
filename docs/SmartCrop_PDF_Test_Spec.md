# SmartCrop PDF — Test Specification

Test strategy for the app. Every check below is **black-box against the public surface** —
`AppModel`'s public methods/properties, `ViewSnapshot`, and the widgets `SmartCropApp` exposes —
so the suite can confirm the application against the build spec **without reading its code**
(no private-attribute assertions; CLAUDE.md rule). Each §22 invariant of the build spec has at
least one test; the mapping is noted inline as *(inv n)*.

```
tests/
  helpers.py            PDF/raster generators (deterministic seeds)
  conftest.py           session fixtures (generated sample PDF)
  core/                 headless AppModel suites (no Tk):
    conftest.py           model / loaded / scanned fixtures + run_job (drives a BatchJob)
    test_model_document   load, combine, classify, reset (inv 17, 18)
    test_model_crop       detect, anchors, offsets, keep-ratio, detect-history (inv 1, 2, 7, 16, 19, 25, 27)
    test_model_gesture    draw-window, window drag, drop, cancel, committed-page edits (inv 13, 15, 24, 26, 28)
    test_model_split      split → N output pages, navigation, apply guards (inv 11)
    test_model_history    undo/redo/rotate/delete (inv 4, 5, 29)
    test_model_export     WYSIWYG, compress, colours, formats, embed encoders (inv 12, 20, 21, 22)
    test_model_coverage   split gestures, keep-ratio everywhere, edge cases, status (inv 3, 6, 19)
    test_model_pages, test_units, test_model_fixes   selection, unit conversions, regressions
  test_geometry.py      UNIT — crop math (pure)
  test_parsing.py       UNIT — page-selection parsing
  test_render.py        UNIT — the one crop/resize/desaturate path (inv 12)
  test_viewmodel.py     UNIT — output-page navigation math (inv 11)
  test_lru.py           UNIT — LRUCache bound (inv 9)
  test_enums.py         UNIT — Mode/FilterMode/PagesMode
  test_imaging.py       UNIT — Sauvola/deskew/content-box/dewarp primitives
  test_property.py      PROPERTY — hypothesis over geometry/parsing
  test_pdf.py           INTEGRATION — generated PDF pipeline
  test_real_pdfs.py     INTEGRATION — real native/scan PDFs (skip if absent)
  test_app.py           INTEGRATION — the real SmartCropApp, withdrawn root, dialogs patched
  test_architecture.py  GUARD — core/ never imports tkinter/customtkinter/ui (inv 10)
```

Run: `python -m pytest` from the repo root (gate: `mypy core ui && ruff check . &&
pytest --cov-fail-under=80 -q`). On a headless Linux box prefix with `xvfb-run -a`
(`test_app.py` needs a display server; key `event_generate` is avoided — shortcuts are asserted
via the binding table plus direct action invocation).

## 1. Unit layers (pure logic, no Tk)

**geometry** — `Box` algebra; `clamp_box` (inside unchanged / pulled in / min size);
`resize_by_handle` (each of 8 handles moves only its edges); `move_box` clamps, keeps size;
`hit_handle`/`point_in_box` tolerance; `union_box` = max-width × max-height at the top-left
corner (not bounding span); `auto_crop_rect` — constant W×H, per-edge offsets, overhang shifts
inward, never shrinks (inv 1, 2); `rotate_box_cw` — four turns round-trip (inv 5).

**parsing** — all/odd/even/selected; singles, `a-b`, Python slices `start:stop[:step]`, mixes;
out-of-range dropped; malformed input raises `ValueError` (the model resolves it to the empty
selection; §20).

**render** — `output_image` = crop → resize(target) → desaturate; `None` target keeps native
pixels; grayscale keeps tone (inv 12, 20, 22); `fit_scale` never overflows either axis (inv 14).

**imaging** — Sauvola bilevel strict {0,255} at 3 strengths; sharpen strengths drive denoise and
unsharp together; skew estimate/correction round-trip; `content_box` ignores border artefacts;
`unwarp_available` / `Int64Session` proxy; `unwarp_supersampled` honours the factor (inv 30).

**viewmodel / lru / enums** — output-page math (uncommitted = 1 view, committed split = N);
LRU eviction/recency (inv 9); str-backed enums.

## 2. Headless model suites (`tests/core/`)

The `model` fixture is the synthetic 24-page demo; `loaded(n)`/`scanned(n)` build real in-memory
PDFs; `run_job` steps any `BatchJob` to completion exactly as the window would.

Document: multi-file combine order, one page per image (inv 17); classification by vector data
(inv 18); Reset re-opens and clears everything (inv 4); load resets prior state.

Detect & crop: constant union size across the selection, inside the page (inv 1, 7); each offset
moves one edge (inv 2); offsets snap into range on commit; re-detect refreshes committed crops
and keeps out-of-selection crops (inv 16); **every detect press is one undoable snapshot,
first included** (inv 27); Crop with no source (no detection, no drawn window) is a no-op —
never full-page boxes (inv 25).

Drawn window (§9.4): a rubber-band creates a **live window** — page scale unchanged, nothing
committed, no history (inv 28); the window drags/resizes by its handles and interior; a new draw
replaces it; `Esc`/right-click outside a drag **drops** it, mid-drag cancel restores the exact
pre-drag state (inv 24); Crop commits it to its page only (inv 13), sourceless selected pages are
skipped (inv 25); undo restores the window; rotate turns it with the page (inv 29).

Committed pages: shown as saved; a stray click or degenerate band changes nothing; a valid band
tightens (undoable); a committed split page ignores window gestures entirely — only the
current output window can be tightened by a draw (inv 15, 26).

Split: 2/4 windows auto-created; drag/resize/same-size/keep-ratio on release; apply multiplies
output pages and navigation walks them in reading order (inv 11); rotate re-lays the grid on the
rotated page (inv 29); wrong rect count refuses to apply.

Scan processing: nothing runs without a press (inv 6); repeated presses idempotent from source
(inv 3); strength selectable before a filter is active; mid-batch failure commits nothing.

History: undo/redo cover crop, draw-commit, rotate, dewarp, filter at the configured depth
(inv 4); rotate preserves crops/filters, delete reindexes survivors (inv 5); output settings
survive undo (inv 22 corollary).

Export: WYSIWYG pixel equality preview↔export (inv 12); compress downsamples, `Original
resolution` keeps native (inv 20); PDF single file / JPG/PNG/TIFF one file per output page
(inv 21); grayscale output (inv 22); **PDF embeds JPEG for continuous-tone pages and PNG for
B/W-filtered pages** (§12.6); an uncommitted page with a drawn window or live auto crop exports
cropped (inv 15); cancel writes nothing (inv 8).

Edge cases (§20): malformed patterns (`0`, `abc`, `5-2`, `:::`) resolve empty and never crash;
navigation stops at both bounds; a draw beyond the page clamps to it; a tiny draw is discarded;
undo depth clamps to ≥ 1; a non-positive ratio never locks or crashes; delete-all refused; empty
selection raises; jump out of range is a no-op.

## 3. UI integration (`test_app.py`)

A withdrawn CTk root, no mainloop; dialogs monkeypatched; batch jobs pumped via the drive loop.

Wiring: dispatch is the single error-catch site and always refreshes; a failed/cancelled job
clears the busy state; the progress overlay is **placed and fully painted before the first heavy
step** and repaints per page (inv 8); callback-error recovery re-enables the UI (§20).

Layout: nav/history/Settings pinned outside the scroll area (§7.8); Advanced collapsed by
default, its four offset fields on **one packed line**, each `OFFSET_FIELD_W` wide — all four fit
the panel (§7.4a); the Keep-ratio row is compact (`ROW_LABEL_W`/`SWITCH_W`) so the ratio field
gets `RATIO_FIELD_W` (§7.4); Actions card precedes Compress (§6); Scan card only in scanned mode.

Canvas: the position text ("3 / 24", split annotation when relevant — no `page` prefix, no
coordinates) is drawn at the **bottom-left of the page image**, anchor `sw` (§6, §19); redraw
reuses the fitted-photo cache for an unchanged page and drops it on navigation (§17).

Controls: Crop disabled until a detection or a drawn window exists, enabled by either (§7.7);
Auto-detect never highlights (§19); glyph-led labels end with the control's name (inv 23);
Current follow highlights and tracks navigation (§11).

Shortcuts (§21): every sequence in the spec table has a Tk binding **and** its action behaves —
Ctrl+O opens the load dialog, Ctrl+S the export dialog, Ctrl+Enter applies, arrows navigate
unless an entry has focus, Esc cancels/drops via the canvas.

Windows: Settings and Help open aligned to the main window's top-left corner; Help matches the
main window's height (inv 31); Settings builds at `FONT_SIZE_MAX` without clipping (§15).

## 4. Conventions

- No network; deterministic seeds; each test owns its document.
- Public interface only — no `model.document.*` / `model.drag` assertions.
- New behaviour → unit test for the pure part first; UI-spanning behaviour → `test_app.py`.
- A behaviour change lands as: spec §-edit → test → code (CLAUDE.md order).
