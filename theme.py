"""UI colour palette — warm-gray chrome with a clear blue accent for active/selected states.

Each value is a CustomTkinter ``(light, dark)`` tuple (single strings are mode-independent,
used for canvas drawing). Buttons look neutral at rest and only highlight (blue) when they
represent an active/pressed state; switches, segmented selections and the crop frame use blue.
"""
from __future__ import annotations

ACCENT = ("#1E64C8", "#3B82E0")            # active button / switch-on / segmented-selected
ACCENT_HOVER = ("#1A56AC", "#5295E8")
ACCENT_TEXT = ("#FFFFFF", "#FFFFFF")
SEG_UNSEL = ("#6E6B64", "#46443E")         # segmented unselected fill (white text reads on it)
SECONDARY = ("#F1EFE9", "#36352F")         # neutral control fill (default button look)
SECONDARY_HOVER = ("#E6E3DB", "#423F39")
SECONDARY_TEXT = ("#2A2A26", "#F1EFE9")
CARD = ("#FBFAF6", "#262522")              # warm off-white / warm charcoal
CARD_BORDER = ("#E6E3DA", "#3A3833")
MUTED = ("#74726B", "#A8A69E")
STATUS_FG = ("#2A2A26", "#DAD8D1")         # prominent status text
CROP_BLUE = "#1E64C8"                      # crop frame outline (clearly visible)
SPLIT_BLUE = "#13478F"                     # split rectangles — one dark blue for all
