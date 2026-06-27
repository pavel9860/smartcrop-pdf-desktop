# SmartCrop PDF — Test Specification

Test strategy for the flat-layout app. Two layers, both run by `pytest` from the repo root
(`python -m pytest`). Tests skip gracefully when an optional resource is missing (docuwarp,
a display, the large local PDFs), so the suite is portable.

```
tests/
  helpers.py          PDF generator + page-render helpers (shared)
  conftest.py         session fixtures (generated sample PDF)
  test_geometry.py    UNIT  — crop math
  test_parsing.py     UNIT  — page-selection parsing
  test_render.py      UNIT  — shared crop/resize/fit (WYSIWYG path)
  test_viewmodel.py   UNIT  — output-page navigation math
  test_lru.py         UNIT  — LRUCache eviction / recency
  test_enums.py       UNIT  — Mode/FilterMode/PagesMode
  test_imaging.py     UNIT  — raster processing
  test_pdf.py         INTEGRATION — generated PDF pipeline
  test_real_pdfs.py   INTEGRATION — user-provided native/scan PDFs (skip if absent)
  test_app.py         INTEGRATION — drives the real SmartCropApp headlessly
```

All modules are imported as `core.*` (the app is a package); the suite runs from the repo root
with `python -m pytest`.

## 1. Unit tests (pure logic, no Tk)

**geometry.py** (`test_geometry.py`)
- `Box`: width/height, equality, tuple.
- `clamp_box`: inside unchanged, negative origin pulled in, overflow clamped, min size.
- `resize_by_handle`: each of 8 handles moves only its edges; opposite edge fixed; min-size on
  over-drag; result always valid + on page.
- `move_box`: translate preserves size; clamps at edges.
- `hit_handle` / `point_in_box`: corner/edge hits, tolerance, all 8 handles hittable.
- `union_box`: size = max(width)/max(height), **not** bounding span; position = top-left corner.
- `auto_crop_rect`: constant W×H across pages; anchor ON = page edge / OFF = union edge; each
  offset moves exactly one edge (no opposite-edge coupling); a frame that would overhang is
  **shifted inward (opposite edge extends), never shrunk** (§9.2) — only `W`/`H` larger than the
  page shrinks.
- `fit_box_keep_size`: shift-to-fit preserving size; shrink a side only when the box is bigger
  than the page in that axis.
- `rotate_box_cw`: maps `(x,y)→(h−y,x)` into the rotated `h×w` page, stays in-bounds; four
  applications return the original box (so rotation carries crops/detection, never drops them).

**parsing.py** (`test_parsing.py`)
- `pages_for_mode`: all / odd / even (1-indexed) / select; empty doc; unknown mode raises.
- `parse_selection`: singles, `a-b` inclusive ranges, **Python-style colon slices**
  `start:stop[:step]` (`1:4`, `1:100:5`, open-ended `::2`/`10:`/`:3`, negative step),
  mixes (`1:4, 8-9, 12`), reversed ranges, out-of-range dropped, duplicates collapse;
  too-many-colons / zero-step / empty raise.
- `parse_page_expr`: Python slices, negative index, step, zero-step + empty raise.

**render.py** (`test_render.py`)
- `crop_to_box`: page-unit box → correct pixel crop; `resize_to`: None/equal are identity,
  else resamples; `output_image`: crop-then-resize matches the DPI target and keeps native crop
  size for `None` (Original resolution); **Output colours = Grayscale** desaturates (tonal range
  preserved — no thresholding, no forcing ink to pure black) and is a no-op for `Original colours`;
  `fit_scale` picks the limiting dimension **and never overflows the canvas in either axis** (page
  always inside the window, many page/canvas aspects).
- DPI→target: a crop's pixel target = `dpi/72 · crop-size-in-points` for High/Medium/Low; `None`
  for Original resolution.

**viewmodel.py** (`test_viewmodel.py`)
- `page_box_count` (uncommitted=1, committed split=N), `view_total` over a mixed doc,
  `view_position` flat index + stale-`view_box` clamp, `flat_to_page_box` round-trips the whole
  sequence and clamps out-of-range to the last page.

**lru.py** (`test_lru.py`)
- LRU eviction on insert past `maxsize`; `get`/re-`set` refresh recency; full dict API
  (`in`/`pop`/`clear`); `maxsize<=0` is unbounded.

**enums.py** (`test_enums.py`)
- `Mode`/`FilterMode`/`PagesMode` values; str-backed equality + singleton members; the pure
  parser accepts a `PagesMode` directly (no boundary conversion).

**imaging.py** (`test_imaging.py`)
- Sauvola threshold shape/dtype, ink/paper separation, odd-window coercion.
- `clean_document_bilevel` (B/W filter): strict {0,255}, strengths 1-3, upscale, blank page,
  dpi scaling.
- `sharpen_grayscale` (Sharpen filter): single-channel output, all 3 strengths run, and
  **strength drives the denoise/unsharp** — not only the caller-set `amount` (regression: the old
  code held denoise fixed, so a hard sharpen amplified scan noise); `_GRAY_STRENGTH` monotonic.
- `estimate_skew`+`deskew` round-trip, `deskew_auto`.
- `content_box` tight box / blank → None.
- Dewarp: `unwarp_available` bool, `Int64Session` proxy (casts int32→int64, delegates the rest,
  leaves the real session unmutated), live dewarp shape (skip if no
  docuwarp), missing-dependency RuntimeError (skip if installed).

## 2. Integration tests

**Generated/real PDFs** (`test_pdf.py`, `test_real_pdfs.py`)
- Build a 5-page PDF (3 vector + 2 scanned-with-skew); classify modes (Normal when any page has
  vector data; Scanned only when every page is image-only); deskew → bilevel → content-box pipeline
  on a rendered raster.
- **Combine inputs** (`DocumentMixin._combine_files`): a mix of a PDF plus image files
  (jpg/png/tiff) builds one document — PDF pages then one page per image — preserving selection
  order. Per-page classification is by **vector data** (native if text ≥ `MODE_TEXT_MIN` or any
  `get_drawings()` path, image-only otherwise) — no image-cover heuristic.
- User PDFs `tests/assets/test_pdf_native.pdf` (normal) and `test_pdf_scan.pdf` (scan):
  classification, vector content box, real dewarp shape, Sauvola detection **not** hitting the
  page border (regression for the full-page-crop bug).

**Live app** (`test_app.py`) — a withdrawn CTk root, no mainloop, dialogs monkeypatched; the
class under test is **`SmartCropApp`** (composed from the ui_build/document/detect/canvas/export
mixins):
- **Split → N×**: `set_split(2|4)` + `apply_crop` commits N boxes/page **in reading order**;
  `_output_images` yields N per page; total = N × page count.
- **Bounded memory**: visiting every page keeps `len(_source_cache)`/`len(_work_cache)` ≤
  `CACHE_WINDOW`; a multi-page export streams to the right page count and leaves caches bounded;
  a single-page export takes the synchronous path; cancelling before the first tick writes no
  file. (Multi-page export tests pump `root.update()` since the batch runs via `after`.)
- **Split preview navigation**: after a committed N-split, `_view_total()` = N × page count
  (uncommitted = one view/page); `next_page`/`prev_page` walk every (source, split) pair in
  reading order; the page entry jumps by output index; re-opening a page for edit resets the
  split view index.
- **WYSIWYG**: with a Compress DPI (and with Output colours = Original/Grayscale), the preview
  image (`render.output_image`) equals the export image (`_output_images`) in size and pixels.
- **Compress**: a High/Medium/Low DPI resamples `_output_images` to the DPI-derived pixel size and
  the written file is no larger than a plain re-save at that DPI; `Original resolution` keeps native
  crop pixels.
- **Output colours**: with `Grayscale` selected, every `_output_images` page is grayscale
  (single-channel or R==G==B) with its tonal range preserved (not thresholded, ink not forced to
  pure black); `Original colours` is a no-op.
- **Output colours / Compress DPI excluded from history**: `_capture()`/`_restore()` do not read or
  write the DPI or Output-colours state; toggling either, then Undo (or Reset), leaves the setting
  exactly as the user set it while still reverting crop/filter/rotate state.
- **Export formats**: PDF writes one file; JPG/PNG/TIFF write one file per output page with an
  index suffix; the suggested name uses the format's extension and the output postfix.
- **Keep ratio (all cases)**: the `height = width/ratio` lock holds for the live auto crop, a
  handle drag, an offset edit, a hand-drawn rectangle and a split rectangle (no gesture bypasses it).
- **Per-page draw**: committing a rubber-banded rectangle writes only that page's `applied`,
  leaves every other page's `_crop_rect` unchanged, and is undoable (snapshots history).
- **Error recovery**: `handle_callback_error` clears `_busy`/`_suspend` and re-enables controls
  (no stuck UI) after an unexpected callback exception.
- **Auto-detect not stuck**: after detect the button stays neutral (never the active accent)
  and `state == normal`; editing an offset and re-pressing detect still works.
- **Page pattern**: `1:3, 5` resolves to the right indices (see the Current follow toggle below).
- **Rotate preserves crop**: `rotate_pages` keeps the committed crop, transformed by
  `rotate_box_cw` and in-bounds of the rotated page; rotate→undo restores box + angle.
- **Offset clamp**: typing 100000 then `_clamp_offsets` snaps each offset into ±100 and keeps
  `_crop_rect` inside the page; with no detection it just bounds to ±100.
- **Delete reindex**: deleting a middle page preserves the surviving pages' `applied`,
  `rotation`, and processed flags at their shifted indices and drops the deleted page's.
- **Failure paths**: delete-all refused, empty/out-of-range selection is a no-op, apply with
  fewer than N split rectangles commits nothing.
- **Crops persist across detect**: re-running `detect_content` keeps crops on pages **outside**
  the detected selection, so two page-sets can be cropped with two patterns. (The **Clear** button
  and `clear_detect` were removed — re-detect / draw replace freely, no Clear needed, #7.)
- **Auto-detect works after a crop (crop kept)**: re-detecting a committed page *refreshes* its
  `applied` box to the fresh auto crop (never drops it: page stays in `_applied`), and is undoable;
  pages outside the selection keep their crops.
- **A crop is never dropped except by Undo/valid-replace**: on a committed page, editing happens
  **within the cropped view** (option a, §9.3) — a press does **not** flip to the full page; a
  press+release with no drag, or a band smaller than `2·MIN_RECT`, leaves the committed crop
  unchanged (`_commit_crop_edit`); a valid band **tightens** it (mapped into the committed box,
  undoable); an uncommitted page's draw commits straight to `applied` (`_commit_drawn_rect`, §9.4).
- **Cancel a drag (#24)**: `_cancel_drag` (Esc / right-click) discards an in-progress draw or split
  drag, commits nothing, takes no history snapshot, and rolls back live offsets / split mutations
  so the crop is exactly as before.
- **Export never drops a visible crop**: with a live auto crop and no Apply, `_output_images` of an
  uncommitted page is cropped (not whole); with one page hand-drawn, `export` still commits/crops
  every other selected page (the drawn page keeps its own box).
- **Wheel turns pages**: `_on_canvas_wheel` up/down moves to the previous/next page (never zooms).
- **Progress paints immediately**: `_show_progress` forces a paint (and is placed); `_run_batch`
  flushes the bar/counter redraw per page so progress is smooth, not fragmental.
- **Redo label**: `btn_redo` leads with its glyph (the word "Redo" is not the clipped edge char).
- **Split overrides stale crop**: switching `set_split` clears the previous mode's committed
  crops; after "normal crop → Split 2" the commit yields N boxes/page and `_output_images`
  totals N × page count.
- **Current follow toggle**: pressing switches to Selected, fills Pattern, and **highlights**
  (`btn_current` fg == ACCENT); pressing again un-highlights and keeps the pattern; while ON the
  pattern tracks `next_page`/`prev_page`; switching mode or a manual `_on_pattern_typed` ends it.
- **Multi-file load & classify** (#17, #18): `_open_files([pdf, img, …])` concatenates into one
  document — PDF pages then one page per image, in selection order — records `_input_paths`, and
  sets the mode (any native page → Normal; all image-only → Scanned). `reset_document`
  re-combines the same `_input_paths` and clears crops.
- **Reset**: clears detection and committed crops, **returns Split to 1** (segment + rects),
  and **drops the scan/Current highlights** (B/W, Sharpen, Dewarp, Current back to neutral); the
  Compress DPI and Output colours settings are untouched (live, not document state).
- **Nav bar pinned**: the Settings/Help+nav card's master is the left panel, not the scroll
  frame (so it can't float under Export or need scrolling); no spacer/reflow machinery.
- **History buttons pinned (§7.8, #4)**: `btn_undo`/`btn_redo`/`btn_reset` live in the pinned
  bottom card (master chain → `_nav_bar`), directly below Settings/Help — not in the Document card.
- **Layout §6 (#6)**: a collapsible **Advanced** card (`btn_advanced`, `advanced_open` False by
  default) holds the four offset steppers (`_off_spins`, ancestors include `advanced_body`),
  separate from Detect Text Borders; **Actions** (Crop full-width + Rotate/Delete) and the
  **Export** split button are separate cards, Actions before Compress.
- **Load resets state (#3)**: `_open_files` clears `_applied`/`_rotation`/`_detect_cache`/`_union`/
  `auto_active`/`dewarp_on` — the same guarantee as Reset.
- **Settings at max font (#8)**: `open_settings` builds at `FONT_SIZE_MAX` without error; rows size
  to content (no fixed-width clip), the window grows to fit (skips if no headless toplevel).
- **Split keep-ratio (#9)**: a split window dragged with Keep ratio on snaps to the **ratio field**
  (`_active_ratio`) on release, not its own initial aspect.
- **Defaults**: undo depth = 4.

## 3. Conventions
- No network; deterministic seeds in `helpers.py`.
- Each test owns its document; the big native book is only opened, never fully rendered.
- New behaviour → add a unit test for the pure part and, if it spans the UI, an integration
  test in `test_app.py`.

Run: `python -m pytest` · single file: `python -m pytest tests/test_app.py -q`.
