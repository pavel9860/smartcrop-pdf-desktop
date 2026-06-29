"""`UIConfig` — presentation-only runtime state that drives NO domain computation
(ARCHITECTURE §5.2). Owned by `SmartCropApp`; invisible to `core/`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.constants import DEFAULT_FONT_SIZE


@dataclass
class UIConfig:
    theme: str = "Dark"                    # appearance only: Light/Dark/System
    font_size: int = DEFAULT_FONT_SIZE      # widget font only
    ui_scale: float = 1.0                   # CTk widget scaling only
    confirm_overwrite: bool = True          # gates a UI overwrite dialog before export
    remember_folder: bool = True            # UI policy: write the chosen folder back to Settings
