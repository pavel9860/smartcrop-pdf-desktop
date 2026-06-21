"""Static configuration: colour themes, resolution presets, help text."""
from __future__ import annotations

from typing import Dict, Sequence

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

RESOLUTIONS: Sequence[str] = (
    "Original (No Resize)",
    "Amazon Kindle Scribe (1860×2480)",
    "Amazon Kindle Oasis (1264×1680)",
    "Amazon Kindle Paperwhite (1080×1440)",
    "Kobo Forma (1440×1920)",
    "Kobo Sage (1440×1920)",
    "Kobo Elipsa (1404×1872)",
    "Kobo Libra 2 (1264×1680)",
    "Kobo Clara 2E/HD (1072×1448)",
    "Onyx Boox Note Air 2 (1404×1872)",
    "PocketBook InkPad 3 (1404×1872)",
    "Custom…",
)

HELP_TEXT = """\
SmartCrop PDF — Quick-Start
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODES
  On load the document is auto-classified Normal or Scanned.
  Normal  : born-digital PDF; crop is vector, non-destructive.
  Scanned : page is an image; SCAN PROCESSING block appears.
  The Mode badge (top-left) flips the classification manually.

SCAN PROCESSING  (scanned mode only)
  Unwarp + Deskew : toggle mesh dewarp + deskew over the PAGES
    selection (idempotent; always re-reads the original).
  Clean output    : two mutually-exclusive buttons, applied to the
    PAGES selection (nothing runs automatically):
      Bilevel B/W  — Sauvola pure black/white (Strength 1/2/3,
                     optional Preserve pictures).
      Sharpen Gray — keep grayscale, flatten + sharpen.
  Reset page      : reloads the current page from the cached original.

SPLIT INTO  (1 / 2 / 4)
  N areas -> N output pages. Draw the boxes in reading order;
  numbered badges confirm output order. Apply unlocks at N boxes.
  2/4 greys out DETECT (manual split is the crop source instead).

DETECT  (split = 1)
  Auto-detect : Normal -> text bounds; Scanned -> ink content-box.
  Anchors snap the crop edge to detected left/top vs page edge.
  One union box across all pages. Offsets L/T/R/B each move ONE
  edge, in % of page dimension (0.1% step): right edge sits on the
  detected right margin (+R). Drag handles or type numbers; the box
  applies to every page in the selection.

PAGES
  All / Odd / Even (1-indexed) or Select for specific pages:
    Select accepts 1-indexed lists + ranges, e.g.  1,3,5-9,12

RESIZE
  Applied at the very end, after crop. 'Original' keeps native size.

ACTIONS
  Apply Crop (Ctrl+Enter) · Rotate 90° CW · Export PDF (Ctrl+S)
  Undo (Ctrl+Z, depth 1-2) · Redo (Ctrl+Y)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHORTCUTS
  Ctrl+O Load · Ctrl+Enter Apply · Ctrl+S Export
  Ctrl+Z Undo · Ctrl+Y Redo · ←/→ or PgUp/PgDn page
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
