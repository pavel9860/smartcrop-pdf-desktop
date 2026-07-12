"""Domain tunables — the single source of truth for the values §18 lists (mirror it exactly;
do not duplicate values into logic). Presentation tunables (themes, handle sizes, window
geometry, fonts) live in ui/constants.py, not here — core is Tk-free (ARCHITECTURE §2, §5.2).
"""
from __future__ import annotations

# Compress Document (§7.6): menu label → output DPI (None = keep native crop pixels). The first
# entry is the default. Compress resamples every embedded page image to the chosen DPI (§12.6).
DPI_PRESETS: dict[str, int | None] = {
    "Original resolution": None,
    "High — 300 dpi": 300,
    "Medium — 150 dpi": 150,
    "Low — 75 dpi": 75,
}
# Output colours menu (§7.6): Grayscale desaturates each output page (tonal range kept).
COLOUR_MODES: list[str] = ["Original colors", "Grayscale"]
# Export split button (§12.7) and Load-Files dialog filter (§7.1a).
EXPORT_FORMATS: list[str] = ["PDF", "JPG", "PNG", "TIFF"]
IMAGE_LOAD_EXT: list[str] = [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"]

# ── DPI / caches ──────────────────────────────────────────────────────────────
SRC_DPI = 200.0            # raster DPI for scanned pages
NORMAL_DPI = 150.0         # raster DPI for born-digital pages
CACHE_WINDOW = 16          # max pages kept in each raster cache (source/work) — LRU-evicted
# ── classification / detection ────────────────────────────────────────────────
MODE_TEXT_MIN = 8          # a page with < this many text chars and no vector path ⇒ image-only (§4)
DETECT_MAX_PX = 1400       # cap raster size for content detection (speed)
BORDER_FRAC = 0.02         # ignore ink within this margin in content detection
MIN_COMP_FRAC = 2.5e-4     # min connected-component area (fraction of page) kept in detection
FULL_PAGE_FRAC = 0.97      # detected box ≥ this fraction of the sheet ⇒ full-page fallback
DESKEW_MAX_DEG = 15.0      # clamp auto-deskew angle
# ── crop geometry ─────────────────────────────────────────────────────────────
OFFSET_LIMIT = 100.0       # max |offset| as a percent of the page dimension
# ── filter / output ───────────────────────────────────────────────────────────
CLEAN_AMOUNT: dict[int, float] = {1: 0.6, 2: 1.1, 3: 1.6}    # Sharpen unsharp amount per strength
JPEG_QUALITY = 88          # JPG export quality (§12.7)
# ── paper sizes ────────────────────────────────────────────────────────────────
# ISO 216, portrait, in points (1 pt = 1/72 in; mm -> pt via *72/25.4).
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A2": (1190.6, 1683.8),
    "A3": (841.9, 1190.6),
    "A4": (595.3, 841.9),
    "A5": (419.5, 595.3),
    "A6": (297.6, 419.5),
}
DEFAULT_PAPER_SIZE = "A4"
# ── synthetic placeholder document ────────────────────────────────────────────
SYNTH_PAGES = 24           # pages in the synthetic placeholder document
