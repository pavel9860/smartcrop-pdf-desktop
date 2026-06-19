# SmartCrop PDF v7

Modular Tkinter/PyMuPDF PDF crop utility (normal + scanned workflows).

## Run (uv)
```
uv pip install -r requirements.txt      # or: uv sync if you keep a pyproject
uv run python pdf_cropper.py
```
`tkinter` ships with CPython on Windows/macOS. On Linux: `apt install python3-tk`.

## The `import fitz` RuntimeError ("Directory 'static/' does not exist")
That is NOT PyMuPDF — an unrelated abandoned PyPI package is also named `fitz`
(it does `from frontend import *`). It's installed in your **.venv** and shadows
PyMuPDF. Use the venv's own pip (uv), and never declare/install `fitz`:
```
uv pip uninstall fitz frontend tools pymupdf pymupdfb
uv pip install --reinstall --no-cache pymupdf
uv run python -c "import fitz; print(fitz.__doc__)"   # 'PyMuPDF 1.27.x ...'
```
If `pyproject.toml`/requirements lists `fitz`, replace it: `uv remove fitz; uv add pymupdf`.

## What changed in v7 (your bug list)
1. Right edge no longer drifts by a constant — auto-detect now builds ONE union
   box (min-left/top, max-right/bottom across pages) and the four offsets are
   PER-EDGE (each moves one border). Right edge = detected right + R.
2. Removed the "offsets = % of page" helper line from the Detect panel.
3. Removed the 4K monitor resolution preset.
4. Pages buttons are now All / Odd / Even / Select (Select = 1-indexed list+ranges
   like `1,3,5-9`). "Current" and raw-slice removed.
5. Clean + Unwarp/Deskew now run over the whole PAGES selection, not one page.
6. Auto-detect is robust to scan-edge lines / border speckle (border-touching
   components and sub-threshold speckle are dropped before bounds).
7. Status/progress dialog (with Cancel) on Unwarp / Clean / Apply.
8. Clean is no longer automatic; nothing runs until you press a button.
9. Two clean buttons (highlight when active): "Bilevel B/W" and "Sharpen Gray"
   (keeps grayscale, flattens illumination, unsharp-masks).
Plus: per-edge offsets make the opposite-border jitter structurally impossible.

## Layout
```
pdf_cropper.py        entry point
smartcrop/
  app.py              PDFCropperApp — GUI, modes, crop pipeline, drag (jitter-free)
  imaging.py          cv2/skimage: clean, sharpen_grayscale, deskew, content_box, unwarp
  parsing.py          parse_selection (1-indexed) + page-mode resolution
  widgets.py          Tooltip, ToggleSwitch, Segmented
  constants.py        themes, resolutions, help text
```

## Validated headless (this build)
All files byte-compile; AST check (88 methods, no missing refs); parsing/select,
robust content_box (drops scan-edge line + speckle), grayscale sharpen, normal
clip + scanned raster→PDF assembly; per-edge geometry (right edge on text, drag
N/W leaves opposite edge fixed over 80 events, anchors). NOT runnable here (no
display): live Tk GUI, drag visuals, threaded processing/progress dialog, panel swap.

## Known follow-ups (flagged)
- Export embeds bilevel as PNG-in-PDF; CCITT-G4/JBIG2 not wired.
- Scanned auto-detect cleans each page once on first press; cache makes re-press cheap.
- Unwarp with docuwarp absent falls back to deskew-only (warning shown).
