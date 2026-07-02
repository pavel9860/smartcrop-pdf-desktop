"""`DocumentState` — exactly the undoable state, and nothing else (ARCHITECTURE §3, §5.1).

`snapshot()` is the single definition of "undoable": History stores these copies (§13). The fields
are precisely the ones spec §13 enumerates as captured by a snapshot — `applied`, split rects,
rotation, processed intents, detection/union, offsets and the filter/dewarp intent. Everything else
the app holds (the open document, page sizes, current page, mode, anchors, keep-ratio, split count,
pages selection) is *not* undoable and lives on `AppModel`, not here.

Note on scope: ARCHITECTURE §5.1 sketched a wider field list; spec §13/§22 are authoritative on
what Undo reverts (only crop/draw/rotate/dewarp/filter), so `DocumentState` is the narrower
spec-snapshot set. `Box` is replaced, never mutated in place, so the shallow per-page dict/list
copies below are safe (a copied box is never written through).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import FilterMode
from core.geometry import Box


@dataclass(frozen=True)
class Offsets:
    """Per-edge crop offsets, percent of the page dimension (§9). Resolution-independent."""
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass(frozen=True)
class PageProcessIntent:
    """One page's scan-processing intent (§10) — replaces today's `dict[int, dict]`."""
    dewarp: bool = False
    filter: tuple[FilterMode, int] | None = None    # (mode, strength) or None


@dataclass
class DocumentState:
    applied: dict[int, list[Box]] = field(default_factory=dict)      # committed crop(s) per page
    drawn: Box | None = None            # the one global live drawn crop window (§9.4)
    crop_rects: list[Box] = field(default_factory=list)             # live split rectangles
    rotation: dict[int, int] = field(default_factory=dict)          # page → degrees CW
    processed: dict[int, PageProcessIntent] = field(default_factory=dict)
    detect_cache: dict[int, Box] = field(default_factory=dict)      # per-page content box
    union: Box | None = None                                        # constant crop frame
    auto_active: bool = False
    offsets: Offsets = field(default_factory=Offsets)
    dewarp_on: bool = False
    filter_mode: FilterMode = FilterMode.NONE
    filter_strength: int = 2

    def snapshot(self) -> DocumentState:
        """An undo copy: deep-copy the per-page maps/lists, share the frozen scalars."""
        return DocumentState(
            applied={i: list(v) for i, v in self.applied.items()},
            drawn=self.drawn,
            crop_rects=list(self.crop_rects),
            rotation=dict(self.rotation),
            processed=dict(self.processed),
            detect_cache=dict(self.detect_cache),
            union=self.union,
            auto_active=self.auto_active,
            offsets=self.offsets,
            dewarp_on=self.dewarp_on,
            filter_mode=self.filter_mode,
            filter_strength=self.filter_strength,
        )
