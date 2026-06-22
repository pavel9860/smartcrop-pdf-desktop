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

Flat layout in the repo root — pure, Tk-free logic modules sit next to the UI modules, with
`main.py` as the **single** entry point. Pure logic is unit-tested; the UI is integration-
tested via a headless `TestUIApp`.

```
main.py            entry point — the ONLY starter (python main.py)
app.py             TestUIApp: orchestration, panels, event wiring, main()
widgets.py         ToolTip, Spin
theme.py           colour palette (warm-gray chrome + blue accent)
help_content.py    help sections + tooltip text
geometry.py        Box, crop-rect math, drag/resize/move, union_box + auto_crop_rect   ┐ pure,
imaging.py         cv2/numpy primitives (Sauvola clean, deskew, content_box, dewarp)    │ Tk-free
parsing.py         page-selection parsing (all/odd/even/ranges/slices)                  │
constants.py       resolutions + dark/light canvas theme tokens                         ┘
tests/             unit + integration (see Test Specification)
core/              previous versions (legacy ttk) + docs/
old/               this version's scratch (logs, algorithms_test)
.gitignore  pyproject.toml  requirements.txt  README.md
```

Dependency rule: `main.py / app.py / *ui modules` → `geometry / imaging / parsing /
constants`. No upward imports. Tkinter and PyMuPDF document mutation run **only on the main
thread**; CPU-heavy imaging runs in worker threads on prerendered numpy rasters. Run with
`python main.py`. Unhandled Tk-callback exceptions are caught by a global handler and shown
in a dialog rather than crashing.

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

Two panes split by a draggable sash. Left = a single **scrollable control stack** ending
with the Settings/Help + page-nav card. That last card is **anchored to the panel bottom
when the column is shorter than the viewport** (a flexible spacer above it grows to fill the
gap, so it sits at the bottom instead of floating right under Export PDF); when the column
overflows the viewport the spacer collapses to nothing and the card scrolls into reach like
any other card (partially/fully hidden until scrolled to). The panel keeps a fixed width via
`pack_propagate(False)`. Right = page canvas with a **centered inline progress overlay** and
a bottom-right status strip. Scanned-only sections pack/unpack with no residual gap.

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
│ ┌ Settings/Help + nav (scrolls) ──│                               x 34.2% y 12.7%│  status strip
│ │ [ ⚙ Settings ][ ? Help ]       │                           ⬓ 41.0 × 58.3 %    │
│ │ [ ◀ ]  [ 3 ] / 312   [ ▶ ]        │                               page 3 / 312   │
│ └────────────────────────────────┴───────────────────────────────────────────────┘
```

---

## 7. Control reference

Every control carries a hover tooltip. Sections top→bottom; Settings/Help + nav is the last
card and scrolls with the column.

### 7.1 Document & State
| Control | Action | Behavior |
|---|---|---|
| Mode marker (title line) | — | Normal/Scanned pill. A **non-interactive marker** (same size/colour as a button, but not clickable); set automatically by classification on load |
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
| `✦ Auto-detect` | detect | per-page content box (§8); scanned mode shows the progress overlay. **Disabled** only when Split > 1 or both anchors are OFF. It is an **action, not a toggle** — it is *never* highlighted and stays re-pressable at any time (re-running after editing/dragging the crop always works) |
| `Anchor Left` / `Anchor Top` (toggles) | re-render | left/top edge from detected text (ON) or union edge (OFF); toggling re-evaluates whether Auto-detect is active |
| `Keep ratio` (toggle) | — | editing R also sets B to hold the current page's detected aspect |
| `L T R B` (label inline with the field; default font; range ±100, step 0.1) | re-render | per-edge percent offsets; each moves exactly one edge. **On commit (Return / focus-out) each offset snaps to the largest value the page allows** — an out-of-range entry (e.g. 100000) is reduced to the value that lands the edge on the page border / opposite side, never accepted as-is |
| `✕ Clear` | clear | drop detection + offsets |

### 7.5 Pages — §11.  ### 7.6 Resize — `Original (No Resize)`, device presets, `Custom…` (W×H); applied last.
### 7.7 Actions — one row, all visible: `✂ Crop` (commits + shows the crop), `↻ Rotate`
(rotates pages, preserves cleaning), `🗑 Delete` (removes the Pages selection). Then `💾 Export PDF`.
### 7.8 Settings/Help & nav — `⚙ Settings`, `? Help`, and page nav `◀  [ n ] /total  ▶` — the
arrows hug the edges and the page box takes the middle so current/total stay fully visible up
to 4 digits. This is the **last card in the scrollable column**; a flexible spacer above it
keeps it anchored at the panel bottom when there is room, and lets it scroll (partially/fully
hidden) when the column is taller than the viewport.

---

## 8. Auto-detect algorithm

Detection yields a **per-page content box** `B_p = (x0,y0,x1,y1)`; offsets and anchors
(§9) turn it into the crop rectangle. Per page over the Pages selection:

- **Normal:** union of text blocks (`get_text("blocks")`, type-0/text only):
  `x0=min bx0, y0=min by0, x1=max bx1, y1=max by1`. Pages with no text → page rect.
- **Scanned:** `content_box` on a real **Sauvola** clean (`clean_document_bilevel`) of the
  page, downscaled to `DETECT_MAX_PX` for speed. Sauvola flattens a photographed page's tinted
  background so the ink mask is the text, not the whole sheet — a global Otsu marks the tinted
  paper as ink and returns a page-border box. If no ink → page rect.

Then aggregate across the selected pages to fix one size for the whole document:
```
gL = min(x0)   gT = min(y0)                 # top-/left-most content corner (anchor-OFF base)
W  = max(x1 − x0)   H  = max(y1 − y0)        # LARGEST content width / height across pages
```
`W` is the widest content box found and `H` the tallest — **not** the bounding span of all
edges (which would over-crop). So every page crops to the same `W×H`. **Full-page fallback
boxes are excluded from the aggregate** (any page whose detected box is ≥ 97 % of the sheet
in both dims): otherwise one failed page would blow `W,H` up to the sheet size and push
right/bottom to the page edge. Per-page boxes and the aggregates are cached.

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
left_base = AnchorLeft ? B_p.x0 : gL              # ON: this page's text left; OFF: union-min left
top_base  = AnchorTop  ? B_p.y0 : gT              # ON: this page's text top;  OFF: union-min top
left   = left_base − L%·w                         # each offset moves exactly ONE edge
top    = top_base  − T%·h
right  = left_base + W + R%·w                      # anchored to left_base+W, NOT to (offset) left
bottom = top_base  + H + B%·h                      # anchored to top_base+H,  NOT to (offset) top
clamp [left,top,right,bottom] to the page rect          # never outside the page
enforce right−left ≥ MIN_RECT and bottom−top ≥ MIN_RECT
```

Auto-detect is **inactive** (button disabled, no crop drawn) when Split > 1 **or** both
anchors are OFF — at least one anchor must pin the frame. Anchors affect only left/top.
Right/bottom are anchored to `left_base+W` / `top_base+H`, so moving the left edge (`L`)
leaves the right edge fixed and moving the top edge leaves the bottom fixed — each offset
is independent, no opposite-edge coupling. Width and height stay the constant `W,H`, so the
box is the **same size on every page**; R/B enlarge it uniformly. **Keep ratio:** when on,
the crop height is locked to `width / ratio` (anchored at the top edge) on every render — so
it holds whether the width changed via the L/R offsets or a handle drag. `ratio` comes from
the editable ratio field (defaults to the detected `W/H`).

**Offset commit clamp:** offsets are bounded to ±100 and, on commit (Return / focus-out),
snapped to the page-limited maximum — the crop rect is round-tripped through `clamp_box` and
each edge is read back out as its offset, so a value that would push an edge past the page
border (or its opposite edge) is rewritten to the largest in-bounds value instead of being
kept verbatim.

**Drag** (auto mode): apply the cursor delta to the dragged handle's edge(s) of the
current page's rectangle, then write back each touched offset as a float in a single
trace-suppressed batch and render once:
```
L = (left_base − new.left )/w·100      R = (new.right  − (left_base + W))/w·100
T = (top_base  − new.top  )/h·100      B = (new.bottom − (top_base  + H))/h·100
```
One edge ↔ one offset ⇒ non-dragged borders are reproduced exactly; opposite-edge jitter
is structurally impossible. Manual/split rectangles are dragged directly in page units.

**Draw a new crop** (auto mode): press on empty page area (not a handle) and drag to
rubber-band a fresh rectangle; on release it *replaces* the current crop (its size becomes
`W,H`, this page's `B_p`, offsets reset to 0, an anchor is enabled if none was). Dragging a
handle resizes one edge; dragging inside the box moves it. Pressing on a page whose crop is
already committed (§12) reverts it to the full page so editing can resume.

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
**Pattern** field plus a **⦿ Current** *button* (a real push-button styled like the other
buttons, not a checkbox) pinned to the right edge that fills the field with the current page
and keeps it selected. The Pattern field accepts a 1-indexed list of page numbers, inclusive
`a-b` ranges, and **Python-style colon slices `start:stop[:step]`** (1-indexed inclusive,
optional ends, optional step — `1:4`==`1-4`==pages 1-4, `1:100:5`==1,6,…,96, `::2`==every odd
page, `10:`==page 10 to the end), and mixes like `1:4, 10:30, 35, 37`; out-of-range values are
ignored. The resolved index set drives detect, dewarp, clean, apply, rotate, and delete.

---

## 12. Apply / export

`Apply Crop` over the Pages selection (other pages copied unchanged):
- **Normal:** clip = the page's auto rectangle (§9) or manual rectangle(s); render via
  `show_pdf_page(clip)` into a new page → vector preserved. Split N → N pages.
- **Scanned:** crop the cached `work[i]` by the rectangle (px); Split N → N crops; embed
  each as an image page. Reuses processed rasters (no reprocessing).
- **Resize** applied last: `Original` keeps native size; preset/Custom resamples the crop.

**Committed crop is saved state.** Apply Crop stores the crop box(es) per page in an
`applied` map (this *is* the persisted crop state and is covered by Undo). It is independent
of the current Pages selection: changing the selection afterwards does **not** un-crop other
pages. The viewer shows each committed page cropped (overlay/handles hidden); pressing on it
re-opens it full-size for editing (§9). Dewarp, clean and rotate also repaint immediately.

`Export` (`Ctrl+S`): pre-fills `<original-name>_cropped.pdf`. Iterates **every** page —
committed pages export cropped, the rest whole — building output images on a worker thread
with the **progress overlay**, then writes `save(garbage=4, deflate=True)`.

---

## 13. History, reset, rotate, delete

- **History:** doc-state stack, depth from the Undo/redo-depth setting (**default 4**).
  Snapshot before any mutating op — crop (the committed `applied` map), rotate, **and
  dewarp/clean** — so Undo reverts all of them. Capture includes `applied`, `rotation`,
  processed flags, detection and offsets (not the rasters); restore clears the raster caches.
- **Reset (header `⟲`):** resets the whole document to its just-opened state — **re-opens the
  file** (or reloads the synthetic demo), clearing all crops, rotations, detection, processing
  and history.
- **Delete (`🗑`, in the Crop/Rotate/Delete row):** removes the Pages selection from the
  document (`doc.delete_pages`), rebuilds page sizes, then **reindexes** every per-page map
  (source/work caches, detection, processed flags, committed crops, rotation): deleted pages'
  entries are dropped and surviving keys shift down, so **adjustments on the kept pages are
  preserved**, not wiped. Refuses to delete every page; confirmation dialog first.
- **Rotate:** a per-page **rotation-angle map** (`rotation[i]` in 0/90/180/270° CW), applied
  in `_source_image`/`_page_dims`. Rotate adds 90° and drops only the page's *rasters* (so they
  re-render at the new angle); the **committed crop and the detected content box are carried
  through the turn** by rotating their coordinates 90° CW (`rotate_box_cw`), so cropping is
  *not* undone by rotation. Live auto-detect offsets reset to 0 (their L/T/R/B map to the
  rotated edges) and the union is rebuilt from the rotated boxes. Fully **undoable** (angle +
  transformed boxes are snapshotted) and identical in Normal and Scanned mode.

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
| Behaviour | Undo / redo depth | numeric field (default 4); bounds the history stack |
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

**Palette: warm-gray chrome + a clear blue accent.** Defined in `smartcrop/ui/theme.py`.
Cards/chrome are warm off-white / warm charcoal; **buttons are neutral at rest** and only
highlight (the blue `ACCENT`) when they represent an active/pressed state — the toggles
(Dewarp, B/W, Grayscale) while on. **Auto-detect is an action, not a toggle: it never
highlights** and stays re-pressable so it always works after editing the crop. Switch-"on",
segmented-selected, the crop frame (`CROP_BLUE`) and split rectangles
(`SPLIT_BLUE`, one dark blue for all, thick lines + large ① numbers, no circle) all use blue
so highlights read clearly. The status strip sits on a card chip with prominent text. The
mode pill is a non-interactive marker. Disabled controls dim. Every label stays legible in
both modes. UI scales with `Ctrl +/-` (`Ctrl 0` resets); 100 % zoom = system display scaling.
Window title shows the open file name. Design aligned with mid-2026 guidance.

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
- Mode switch leaves no empty gap at the panel top; the whole control column scrolls as one.

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
5. Rotate preserves applied cleaning **and the committed/detected crop** (boxes are rotated
   with the page, not dropped); Delete preserves the kept pages' adjustments (reindex, no wipe).
6. Nothing in scanned processing runs without an explicit button press.
7. Crop rectangles never extend outside the page.
8. UI never blocks during batch processing; Cancel stops promptly; the overlay (not a
   window) reports progress for detect, dewarp, clean, and apply.
9. Resident memory stays within `CACHE_MAX_MB` for raster caches regardless of page count.
10. All PyMuPDF/Tkinter access is main-thread; workers touch only numpy/cv2 + prerendered rasters.
