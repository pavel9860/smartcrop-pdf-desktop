"""Presentation tunables — the UI half of spec §18 (domain tunables stay in core/constants.py;
core is Tk-free, ARCHITECTURE §2/§5.2). Mirror the spec exactly; no magic numbers inline in ui/.
"""
from __future__ import annotations

# ── crop handle hit-test / drawing (page-unit tol = (HANDLE_R + HANDLE_SLACK) / scale) ───────
HANDLE_R = 6
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
SETTINGS_MIN_W = 520

# ── timings ────────────────────────────────────────────────────────────────────────────────────
SCALE_THROTTLE_MS = 80

# ── canvas paint (§17 preview lever, §19 status) ──────────────────────────────────────────────
PHOTO_CACHE = 6          # fitted page bitmaps kept resident — nav/drag skips the resample
STATUS_PAD = 8           # position text inset from the page image's bottom-left corner (px)

# ── compact control rows (§7.4, §7.4a) ────────────────────────────────────────────────────────
OFFSET_FIELD_W = 48      # one-line L T R B offset entries — all four visible in the panel
RATIO_FIELD_W = 110      # Keep-ratio value entry — four significant digits, no clipping
ROW_LABEL_W = 90         # label column of the Same-size / Keep-ratio rows
SWITCH_W = 44            # CTkSwitch width in those rows (default 100 starves the entry)

# ── UI scale / font (Settings, §15) ──────────────────────────────────────────────────────────
UI_SCALE_MIN = 0.7
UI_SCALE_MAX = 2.0
FONT_SIZE_MIN = 10
FONT_SIZE_MAX = 24
DEFAULT_FONT_SIZE = 15

# ── split badge: numbered circle marking output order, top-left corner of each split window
# (spec §9.6). A fixed point size like the other canvas marks (§19) — does not track
# DEFAULT_FONT_SIZE's live Settings override, only its default value.
SPLIT_BADGE_FONT_SIZE = round(DEFAULT_FONT_SIZE * 1.3)     # 30% bigger than the base UI font
SPLIT_BADGE_R = round(SPLIT_BADGE_FONT_SIZE * 0.8)         # circle radius, fits a 1-2 digit number
SPLIT_BADGE_MARGIN = 4                                      # gap from window corner to the circle
CANVAS_STATUS_FONT_SIZE = DEFAULT_FONT_SIZE                 # status text drawn directly on canvas

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
