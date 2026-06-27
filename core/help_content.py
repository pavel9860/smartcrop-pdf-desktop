"""Help sections and per-control tooltip text (UI-toolkit-agnostic strings)."""
from __future__ import annotations

# (anchor, title, body) — rendered as a scrollable, clickable table of contents.
HELP_SECTIONS = [
    ("modes", "Document mode", "When you open a file, SmartCrop inspects every page and "
     "labels the document Normal (born-digital vector text) or Scanned (page images). The "
     "marker beside the Document & State title shows the result; it is informational and set "
     "automatically. Scan Processing appears only for Scanned documents."),
    ("loading", "Loading & combining files", "Use Load Files (Ctrl+O) to choose one or many "
     "files at once — any mix of PDFs and images (jpg/png/tif). They combine into one working "
     "document in selection order: each PDF contributes its pages, each image becomes one page. "
     "Your work stays in memory until you export — the originals are never modified."),
    ("pages", "Choosing pages", "Pick which pages an action affects: All, Odd, or Even "
     "(counted from page 1), or Selected to type an exact set such as 1,3,5-9,12 (commas and "
     "inclusive ranges). The chosen pages drive auto-detect, scan processing, crop and "
     "rotate."),
    ("detect", "Auto-detect & offsets", "Auto-detect finds the text area on each chosen page "
     "and derives one crop size that fits them all — a constant width (the widest content "
     "found) and height (the tallest), so every page is trimmed to matching dimensions. "
     "Anchor Left and Anchor Top decide where that frame sits: ON aligns the edge to each "
     "page's own content, OFF aligns it to the common (cross-page) edge. At least one anchor "
     "must be on. Fine-tune with the L/T/R/B fields — each nudges a single edge (in percent "
     "of the page), and dragging a handle on the page does the same. Keep ratio locks the "
     "width-to-height proportion (set it in the field) by adjusting the bottom edge."),
    ("draw", "Adjusting the crop", "Drag any handle to resize one edge, or drag inside the "
     "box to move it. To start over, drag a new rectangle anywhere on the page — the previous "
     "crop is replaced. Clear removes the crop and resets the offsets."),
    ("scan", "Scan processing", "For Scanned documents only. Dewarp & Deskew flattens and "
     "straightens curled or tilted pages. B/W (bilevel threshold) and Sharpen (flatten + "
     "denoise + unsharp, keeps tone) are mutually exclusive filters; Strength 1-3 sets how "
     "aggressive the active one is. Nothing is applied until you press a button, and each run "
     "starts fresh from the original scan."),
    ("split", "Splitting pages", "Split one source page into 1, 2, or 4 output pages — handy "
     "for two-up scans. Draw or drag the rectangles in reading order (numbered ①-④); Same "
     "size keeps them identical. Split and auto-detect are mutually exclusive."),
    ("compress", "Compressing output", "Compress Document resamples every output image to the "
     "chosen DPI (Original keeps native crop pixels; High 300 / Medium 150 / Low 72 make a "
     "leaner file), applied last after cropping. Output colours = Grayscale desaturates every "
     "page (tone kept, no thresholding); Original colors leaves each page untouched."),
    ("export", "Export & formats", "Apply Crop commits the crop to the chosen pages and shows "
     "the result in the viewer. Export (Ctrl+S) writes a new file; the ▾ menu chooses the "
     "format — PDF (one file) or JPG / PNG / TIFF (one file per output page, with an index "
     "suffix). The name is suggested as <name>_cropped. Undo/Redo cover crop, rotate, dewarp "
     "and filter."),
    ("shortcuts", "Keyboard shortcuts", "Ctrl+O open · Ctrl+Enter apply crop · Ctrl+S "
     "export · Ctrl+Z undo · Ctrl+Y redo · ← / → and PgUp / PgDn (or the mouse wheel over "
     "the page) change page · Ctrl+= and Ctrl+- scale the interface · Enter in the page box "
     "jumps to it."),
    ("about", "About", "SmartCrop PDF crops, straightens and cleans PDFs and scans for "
     "comfortable reading on e-readers and tablets. Interface built with CustomTkinter."),
]

SPLIT_TIP = {1: "Single crop — one rectangle, one output page per source page.",
             2: "Two areas → 2 output pages, left-to-right reading order (①②).",
             4: "Four quadrants → 4 output pages in reading order (①②③④)."}

OFFSET_TIP = {"L": "Left edge offset — percent of page width (range ±100, step 0.1).",
              "T": "Top edge offset — percent of page height (range ±100, step 0.1).",
              "R": "Right edge offset — percent of page width (range ±100, step 0.1).",
              "B": "Bottom edge offset — percent of page height (range ±100, step 0.1)."}
