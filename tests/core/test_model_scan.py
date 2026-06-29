"""Scan processing: idempotent from source, nothing auto-runs (spec §10; inv 3, 6)."""
from __future__ import annotations

from core.enums import FilterMode


def _img_bytes(model):
    return model.view_snapshot().image.tobytes()


def test_nothing_runs_without_an_explicit_press(scanned):
    m = scanned(2)
    assert m.filter_mode == FilterMode.NONE      # inv 6: no processing on load
    assert m.dewarp_on is False


def test_filter_takes_effect_only_when_the_job_runs(scanned, run_job):
    m = scanned(2)
    job = m.set_filter_mode(FilterMode.BW)        # pressing creates a job…
    assert m.filter_mode == FilterMode.NONE       # …but commits nothing until it runs
    run_job(job)
    assert m.filter_mode == FilterMode.BW


def test_filter_is_idempotent_from_source(scanned, run_job):
    m = scanned(1)
    m.current_page = 0
    plain = _img_bytes(m)
    run_job(m.set_filter_mode(FilterMode.BW))
    once = _img_bytes(m)
    run_job(m.set_filter_strength(m.filter_strength))   # re-apply the same filter
    twice = _img_bytes(m)
    assert once != plain                          # the filter actually changed the page
    assert twice == once                          # inv 3: re-running == one run (no compounding)


def test_dewarp_toggles_and_re_derives_from_source(scanned, run_job):
    m = scanned(1)
    m.current_page = 0
    plain = _img_bytes(m)
    run_job(m.run_dewarp())                       # on
    on1 = _img_bytes(m)
    run_job(m.run_dewarp())                       # off → back to the unprocessed source
    assert _img_bytes(m) == plain
    run_job(m.run_dewarp())                       # on again
    assert _img_bytes(m) == on1                   # inv 3: derived fresh from source each time
