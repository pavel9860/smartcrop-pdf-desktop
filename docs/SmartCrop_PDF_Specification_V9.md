# SmartCrop PDF — Build Specification

A desktop utility to crop, straighten, and clean PDFs and scanned documents for
e-readers. This document is the complete contract: an implementer can build the app
from it without other references. It defines architecture, UI, algorithms, state,
constraints, and acceptance invariants. No source code — logic and layout only.

## Contents
1. [Purpose & scope](#1-purpose--scope)
2. [Stack & dependencies](#2-stack--dependencies)
3. [Architecture & modules](#3-architecture--modules)
4. [Modes & classification](#4-modes--classification)
5. [Coordinate system](#5-coordinate-system)
6. [Window layout (console art)](#6-window-layout-console-art)
7. [Control reference](#7-control-reference)
8. [Auto-detect algorithm](#8-auto-detect-algorithm)
9. [Crop geometry & drag](#9-crop-geometry--drag)
10. [Scan processing pipeline](#10-scan-processing-pipeline)
11. [Pages selection](#11-pages-selection)
12. [Apply / export](#12-apply--export)
13. [History, reset, rotate](#13-history-reset-rotate)
14. [Progress overlay & threading](#14-progress-overlay--threading)
15. [Settings](#15-settings)
16. [Help](#16-help)
17. [Performance & memory](#17-performance--memory)
18. [Constants](#18-constants)
19. [Typography & theme](#19-typography--theme)
20. [Error handling & edge cases](#20-error-handling--edge-cases)
21. [Shortcuts](#21-shortcuts)
22. [Acceptance invariants](#22-acceptance-invariants)

---

## 1. Purpose & scope

Load a PDF, crop pages (auto-detected content box or manual rectangles, single or
2/4-up split), optionally dewarp/deskew/clean scanned pages, resize to a target device,
and export. Two workflows share one window; the scanned workflow adds a raster
processing stage. **Out of scope:** OCR/searchable text, thumbnail page picker, N×M
auto-grid split.

---

## 2. Stack & dependencies

Python 3.10+. GUI: **CustomTkinter** (Fluent/Windows-11-style themed widgets — rounded
cards, segmented buttons, switches, sliders, built-in UI scaling and Light/Dark/System
appearance modes) over a `tk.Canvas` for the page view. PDF: PyMuPDF (`pymupdf`, imported
as `fitz`). Imaging: OpenCV (`opencv-python`), NumPy, scikit-image, Pillow. Dewarp:
`docuwarp` + `onnxruntime` (optional; absence degrades to deskew-only).

UI scaling: `Ctrl +` / `Ctrl -` scale every widget live (`Ctrl 0` resets) via CTk's
`set_widget_scaling`. Accent and neutral colours come from a Fluent 2 palette; all button
labels stay legible in both Light and Dark modes.

Packaging note: the real PDF dependency is **`pymupdf`**; an unrelated PyPI package named
`fitz` also exists and must never be installed (it shadows PyMuPDF).

---

## 3. Architecture & modules

Pure, Tk-free core separated from UI for testability. Tkinter and all PyMuPDF document
mutation run **only on the main thread**; CPU-heavy imaging runs in worker threads on
prerendered numpy rasters.

```
pdf_cropper.py                entry point (creates root + app, runs mainloop)
smartcrop/
  __init__.py                 lazy export of the app class
  constants.py                ALL tunables, fonts, sizes, theme maps, strings
  imaging.py                  cv2/skimage primitives (pure ndarray→ndarray)
  core/
    pages.py                  page-selection parsing
    detect.py                 per-page content-box detection
    geometry.py               crop-rect ↔ per-edge offsets, drag back-out
    pipeline.py               scan intent → processed raster; raster cache (LRU)
    document.py               PDF I/O, crop/apply/export, rotate, history
  ui/
    widgets.py                Tooltip, ToggleSwitch, Segmented, ProgressOverlay
    panels.py                 section builders
    app.py                    orchestration & event wiring only
```

Dependency rule: `ui/*` → `core/*` → `imaging.py` → `constants.py`. No upward imports.

---

## 4. Modes & classification

On load, classify each page, then majority-vote (**bias Normal on ties**):

```
page_is_scanned = (len(text(page).strip()) < MODE_TEXT_MIN)
                  AND any(image on page with bbox area ≥ MODE_IMG_COVER · page_area)
mode = "scanned" if (#scanned·2 > #pages) else "normal"
```

| Mode | Crop unit | Stage chain |
|---|---|---|
| Normal | PDF points (vector clip) | detect → adjust → crop → resize → save |
| Scanned | raster px @ SRC_DPI | dewarp? → clean? → detect → adjust → crop → resize → save |

A clickable mode badge overrides the classification; toggling resets detection and the
raster cache.

---

## 5. Coordinate system

All geometry is expressed in **page units**: PDF points (Normal) or raster pixels at
`SRC_DPI` (Scanned). Canvas mapping:

```
canvas_x = page_x · scale + img_x      page_x = (canvas_x − img_x) / scale
scale    = min((cw − MARGIN)/page_w, (ch − MARGIN)/page_h)   # fit, preserve aspect
img_x,img_y = center the bitmap in the canvas
```

Offsets are **percent of the current page dimension** (resolution-independent). One
geometry/drag/render code path serves both modes.

---

## 6. Window layout (console art)

Two panes split by a draggable sash. Left = scrollable control stack with a **bottom bar
pinned** to the panel (packed before the scroll region, so it never floats and stays
visible on short windows). Right = page canvas with a **centered inline progress overlay**
and a bottom-right status strip. Scanned-only sections pack/unpack with no residual gap.

```
┌──────────────────────────────────┬───────────────────────────────────────────────┐
│ ┌ Document & State ───── [Normal] │                                             │  badge sits on
│ │ [          Load PDF          ]  │                                             │  the title line
│ │ [ ↩ Undo ][ Redo ↪ ][ ⟲ Reset ]│               page bitmap                  │  3 equal buttons
│ └────────────────────────────────│            + 8 diamond handles               │
│ ┌ Scan Processing ───────────────│            dashed = kept area                │  (scanned mode)
│ │ [      Dewarp + Deskew       ] │                                              │
│ │                                                				  │
│ │ [Filter B/W] [Grayscale Filter]│         ┌─────────────────────────┐          │  overlay shows
│ │  Strength                      │         │  Cleaning pages         │          │  only while busy
│ │ [   1  ] [   2   ]  [   3   ]  │         │  ▓▓▓▓▓▓▓░░░░░ 124 / 312 │          │
│ └────────────────────────────────│         │           [ Cancel ]    │          │
│ ┌ Split Into ─────────────────────│        └─────────────────────────┘          │
│ │ [ 1 ]  [ 2 ]  [ 4 ]            │   segmented; per-option tooltip on hover      │ 3-way segment
│ │ ◍ Same size                    │   toggle switch, like Anchor Left/Top (2 & 4) │
│ └────────────────────────────────│                                               │
│ ┌ Detect ─────────────────────────│                                              │
│ │ [        ✦ Auto-detect       ] │                                               │
│ │ ◌ Anchor Left    ◌ Anchor Top  │                                               │
│ │ ◌ Keep ratio  [field with ratio] │                                             │
│ │ L[ 0.0 ] T[ 0.0 ] R[ 0.0 ] B[ ]│   label inline with field; default font       │
│ │ [          ✕ Clear           ] │                                               │
│ └────────────────────────────────│                                               │
│ ┌ Pages ──────────────────────────│                                              │
│ │ [ All ][ Odd ][ Even ][Selected]│   four buttons always visible                │
│ │ Pattern [ 1,3,5-9           ]  │   field appears only under Selected           │
│ └────────────────────────────────│                                               │
│ ┌ Resize ─────────────────────────│                                              │
│ │ [  Original (No Resize)      ▾]│                                               │
│ └────────────────────────────────│                                               │
│ [   ✂ Apply Crop   ][  ↻ Rotate ]│                                              │
│ [          💾 Export PDF        ] │                                              │
│ ··············(scroll)···········│                                               │
│ ┌ bottom bar (pinned) ────────────│                               x 34.2% y 12.7%│  status strip
│ │ [ ⚙ Settings ][ ? Help ]       │                           ⬓ 41.0 × 58.3 %    │
│ │ [ ◀ ]  [ 3 ] / 312   [ ▶ ]        │                               page 3 / 312   │
│ └────────────────────────────────┴───────────────────────────────────────────────┘
```

---

## 7. Control reference

Every control carries a hover tooltip. Sections top→bottom; the bottom bar is pinned.

### 7.1 Document & State
| Control | Action | Behavior |
|---|---|---|
| Mode badge (title line) | toggle mode | Normal/Scanned; click flips, resets detection + raster cache, repaints |
| `Load PDF` (panel width) | open file | classify → set mode → init caches → clear history |
| `↩ Undo` `Redo ↪` `⟲ Reset` (equal width, always visible) | undo / redo / reset page | Undo/redo depth = `HISTORY_DEPTH`, covers dewarp/clean/crop/rotate; Reset reloads the current page from the pre-process cache |

### 7.2 Scan Processing *(scanned mode only)*
| Control | Action | Behavior |
|---|---|---|
| `Dewarp/Deskew` (toggle, highlight when on) | set dewarp intent | mesh unwarp + deskew over the Pages selection; always recomputed from the pre-process source (idempotent) |
| **Clean** block (bordered; title styled as a section title) | — | groups the clean controls |
| `B/W filter` / `Grayscale filter` (mutually exclusive, highlight active) | set clean mode | run over Pages selection; pressing the active one turns it off |
| `Strength (1)(2)(3)` (label styled as a section title) | set strength | 3 discrete levels; applies to whichever clean mode is active |

Nothing auto-runs; processing happens only on button press.

### 7.3 Split Into
`(1)(2)(4)` → N output pages. N>1 disables Detect, anchors, and offsets (manual split is
the crop source). Draw N rectangles in reading order; a numbered badge ①…④ is drawn
inside each.  Apply is enabled only when exactly N rectangles exist.
**Same size** is a toggle switch (styled like Anchor Left / Anchor Top), shown only in 2-
and 4-page modes. When ON, every split rectangle is kept the same size: dragging one box's
border resizes all of them to match on mouse release, anchored at each box's own corner.
Borders of a rect can be dragged by mouse, and the whole rectangle can be dragged too.
If Keep ratio is active the dragged rectangle is adjusted to its ratio on mouse release.
Each of the `1 / 2 / 4` segments shows its own tooltip on hover (single / side-by-side /
quadrants).

### 7.4 Detect
| Control | Action | Behavior |
|---|---|---|
| `✦ Auto-detect` | detect | per-page content box (§8); scanned mode shows the progress overlay |
| `Anchor Left` / `Anchor Top` (toggles) | re-render | left/top edge from detected text (ON) or page boundary (OFF) |
| `Keep ratio` (toggle) | — | editing R also sets B to hold the current page's detected aspect |
| `L T R B` spinboxes (font the same size like other elements; range ±100, step 0.1) | re-render | per-edge percent offsets |
| `✕ Clear` | clear | drop detection + offsets |

### 7.5 Pages — §11.  ### 7.6 Resize — `Original (No Resize)`, device/monitor presets, `Custom…` (W×H); applied last.
### 7.7 Actions — `✂ Apply Crop`, `↻ Rotate` (rotates pages, preserves cleaning).
### 7.8 Bottom bar — `⚙ Settings`, `? Help`, page nav `◀ n/total ▶`.

---

## 8. Auto-detect algorithm

Detection yields a **per-page content box** `B_p = (x0,y0,x1,y1)`; offsets and anchors
(§9) turn it into the crop rectangle. Per page over the Pages selection:

- **Normal:** union of text blocks (`get_text("blocks")`, type-0/text only):
  `x0=min bx0, y0=min by0, x1=max bx1, y1=max by1`. Pages with no text → page rect.
- **Scanned:** `content_box` on the page's cleaned ink mask (§10.4). If no ink → page rect.

Then aggregate across the selected pages to fix one size for the whole document:
```
gL = min(x0)   gT = min(y0)   gR = max(x1)   gB = max(y1)     # union span
W  = gR − gL   H  = gB − gT                                    # constant for ALL pages
```
Per-page boxes and the aggregates are cached; re-detect and page flips are free. `W` and
`H` are page-independent (the union span); §9 positions this fixed-size box per page.

`content_box(bilevel)` (robust to scan artifacts):
```
ink = bilevel < 128
components = connected_components(ink, 8-conn)
keep = components with area ≥ MIN_COMP_FRAC·page_area
              AND not touching the outer BORDER_FRAC margin   # drop scan-edge lines, punch holes, shadow
if keep is empty: keep = components with area ≥ MIN_COMP_FRAC·page_area   # fallback
box = bounding rectangle of kept pixels
```

Detection is non-destructive and deterministic; safe to re-run.

---

## 9. Crop geometry & drag

The crop rectangle for page `p` uses **per-page (or global-min) left/top** and the
**constant size** `W,H` from §8. `w,h` = page size; offsets are percent of page dim:

```
left   = (AnchorLeft ? B_p.x0 : gL) − L%·w        # ON: this page's text left; OFF: union-min left
top    = (AnchorTop  ? B_p.y0 : gT) − T%·h        # ON: this page's text top;  OFF: union-min top
right  = left + W + R%·w                           # size is constant; R grows it uniformly
bottom = top  + H + B%·h
clamp [left,top,right,bottom] to the page rect          # never outside the page
enforce right−left ≥ MIN_RECT and bottom−top ≥ MIN_RECT
```

Anchors affect only left/top (ON = this page's detected edge, OFF = union-minimum edge).
Width and height are the constant union span, so the box is the **same size on every
page**; R/B enlarge it uniformly. Consequence: on pages smaller than the union extent the
right/bottom edges carry margin by design — the cost of uniform output size. **Keep
ratio:** when R changes, set `B = ((W + R%·w)/ratio − H)/h·100`, with `ratio = W/H`.

**Drag** (auto mode): apply the cursor delta to the dragged handle's edge(s) of the
current page's rectangle, then write back each touched offset as a float in a single
trace-suppressed batch and render once:
```
L = (left_base − new.left )/w·100      R = (new.right  − (left_base + W))/w·100
T = (top_base  − new.top  )/h·100      B = (new.bottom − (top_base  + H))/h·100
```
One edge ↔ one offset ⇒ non-dragged borders are reproduced exactly; opposite-edge jitter
is structurally impossible. Manual/split rectangles are dragged directly in page units.

Handles: 8 diamonds (corners + edge midpoints), hit radius `HANDLE_R+slack`; cursors map
to resize directions; clicking outside any handle starts a new rectangle (and exits auto
mode in single-crop).

---

## 10. Scan processing pipeline

### 10.1 Raster layers (correctness core)
Per page, two cached rasters:
- `source[i]` — rendered once at `SRC_DPI`, **pre-process, immutable** (idempotency + Reset).
- `work[i]` — current processed raster, shown on canvas and cropped.

`work` is always derived **from `source`** through the current intent, so repeated presses
equal one press and re-cleaning starts from the un-cleaned image.

### 10.2 Intent → processed raster (single page, pure, thread-safe)
```
base = Dewarp_on ? dewarp(source) : deskew(source)         # deskew always runs (10.3)
work = clean=="bilevel" ? bilevel(base, strength)
     : clean=="gray"    ? sharpen_gray(base, strength)
     : base
```
Applied over the Pages selection (threaded, §14, §17).

### 10.3 Dewarp/deskew
Mesh unwarp (docuwarp/ONNX) plus deskew, as one control. To limit resampling blur:
**supersample ×DEWARP_SS → dewarp → downsample → unsharp(UNSHARP[strength])**. Without
docuwarp: deskew-only + a single warning. Deskew angle = `minAreaRect` of ink, normalized
to (−45,45], clamped to ±DESKEW_MAX_DEG; `deskew(img, angle)` straightens it (rotate by the
correction angle, white border fill).

### 10.4 Clean modes (each 3 levels)
- **B/W (bilevel):** illumination-flatten (divide by morphological-close background) →
  Sauvola threshold → connected-component despeckle. `strength → (sauvola_k, min_area)`.
- **Grayscale (sharpen):** illumination-flatten → bilateral denoise → unsharp mask; keeps
  continuous tone (photos survive). `strength → unsharp amount` (+ denoise radius).
- Pixel-defined kernels (Sauvola window, bg kernel, min area) scale by embedded DPI so
  150- and 600-DPI scans binarize comparably.

### 10.5 Processing is committed only on button press; detection and crop read `work`.

---

## 11. Pages selection

Four buttons always visible together: `All · Odd · Even · Selected` (1-indexed; Odd =
pages 1,3,5 → indices 0,2,4; Even = 2,4,6 → 1,3,5). **Selected** reveals an inline
**Pattern** field accepting a 1-indexed list with inclusive ranges, e.g. `1,3,5-9,12`; out-of-range values
are ignored. The resolved index set drives detect, dewarp, clean, apply, and rotate.

---

## 12. Apply / export

`Apply Crop` over the Pages selection (other pages copied unchanged):
- **Normal:** clip = the page's auto rectangle (§9) or manual rectangle(s); render via
  `show_pdf_page(clip)` into a new page → vector preserved. Split N → N pages.
- **Scanned:** crop the cached `work[i]` by the rectangle (px); Split N → N crops; embed
  each as an image page. Reuses processed rasters (no reprocessing).
- **Resize** applied last: `Original` keeps native size; preset/Custom resamples the crop.

`Export`: `save(garbage=4, deflate=True, clean=True)`.

---

## 13. History, reset, rotate

- **History:** doc-state stack, depth `HISTORY_DEPTH` (bounded for memory). Snapshot before
  any mutating op — crop, rotate, **and dewarp/clean** — so Undo reverts processing too.
- **Reset page:** reload the current page from `source[i]`; clears its `work`/detect cache.
- **Rotate:** rotate Pages-selected pages 90° CW in the document **and** rotate their cached
  `source`/`work` rasters 90° (do not discard) → cleaning survives rotation; subsequent
  re-clean still derives from `source`.

---

## 14. Progress overlay & threading

Long operations (auto-detect on scans, dewarp, clean, apply) show a **centered card on the
canvas** — message, determinate bar, page counter, Cancel — not a separate window.

Threading model: prerender required `source` rasters on the main thread; run per-page
imaging in a worker thread; post `progress/done/error/cancel` to a queue polled every
`PROGRESS_POLL_MS` by `after`. The main thread applies results and touches all Tkinter and
PyMuPDF-document state. Cancel sets a flag checked between pages. Controls disable while
busy; the status strip mirrors progress. Worker exceptions surface as an error dialog,
never crash the loop.

---

## 15. Settings

The Settings window sizes its height to its content (no blank space) and is positioned
near the main window. Every value-row uses a field/menu/switch; the colour scheme uses a
three-way segmented control with highlighter pictograms (☀ Light / 🌙 Dark / 🖥 System).

| Group | Setting | Notes |
|---|---|---|
| Appearance | Colour scheme | ☀ Light / 🌙 Dark / 🖥 System (segmented, applied live) |
| Appearance | Font size | menu of point sizes; rebuilds the shared (mutable) CTkFonts live |
| Appearance | Zoom (UI scale) | menu 80–200 %; same as `Ctrl +/-`. 100 % = the system display size |
| Output | Default resolution | preset list (no “2K monitor” entry) |
| Behaviour | Confirm before overwrite | default on |
| Behaviour | Remember last folder | reopen file dialogs there |
| Behaviour | Undo / redo depth | numeric field (default 2); bounds the history stack |
| Scan | Dewarp supersample | DEWARP_SS |
| Scan | Worker threads | batch parallelism (default = CPU count) |

Fonts use the **native system UI font** (`TkDefaultFont` family) so text matches the OS;
all sizes derive from one base and are reconfigured live by the Font size menu. Zoom is a
user multiplier on top of CustomTkinter's automatic system-DPI scaling, so the default
(100 %) already renders at the system's display size. **No Source DPI setting** — rendering
DPI is an internal constant.

There is **no export-image-format setting** — SmartCrop PDF is a pure-PDF tool; output is
always PDF.

---

## 16. Help

A standard help window: title bar, a one-line description at the top
("Crop, straighten, and clean PDFs and scans for e-readers."), then a **clickable table of
contents** at the top of a scrollable body. The TOC entries are buttons; clicking one
scrolls the body to that section (`yview_moveto` on the section's content offset) — the
content stays in the same window, no separate pane. Sections: Modes · Loading · Pages ·
Auto-detect & offsets · Scan processing · Split · Resize · Export · Shortcuts · About.
Concise prose, consistent heading style, a shortcut table, version/engine in About. Help
text renders one point larger than the rest of the UI.

---

## 17. Performance & memory

Target ≤ ~150 ms/page for clean/dewarp at `SRC_DPI`=200 on a laptop; batches run in
parallel.

| Lever | Action |
|---|---|
| Binarize | integral-image Sauvola (O(N)); single-pass component despeckle; binarize at native DPI (no global upscale) |
| Dewarp | cache the ONNX session process-wide; supersample only by `DEWARP_SS` |
| Batch | thread pool (`WORKERS`) over pages; render sources on main thread first |
| Apply | reuse cached `work`; encode once; no re-clean |
| Detection | cache per-page content box; re-press is free |

**Memory constraint:** raster caches are **LRU-bounded** to `CACHE_MAX_MB` total (source +
work). Prefetch a small window around the current page; evict least-recently-used pages.
Peak working-set must stay well under host RAM; never hold all pages uncapped.

---

## 18. Constants

All in `constants.py`; no literals in logic.

```
SRC_DPI = 200            HISTORY_DEPTH = 2          CACHE_MAX_MB = 1500
HANDLE_R = 8             HANDLE_SLACK = 5           MIN_RECT = 5
CANVAS_MARGIN = 36       PROGRESS_POLL_MS = 40      WORKERS = cpu_count()
MODE_TEXT_MIN = 8        MODE_IMG_COVER = 0.60
SAUVOLA_WINDOW = 51      BG_KERNEL = 51
STRENGTH_BILEVEL = {1:(0.06,20), 2:(0.11,40), 3:(0.18,90)}   # (sauvola_k, min_area px²)
UNSHARP = {1:0.6, 2:1.1, 3:1.6}                              # gray-sharpen amount
DESKEW_MAX_DEG = 15      DEWARP_SS = 2.0
BORDER_FRAC = 0.02       MIN_COMP_FRAC = 2.5e-4
RESOLUTIONS = ["Original (No Resize)", <e-reader/monitor presets…>, "Custom…"]
```
Fonts, paddings, sizes, and theme maps also live here.

---

## 19. Typography & theme

| Token | Value |
|---|---|
| Base UI font | `FONT_BASE` adjastable in settings, no elements with smaller font|
| Section-title font | LabelFrame titles **and** the "Clean" block title + "Strength" label |
| Offset spinbox font | `FONT_BASE` |
| Mono font | numeric/slice entries, help body |
| Themes | dark / light token maps: bg, panel(2/3), border, text, muted, accent, select, badge(normal/scan), handle, ok, warn, canvas |

Toggle switches and segmented buttons are custom-drawn; active segment/toggle uses the
`select`/accent tokens; disabled controls dim to `muted`.
The scale of the interface should be scale up and down with cntr+ cntrl-
The design should be aligned with mid 2026 design guides.

---

## 20. Error handling & edge cases

- No document loaded → actions are no-ops; nav shows `/ 0`.
- Empty Pages selection → warn, do nothing.
- Auto-detect with no text/ink anywhere → warn; leave prior state.
- Drag collapsing a rectangle → clamp to `MIN_RECT`; never invert.
- Crop rectangle clamped to page; degenerate clips skipped.
- Re-fetch a `Page` object after any document mutation (insert/rotate invalidate handles).
- Custom resolution non-positive/unparseable → error dialog, abort.
- docuwarp/onnxruntime missing → dewarp falls back to deskew-only with one warning.
- Worker exception → error dialog; busy state cleared; document untouched.
- Mode switch leaves no empty gap at the panel top; bottom bar stays pinned.

---

## 21. Shortcuts

`Ctrl+O` Load · `Ctrl+Enter` Apply Crop · `Ctrl+S` Export · `Ctrl+Z` Undo · `Ctrl+Y`
Redo · `←`/`→` and `PgUp`/`PgDn` previous/next page · page field `Enter` jumps.

---

## 22. Acceptance invariants

1. After Auto-detect with all offsets 0, each page's crop starts at its anchored top-left
   (per-page detected edge if anchored, else the union-minimum edge); `W` and `H` are the
   constant union span across the selection. Right/bottom hug text only on the page(s) that
   define the maximum extent; smaller pages carry margin (the cost of uniform size).
2. Dragging any handle leaves every non-dragged edge pixel-stable across the whole drag.
3. Repeated Dewarp/Clean presses produce the same `work` as one press (idempotent from source).
4. Undo reverts dewarp, clean, crop, and rotate; Reset returns the current page to `source`.
5. Rotate preserves applied cleaning.
6. Nothing in scanned processing runs without an explicit button press.
7. Crop rectangles never extend outside the page.
8. UI never blocks during batch processing; Cancel stops promptly; the overlay (not a
   window) reports progress for detect, dewarp, clean, and apply.
9. Resident memory stays within `CACHE_MAX_MB` for raster caches regardless of page count.
10. All PyMuPDF/Tkinter access is main-thread; workers touch only numpy/cv2 + prerendered rasters.
