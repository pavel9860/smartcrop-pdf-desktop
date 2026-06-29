"""Cooperative batch model (ARCHITECTURE §5.5, spec §14).

Single-threaded: "non-blocking to the event loop" means one page per `step()`. `core/` owns the
step semantics; `ui/` owns the scheduling (`root.after`). A command that processes pages returns a
`PageJob`; the window steps it, repaints the overlay (suppressed when `total <= 1`), and inspects
`result()` on finish. Fail-fast: a page raising `SmartCropError` ends the job `Failed` and commits
nothing — `on_success` (the commit) runs only after every page succeeds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from core.errors import ImagingError, SmartCropError


@dataclass(frozen=True)
class Ok:
    pass


@dataclass(frozen=True)
class Cancelled:
    pass


@dataclass(frozen=True)
class Failed:
    error: SmartCropError


BatchResult = Ok | Cancelled | Failed


class BatchJob(Protocol):
    title: str
    total: int
    done: int

    def step(self) -> None: ...
    def is_finished(self) -> bool: ...
    def cancel(self) -> None: ...
    def result(self) -> BatchResult: ...


def _noop() -> None:
    pass


class PageJob:
    """The one concrete `BatchJob`. `step_one(i)` does page i's heavy work (raising
    `SmartCropError` to fail-fast); `on_success()` commits once every page is `Ok`; `on_abort()`
    cleans up on cancel/failure (e.g. discard a half-built file)."""

    def __init__(self, title: str, indices: list[int], step_one: Callable[[int], None],
                 on_success: Callable[[], None] = _noop,
                 on_abort: Callable[[], None] = _noop) -> None:
        self.title = title
        self.total = len(indices)
        self.done = 0
        self._indices = indices
        self._step_one = step_one
        self._on_success = on_success
        self._on_abort = on_abort
        self._result: BatchResult | None = None

    def step(self) -> None:
        if self._result is not None:
            return
        if self.done >= self.total:           # zero-page job: vacuous success, still commits
            self._finish()
            return
        i = self._indices[self.done]
        try:
            self._step_one(i)
        except SmartCropError as exc:
            self._fail(exc)
            return
        self.done += 1
        if self.done >= self.total:
            self._finish()

    def _finish(self) -> None:
        try:
            self._on_success()                # the commit may itself fail (e.g. a bad save path)
        except SmartCropError as exc:
            self._fail(exc)
            return
        except Exception as exc:              # an unwrapped failure must still resolve the job
            self._fail(ImagingError(f"{self.title}: commit failed ({exc})."))
            return
        self._result = Ok()

    def _fail(self, exc: SmartCropError) -> None:
        self._result = Failed(exc)
        self._on_abort()

    def is_finished(self) -> bool:
        return self._result is not None

    def cancel(self) -> None:
        if self._result is None:
            self._result = Cancelled()
            self._on_abort()

    def result(self) -> BatchResult:
        if self._result is None:
            raise RuntimeError("result() before the job finished")
        return self._result
