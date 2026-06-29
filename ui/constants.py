"""Presentation tunables — the UI half of spec §18 (domain tunables stay in core/constants.py;
core is Tk-free, ARCHITECTURE §2/§5.2). Mirror the spec exactly; no magic numbers inline in ui/.
"""
from __future__ import annotations

# ── crop handle hit-test / drawing (page-unit tol = (HANDLE_R + HANDLE_SLACK) / scale) ───────
HANDLE_R = 8
HANDLE_SLACK = 6
CANVAS_MARGIN = 40

# Cursor shown while hovering/dragging each handle (moved from core/geometry.py — a Tk concern).
HANDLE_CURSOR: dict[str, str] = {
    "NW": "size_nw_se", "SE": "size_nw_se", "NE": "size_ne_sw", "SW": "size_ne_sw",
    "N": "sb_v_double_arrow", "S": "sb_v_double_arrow",
    "E": "sb_h_double_arrow", "W": "sb_h_double_arrow",
}

# ── window / panel geometry ───────────────────────────────────────────────────────────────────
WINDOW_SIZE = "1560x1000"
WINDOW_MIN = (1040, 700)
PANEL_WIDTH = 320
SETTINGS_MIN_W = 620

# ── timings ────────────────────────────────────────────────────────────────────────────────────
STATUS_IDLE_MS = 2400
SCALE_THROTTLE_MS = 80

# ── UI scale / font (Settings, §15) ──────────────────────────────────────────────────────────
UI_SCALE_MIN = 0.7
UI_SCALE_MAX = 2.0
FONT_SIZE_MIN = 10
FONT_SIZE_MAX = 24
DEFAULT_FONT_SIZE = 15

# ── palette: warm-gray chrome + a clear blue accent (§19) ───────────────────────────────────
# CustomTkinter colour params take a (light, dark) tuple and pick by appearance mode; a single
# string is mode-independent (used for tk.Canvas drawing, which isn't theme-aware).
THEMES: dict[str, tuple[str, str] | str] = {
    "accent": ("#1A1A1C", "#3B82E0"),            # active button / switch-on / segmented-selected
    "accent_hover": ("#1A1A1C", "#5295E8"),
    "accent_text": ("#FFFFFF", "#FFFFFF"),
    "seg_unsel": ("#6E6B64", "#46443E"),          # segmented unselected fill
    "secondary": ("#F1EFE9", "#36352F"),          # neutral control fill (default button look)
    "secondary_hover": ("#E6E3DB", "#423F39"),
    "secondary_text": ("#2A2A26", "#F1EFE9"),
    "card": ("#FBFAF6", "#262522"),               # warm off-white / warm charcoal
    "card_border": ("#E6E3DA", "#3A3833"),
    "muted": ("#74726B", "#A8A69E"),
    "status_fg": ("#1A1A1C", "#DAD8D1"),
    "crop_blue": "#224d87",                       # crop frame outline (canvas drawing)
    "split_blue": "#224d87",                      # split rectangles (canvas drawing)
}
