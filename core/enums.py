"""Formalised application states (no more 'stringly-typed' modes).

These are `str`-backed enums, so a member compares/serialises like its old string value
(`Mode.SCANNED == "scanned"`) — keeping `parsing.pages_for_mode` and any legacy comparison
working — while assignments use named constants (`self.mode = Mode.SCANNED`). A typo in a
member name (`Mode.SCANNDED`) is an immediate AttributeError instead of a silent bad branch.
"""
from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """Document classification / crop unit."""
    NORMAL = "normal"        # born-digital: vector crop, points
    SCANNED = "scanned"      # raster crop, pixels @ SRC_DPI


class FilterMode(str, Enum):
    """Scan filter (mutually exclusive, §7.2/§10.2)."""
    NONE = "none"
    BW = "bw"                # bilevel black/white (Sauvola threshold)
    SHARPEN = "sharpen"      # flatten + denoise + unsharp, keeps continuous tone


class PagesMode(str, Enum):
    """Which pages an operation applies to."""
    ALL = "all"
    ODD = "odd"
    EVEN = "even"
    SELECT = "select"        # the Pattern field decides
