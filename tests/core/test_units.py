"""Unit tests for the value objects and the batch mechanism (History, DocumentState, PageJob)."""
from __future__ import annotations

import pytest

from core.batch import Cancelled, Failed, Ok, PageJob
from core.document_state import DocumentState, Offsets, PageProcessIntent
from core.enums import FilterMode
from core.errors import ImagingError, SmartCropError
from core.geometry import Box
from core.history import History


# ── History ─────────────────────────────────────────────────────────────────────
def test_history_undo_redo_roundtrip():
    h = History(4)
    s0 = DocumentState(auto_active=False)
    s1 = DocumentState(auto_active=True)
    h.push(s0)                                   # snapshot of s0 before mutating to s1
    assert h.can_undo and not h.can_redo
    back = h.undo(s1)
    assert back is not None and back.auto_active is False
    assert h.can_redo
    fwd = h.redo(s0)
    assert fwd is not None and fwd.auto_active is True


def test_history_is_depth_bounded():
    h = History(2)
    for k in range(5):
        h.push(DocumentState(filter_strength=k))
    assert h.undo(DocumentState()) is not None
    assert h.undo(DocumentState()) is not None
    assert h.undo(DocumentState()) is None       # only 2 retained


def test_history_set_depth_trims():
    h = History(5)
    for k in range(5):
        h.push(DocumentState(filter_strength=k))
    h.set_depth(2)
    assert h.undo(DocumentState()) is not None
    assert h.undo(DocumentState()) is not None
    assert h.undo(DocumentState()) is None


def test_history_empty_returns_none():
    h = History(4)
    assert h.undo(DocumentState()) is None
    assert h.redo(DocumentState()) is None


# ── DocumentState.snapshot ───────────────────────────────────────────────────────
def test_snapshot_deep_copies_mutable_maps():
    s = DocumentState(applied={0: [Box(0, 0, 1, 1)]}, rotation={0: 90},
                      processed={0: PageProcessIntent(dewarp=True)})
    snap = s.snapshot()
    s.applied[0].append(Box(2, 2, 3, 3))         # mutate the original
    s.rotation[1] = 180
    assert snap.applied == {0: [Box(0, 0, 1, 1)]}    # snapshot unaffected
    assert snap.rotation == {0: 90}


def test_snapshot_shares_frozen_scalars():
    o = Offsets(1.0, 2.0, 3.0, 4.0)
    s = DocumentState(offsets=o, filter_mode=FilterMode.BW)
    snap = s.snapshot()
    assert snap.offsets is o                      # frozen → safe to share by reference
    assert snap.filter_mode == FilterMode.BW


# ── PageJob ──────────────────────────────────────────────────────────────────────
def _drive(job):
    while not job.is_finished():
        job.step()
    return job.result()


def test_pagejob_runs_all_then_commits():
    seen, committed = [], []
    job = PageJob("t", [0, 1, 2], seen.append, lambda: committed.append(True))
    assert isinstance(_drive(job), Ok)
    assert seen == [0, 1, 2] and committed == [True]
    assert job.done == 3


def test_pagejob_empty_still_commits_on_success():
    committed = []
    job = PageJob("t", [], lambda i: None, lambda: committed.append(True))
    assert isinstance(_drive(job), Ok)
    assert committed == [True]                    # zero-page job is a vacuous success (FIX 14)


def test_pagejob_failfast_commits_nothing():
    committed, aborted = [], []

    def step(i):
        if i == 1:
            raise ImagingError("boom on page 2")

    job = PageJob("t", [0, 1, 2], step, lambda: committed.append(True),
                  lambda: aborted.append(True))
    result = _drive(job)
    assert isinstance(result, Failed)
    assert isinstance(result.error, SmartCropError)
    assert committed == [] and aborted == [True]  # nothing committed; cleanup ran
    assert job.done == 1                          # stopped on the failing page


def test_pagejob_cancel_aborts():
    aborted = []
    job = PageJob("t", [0, 1, 2], lambda i: None, on_abort=lambda: aborted.append(True))
    job.step()                                    # process page 0
    job.cancel()
    assert job.is_finished()
    assert isinstance(job.result(), Cancelled)
    assert aborted == [True]


def test_pagejob_commit_failure_becomes_failed():
    def bad_commit():
        raise ImagingError("save failed")

    job = PageJob("t", [0], lambda i: None, bad_commit)
    result = _drive(job)
    assert isinstance(result, Failed)             # an on_success failure routes to Failed (FIX 12)


def test_pagejob_commit_unexpected_exception_becomes_failed():
    def bad_commit():
        raise ValueError("not a SmartCropError")

    job = PageJob("t", [0], lambda i: None, bad_commit)
    result = _drive(job)
    assert isinstance(result, Failed)             # an unwrapped commit failure still resolves
    assert isinstance(result.error, ImagingError)
    assert job.is_finished()


def test_result_before_finish_raises():
    job = PageJob("t", [0], lambda i: None)
    with pytest.raises(RuntimeError):
        job.result()
