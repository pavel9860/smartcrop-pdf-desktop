"""Regression tests for the reviewed fixes (FIX 1, 2, 6, 8)."""
from __future__ import annotations

import io

import fitz
from PIL import Image

from core.constants import OFFSET_LIMIT
from core.enums import Mode
from core.model import AppModel


def _box(model, page=None):
    if page is not None:
        model.current_page = page
    ov = model.view_snapshot().overlay
    return ov[0].box if ov else None


# TEST A — a split miss-click must NOT drop committed crops (FIX 1)
def test_split_missclick_keeps_committed_crop(model):
    model.set_split(2)
    model.apply_crop()
    model.current_page = 0
    original = list(model.document.applied[0])
    model.begin_drag(-50.0, -50.0, tol=1.0)      # outside every split rectangle → nothing grabbed
    model.end_drag()
    assert model.document.applied[0] == original  # the committed split is restored, not discarded


# TEST B — view_snapshot() must not mutate view_box (FIX 2)
def test_view_snapshot_is_side_effect_free(model):
    model.begin_drag(50.0, 50.0, tol=3.0)        # commit a single-box crop on page 0
    model.update_drag(250.0, 550.0)
    model.end_drag()
    model.current_page = 0
    model.view_box = 99                          # deliberately stale
    model.view_snapshot()
    assert model.view_box == 99                  # the query left it untouched (no clamp inside)


# TEST C — _write_auto_offsets clamps to OFFSET_LIMIT (FIX 6)
def test_drag_far_outside_clamps_offsets(model, run_job):
    run_job(model.detect_content())
    b = _box(model, 0)
    model.begin_drag((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, tol=3.0)   # grab to move the whole rect
    model.update_drag(99999.0, 99999.0)          # drag far off-page
    model.end_drag()
    o = model.offsets
    assert all(abs(v) <= OFFSET_LIMIT for v in (o.left, o.top, o.right, o.bottom))


# TEST D — _classify_document caps the scan at 10 pages (FIX 8)
def test_classify_scans_at_most_ten_pages(tmp_path, monkeypatch):
    doc = fitz.open()
    for _ in range(50):                          # 50 image-only pages
        buf = io.BytesIO()
        Image.new("RGB", (40, 50), "white").save(buf, format="PNG")
        pg = doc.new_page(width=40, height=50)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    path = tmp_path / "big.pdf"
    doc.save(str(path))
    doc.close()

    calls = []
    orig = fitz.Page.get_text

    def counting(self, *a, **k):
        calls.append(1)
        return orig(self, *a, **k)

    monkeypatch.setattr(fitz.Page, "get_text", counting)
    m = AppModel()
    m.load_files([str(path)])
    assert m.page_count() == 50
    assert m.mode == Mode.SCANNED
    assert len(calls) <= 10                       # only the first 10 pages were inspected
