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
  test_imaging.py     UNIT  — raster processing
  test_pdf.py         INTEGRATION — generated PDF pipeline
  test_real_pdfs.py   INTEGRATION — user-provided native/scan PDFs (skip if absent)
  test_app.py         INTEGRATION — drives the real TestUIApp headlessly
```

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
  offset moves exactly one edge (no opposite-edge coupling).
- `rotate_box_cw`: maps `(x,y)→(h−y,x)` into the rotated `h×w` page, stays in-bounds; four
  applications return the original box (so rotation carries crops/detection, never drops them).

**parsing.py** (`test_parsing.py`)
- `pages_for_mode`: all / odd / even (1-indexed) / select; empty doc; unknown mode raises.
- `parse_selection`: singles, `a-b` inclusive ranges, **Python-style colon slices**
  `start:stop[:step]` (`1:4`, `1:100:5`, open-ended `::2`/`10:`/`:3`, negative step),
  mixes (`1:4, 8-9, 12`), reversed ranges, out-of-range dropped, duplicates collapse;
  too-many-colons / zero-step / empty raise.
- `parse_page_expr`: Python slices, negative index, step, zero-step + empty raise.

**imaging.py** (`test_imaging.py`)
- Sauvola threshold shape/dtype, ink/paper separation, odd-window coercion.
- `clean_document_bilevel`: strict {0,255}, strengths 1-3, upscale, blank page, dpi scaling,
  preserve-mask.
- `sharpen_grayscale`, `estimate_skew`+`deskew` round-trip, `deskew_auto`.
- `content_box` tight box / blank → None; `detect_picture_mask` textured vs blank.
- Dewarp: `unwarp_available` bool, ONNX int64 cast helper, live dewarp shape (skip if no
  docuwarp), missing-dependency RuntimeError (skip if installed).

## 2. Integration tests

**Generated/real PDFs** (`test_pdf.py`, `test_real_pdfs.py`)
- Build a 5-page PDF (3 vector + 2 scanned-with-skew); classify modes; deskew → bilevel →
  content-box pipeline on a rendered raster.
- User PDFs `tests/assets/test_pdf_native.pdf` (normal) and `test_pdf_scan.pdf` (scan):
  classification, vector content box, real dewarp shape, Sauvola detection **not** hitting the
  page border (regression for the full-page-crop bug).

**Live app** (`test_app.py`) — a withdrawn CTk root, no mainloop, dialogs monkeypatched:
- **Split → N×**: `set_split(2|4)` + `apply_crop` commits N boxes/page **in reading order**;
  `_output_images` yields N per page; total = N × page count.
- **Auto-detect not stuck**: after detect the button stays neutral (never the active accent)
  and `state == normal`; editing an offset and re-pressing detect still works.
- **Keep ratio**: after detect, `keep_ratio` + ratio → `_crop_rect` height = width/ratio.
- **Page pattern**: `1:3, 5` resolves to the right indices; the **Current** button selects the
  current page.
- **Rotate preserves crop**: `rotate_pages` keeps the committed crop, transformed by
  `rotate_box_cw` and in-bounds of the rotated page; rotate→undo restores box + angle.
- **Offset clamp**: typing 100000 then `_clamp_offsets` snaps each offset into ±100 and keeps
  `_crop_rect` inside the page; with no detection it just bounds to ±100.
- **Delete reindex**: deleting a middle page preserves the surviving pages' `applied`,
  `rotation`, and processed flags at their shifted indices and drops the deleted page's.
- **Failure paths**: delete-all refused, empty/out-of-range selection is a no-op, apply with
  fewer than N split rectangles commits nothing.
- **Reset**: `reset_document` clears detection and committed crops.
- **Defaults**: undo depth = 4.

## 3. Conventions
- No network; deterministic seeds in `helpers.py`.
- Each test owns its document; the big native book is only opened, never fully rendered.
- New behaviour → add a unit test for the pure part and, if it spans the UI, an integration
  test in `test_app.py`.

Run: `python -m pytest` · single file: `python -m pytest tests/test_app.py -q`.
