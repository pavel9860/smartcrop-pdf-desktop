"""Typed error taxonomy (spec §20, ARCHITECTURE §6).

`core/` raises these for every *expected* failure and never catches them or opens a dialog;
`ui/app_window.dispatch()` is the one place they are caught and shown. Unexpected exceptions are
left to propagate to Tk's global handler.
"""
from __future__ import annotations


class SmartCropError(Exception):
    """Base for every expected failure core raises."""


class NoDocumentError(SmartCropError):
    """An operation needs a real loaded document (the synthetic demo can't be edited)."""


class EmptySelectionError(SmartCropError):
    """The Pages selection resolved to no pages."""


class InvalidSplitError(SmartCropError):
    """Apply was pressed without exactly N split rectangles."""


class DeleteAllPagesError(SmartCropError):
    """Delete would remove every page."""


class DocumentLoadError(SmartCropError):
    """A file could not be opened / combined (malformed PDF or image)."""


class ImagingError(SmartCropError):
    """One page's imaging step failed inside a batch (fail-fast, §14/§20)."""


class MissingDependencyError(SmartCropError):
    """A required optional dependency (docuwarp) is absent."""
