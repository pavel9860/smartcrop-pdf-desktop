"""Bounded undo/redo of `DocumentState` snapshots (ARCHITECTURE §5.3, spec §13).

There is exactly one snapshot type ever, so this is not generic. A mutating command pushes a
pre-mutation copy then mutates the live state; `undo(current)` parks a copy of `current` on the
redo stack and hands back the popped undo copy for the model to install.
"""
from __future__ import annotations

from core.document_state import DocumentState


class History:
    def __init__(self, depth: int) -> None:
        self._depth = max(1, depth)
        self._undo: list[DocumentState] = []
        self._redo: list[DocumentState] = []

    def set_depth(self, depth: int) -> None:
        self._depth = max(1, depth)
        del self._undo[: max(0, len(self._undo) - self._depth)]

    def push(self, state: DocumentState) -> None:
        self._undo.append(state.snapshot())
        del self._undo[: max(0, len(self._undo) - self._depth)]
        self._redo.clear()

    def undo(self, current: DocumentState) -> DocumentState | None:
        if not self._undo:
            return None
        self._redo.append(current.snapshot())
        return self._undo.pop()

    def redo(self, current: DocumentState) -> DocumentState | None:
        if not self._redo:
            return None
        self._undo.append(current.snapshot())
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
