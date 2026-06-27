"""Static configuration: colour themes, tunables, compress/export presets."""
from __future__ import annotations

from typing import Dict, List, Optional

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "BG": "#1a1a1c", "PANEL": "#232325", "PANEL_2": "#2a2a2d", "PANEL_3": "#323236",
        "BORDER": "#3a3a3f", "TEXT": "#ededee", "MUTED": "#9a9aa0",
        "INPUT_BG": "#1a1a1c", "INPUT_FG": "#ededee", "ACCENT": "#ededee",
        "ACCENT_HOVER": "#ffffff", "ACCENT_SELECTED": "#4a4a50", "SELECT_BG": "#5e5e68",
        "SELECT_FG": "#ffffff", "ACCENT_TEXT": "#1a1a1c", "SW_OFF": "#45454b",
        "SW_ON": "#ededee", "SW_KNOB_ON": "#1a1a1c", "SW_KNOB_OFF": "#ededee",
        "SEP": "#3a3a3f", "CANVAS_BG": "#161618", "SETTINGS_BG": "#1a1a1c",
        "SASH": "#3a3a3f", "HANDLE": "#3b82f6", "HANDLE_FILL": "#ffffff",
        "MAGIC": "#3b82f6", "CANVAS_ACCENT": "#3b82f6", "HEADER_FG": "#ededee",
        "BADGE_NORMAL": "#2f6f4f", "BADGE_SCAN": "#7a4d1d", "OK": "#3fae6b", "WARN": "#d08a3a",
    },
    "light": {
        "BG": "#f4f4f2", "PANEL": "#ffffff", "PANEL_2": "#f1f1ef", "PANEL_3": "#e8e8e6",
        "BORDER": "#dcdcda", "TEXT": "#1a1a1a", "MUTED": "#6e6e72",
        "INPUT_BG": "#ffffff", "INPUT_FG": "#1a1a1a", "ACCENT": "#1a1a1a",
        "ACCENT_HOVER": "#000000", "ACCENT_SELECTED": "#c6c6c2", "SELECT_BG": "#d8d8d4",
        "SELECT_FG": "#1a1a1a", "ACCENT_TEXT": "#ffffff", "SW_OFF": "#c8c8c4",
        "SW_ON": "#1a1a1a", "SW_KNOB_ON": "#ffffff", "SW_KNOB_OFF": "#ffffff",
        "SEP": "#dcdcda", "CANVAS_BG": "#dadad6", "SETTINGS_BG": "#f4f4f2",
        "SASH": "#c6c6c2", "HANDLE": "#2563eb", "HANDLE_FILL": "#ffffff",
        "MAGIC": "#2563eb", "CANVAS_ACCENT": "#2563eb", "HEADER_FG": "#1a1a1a",
        "BADGE_NORMAL": "#cfe8da", "BADGE_SCAN": "#f0dcc2", "OK": "#2e7d4f", "WARN": "#b06a1f",
    },
}

# Compress Document (§7.6): menu label → output DPI (None = keep native crop pixels). The first
# entry is the default. Compress resamples every embedded page image to the chosen DPI (§12.6).
DPI_PRESETS: Dict[str, Optional[int]] = {
    "Original resolution": None,
    "High — 300 dpi": 300,
    "Medium — 150 dpi": 150,
    "Low — 72 dpi": 72,
}
# Output colours menu (§7.6): Grayscale desaturates each output page (tonal range kept).
COLOUR_MODES: List[str] = ["Original colors", "Grayscale"]
# Export split button (§12.7) and Load-Files dialog filter (§7.1a).
EXPORT_FORMATS: List[str] = ["PDF", "JPG", "PNG", "TIFF"]
IMAGE_LOAD_EXT: List[str] = [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"]

# ── App geometry / rendering / behaviour constants (single source of truth) ──────────
SRC_DPI = 200.0            # raster DPI for scanned pages
NORMAL_DPI = 150.0         # raster DPI for born-digital pages
HANDLE_R = 8               # crop-handle radius (px)
HANDLE_SLACK = 6           # extra hit tolerance around a handle (px)
CANVAS_MARGIN = 40         # padding kept around the fitted page on the canvas (px)
MODE_TEXT_MIN = 8          # a page with < this many text chars and no vector path ⇒ image-only (§4)
DESKEW_MAX_DEG = 15.0      # clamp auto-deskew angle
BORDER_FRAC = 0.02         # ignore ink within this margin in content detection
MIN_COMP_FRAC = 2.5e-4     # min connected-component area (fraction of page) kept in detection
DETECT_MAX_PX = 1400       # cap raster size for content detection (speed)
SYNTH_PAGES = 24           # pages in the synthetic placeholder document
CACHE_WINDOW = 16          # max pages kept in each raster cache (source/work) — LRU-evicted
CLEAN_AMOUNT = {1: 0.6, 2: 1.1, 3: 1.6}    # grayscale-filter unsharp amount per strength
FULL_PAGE_FRAC = 0.97      # detected box ≥ this fraction of the sheet ⇒ full-page fallback
STATUS_IDLE_MS = 2400      # delay before the status strip reverts to the page indicator (ms)
SCALE_THROTTLE_MS = 80     # min interval between live UI-scale applies while a key repeats (ms)
UI_SCALE_MIN = 0.7         # Ctrl-/+ and zoom-menu bounds
UI_SCALE_MAX = 2.0
FONT_SIZE_MIN = 10
FONT_SIZE_MAX = 24
DEFAULT_FONT_SIZE = 15
OFFSET_LIMIT = 100.0       # max |offset| as a percent of the page dimension
WINDOW_SIZE = "1560x1000"  # initial main-window geometry
WINDOW_MIN = (1040, 700)   # minimum main-window size
PANEL_WIDTH = 440          # fixed width of the left control panel (px)
SETTINGS_MIN_W = 620       # minimum Settings-window width; grows to fit content/DPI
