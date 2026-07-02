"""Live output/behaviour settings a domain command reads (ARCHITECTURE §5.2).

A value belongs here iff a domain command consumes it (compress → render target, colours →
render, format/folder/postfix → export naming, undo_depth → History, dewarp_supersample →
dewarp). It sits *outside* History, so "Compress DPI / Output colours survive Undo" (§22 inv 22)
holds by construction. Presentation-only state (theme/font/scale/dialog toggles) is ui/UIConfig,
not here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Settings:
    compress_preset: str = "Original resolution"
    output_colours: str = "Original colors"
    export_format: str = "PDF"
    output_folder: str = ""                # "" → same folder as the source file
    output_postfix: str = "_cropped"       # appended before the extension (§12.5)
    undo_depth: int = 4
    dewarp_supersample: float = 1.0     # 1.0 = off (§10.1); raise for less resampling blur
