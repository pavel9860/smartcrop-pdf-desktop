"""`AppModel` — the single Tk-free facade that owns all state, commands and queries
(ARCHITECTURE §3–§5). `ui/` calls only public methods here and reads only the frozen objects they
return; it never reaches past them.

State split: `DocumentState` is the undoable bundle (History snapshots it, §13). Everything else —
the open document, page sizes, navigation, mode, anchors, keep-ratio, split count, the pages
selection, the raster caches and the transient drag — is non-undoable and lives directly on the
model. `Settings` (live output/behaviour) sits outside History, so Compress/colours survive Undo.
"""
from __future__ import annotations

import os
import random
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypeVar

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw

import core.imaging
from core import render, viewmodel
from core.batch import BatchJob, PageJob
from core.constants import (
    CACHE_WINDOW,
    CLEAN_AMOUNT,
    DETECT_MAX_PX,
    DPI_PRESETS,
    FULL_PAGE_FRAC,
    JPEG_QUALITY,
    MODE_TEXT_MIN,
    NORMAL_DPI,
    OFFSET_LIMIT,
    SRC_DPI,
    SYNTH_PAGES,
)
from core.document_state import DocumentState, Offsets, PageProcessIntent
from core.drag import AutoDrag, CropEditDrag, DragState, DrawDrag, SplitDrag
from core.enums import FilterMode, Mode, PagesMode
from core.errors import (
    DeleteAllPagesError,
    DocumentLoadError,
    EmptySelectionError,
    ImagingError,
    InvalidSplitError,
    NoDocumentError,
)
from core.geometry import (
    MIN_RECT,
    Box,
    anchored_base,
    auto_crop_rect,
    clamp_box,
    hit_handle,
    move_box,
    point_in_box,
    resize_by_handle,
    rotate_box_cw,
    union_box,
)
from core.history import History
from core.lru import LRUCache
from core.parsing import pages_for_mode
from core.settings import Settings

_FMT_EXT = {"PDF": "pdf", "JPG": "jpg", "PNG": "png", "TIFF": "tif"}
_T = TypeVar("_T")


@dataclass(frozen=True)
class OverlayBox:
    """One crop rectangle the canvas paints, kind-tagged so the painter picks colour/badge."""
    box: Box
    kind: Literal["auto", "split"]
    index: int                       # split badge 0..3; -1 for the auto crop


@dataclass(frozen=True)
class ViewSnapshot:
    """Everything the canvas needs to paint one frame (ARCHITECTURE §5.6)."""
    image: Image.Image               # the page raster, or the committed-crop output image
    page_w: float                    # units the overlay/draw_rect coords live in
    page_h: float
    overlay: tuple[OverlayBox, ...]  # empty on a committed page (no handles)
    draw_rect: Box | None            # live rubber-band
    position: int                    # 1-based output-page position
    total: int                       # output-page total
    status: str


def _clamp_offset(v: float) -> float:
    return round(max(-OFFSET_LIMIT, min(OFFSET_LIMIT, v)), 1)


def _reindex(d: dict[int, _T], deleted: set[int]) -> dict[int, _T]:
    """Drop deleted pages and shift surviving keys down (kept-page adjustments preserved, §13)."""
    return {o - sum(1 for x in deleted if x < o): v for o, v in d.items() if o not in deleted}


class AppModel:
    # ── construction / non-undoable context ──────────────────────────────────
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.document = DocumentState()
        self.history = History(self.settings.undo_depth)
        self.source_cache = LRUCache(CACHE_WINDOW)
        self.work_cache = LRUCache(CACHE_WINDOW)
        self.drag: DragState | None = None
        self.draw_rect: Box | None = None
        self.prev_applied: list[Box] | None = None
        self._drag_moved = False
        self.doc: Any = None                      # fitz.Document | None (fitz is untyped)
        self.input_paths: list[str] = []
        self.page_sizes: list[tuple[float, float]] = []
        self.mode = Mode.NORMAL
        self.current_page = 0
        self.view_box = 0
        self.anchor_left = True
        self.anchor_top = True
        self.keep_ratio = False
        self.ratio: float | None = None
        self.split_count = 1
        self.same_size = True
        self.pages_mode = PagesMode.ALL
        self.select_pattern = ""
        self.current_follow = False
        self._load_synthetic()

    # ── document ─────────────────────────────────────────────────────────────
    def load_files(self, paths: list[str]) -> None:
        try:
            doc = self._combine_files(paths)
        except Exception as exc:
            raise DocumentLoadError(f"Could not open the selected files: {exc}") from exc
        if doc.page_count == 0:
            raise DocumentLoadError("No pages to load.")
        self.doc = doc
        self.input_paths = list(paths)
        self.page_sizes = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
        self._reset_doc_state()
        self.mode = self._classify_document()

    @staticmethod
    def _combine_files(paths: list[str]) -> Any:
        """Concatenate PDFs (all pages) and images (one page each) in selection order (§7.1a)."""
        combined = fitz.open()
        try:
            for path in paths:
                if os.path.splitext(path)[1].lower() == ".pdf":
                    with fitz.open(path) as src:
                        combined.insert_pdf(src)
                else:
                    with fitz.open(path) as img:
                        pdf_bytes = img.convert_to_pdf()
                    with fitz.open("pdf", pdf_bytes) as img_pdf:
                        combined.insert_pdf(img_pdf)
        except Exception:
            combined.close()              # don't leak the half-built doc on a bad input
            raise
        return combined

    def reset(self) -> None:
        """Re-open the whole document to its just-loaded state (§13)."""
        if self.doc is not None and self.input_paths:
            self.load_files(self.input_paths)
        else:
            self._load_synthetic()

    def _load_synthetic(self) -> None:
        self.doc = None
        self.input_paths = []
        rnd = random.Random(7)
        self.page_sizes = [(600 + rnd.uniform(-15, 15), 820 + rnd.uniform(-20, 20))
                           for _ in range(SYNTH_PAGES)]
        self._reset_doc_state()
        self.mode = Mode.NORMAL

    def _reset_doc_state(self) -> None:
        self.document = DocumentState()
        self.history.clear()
        self.source_cache.clear()
        self.work_cache.clear()
        self.current_page = 0
        self.view_box = 0
        self.current_follow = False
        self.split_count = 1
        self.ratio = None
        self.drag = None
        self.draw_rect = None
        self.prev_applied = None

    def page_count(self) -> int:
        return len(self.page_sizes)

    def _classify_document(self) -> Mode:
        if self.doc is None:
            return self.mode
        # heuristic — first 10 pages suffice; early return on the first text-bearing page (§4)
        for i in range(min(self.doc.page_count, 10)):
            page = self.doc[i]
            if len(page.get_text().strip()) >= MODE_TEXT_MIN or page.get_drawings():
                return Mode.NORMAL
        return Mode.SCANNED

    def _page_dims(self, idx: int) -> tuple[float, float]:
        w, h = self.page_sizes[idx]
        if self.mode == Mode.SCANNED:
            k = SRC_DPI / 72.0
            w, h = w * k, h * k
        if self.document.rotation.get(idx, 0) % 180 == 90:
            return h, w
        return w, h

    # ── raster pipeline (the source/work caches, §10) ────────────────────────
    def _source_image(self, idx: int) -> Image.Image:
        cached: Image.Image | None = self.source_cache.get(idx)
        if cached is not None:
            return cached
        if self.doc is not None:
            dpi = int(SRC_DPI if self.mode == Mode.SCANNED else NORMAL_DPI)
            pm = self.doc[idx].get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        else:
            img = self._synthetic_image(idx)
        ang = self.document.rotation.get(idx, 0)
        if ang:
            img = img.rotate(-ang, expand=True)       # PIL rotates CCW; -ang = clockwise
        self.source_cache[idx] = img
        return img

    def _compute_work(self, idx: int, intent: PageProcessIntent) -> Image.Image:
        """Derive the work raster from the immutable source under `intent` (idempotent, §10)."""
        src = self._source_image(idx)
        if self.mode != Mode.SCANNED:
            return src
        bgr = cv2.cvtColor(np.array(src), cv2.COLOR_RGB2BGR)
        if intent.dewarp:
            bgr = self._dewarp_bgr(bgr)
        if intent.filter is not None:
            fmode, strength = intent.filter
            if fmode == FilterMode.BW:
                g = core.imaging.clean_document_bilevel(bgr, strength=strength, upscale=1.0)
            else:
                g = core.imaging.sharpen_grayscale(bgr, strength=strength,
                                                   amount=CLEAN_AMOUNT[strength])
            bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def _work_image(self, idx: int) -> Image.Image:
        cached: Image.Image | None = self.work_cache.get(idx)
        if cached is not None:
            return cached
        img = self._compute_work(idx, self.document.processed.get(idx, PageProcessIntent()))
        self.work_cache[idx] = img
        return img

    def _dewarp_bgr(self, bgr: Any) -> Any:
        if core.imaging.unwarp_available():
            try:
                return core.imaging.unwarp_bgr(bgr)
            except (RuntimeError, OSError) as exc:   # ONNX/docuwarp inference failed → deskew-only
                warnings.warn(f"dewarp failed, falling back to deskew: {exc}", stacklevel=2)
        return core.imaging.deskew_auto(bgr)[0]

    def _synthetic_text_box(self, idx: int, w: float, h: float) -> Box:
        rnd = random.Random(idx * 17 + 3)
        return Box(w * (0.09 + rnd.uniform(-0.02, 0.03)), h * (0.10 + rnd.uniform(-0.02, 0.03)),
                   w * (1 - 0.09 - rnd.uniform(-0.02, 0.03)),
                   h * (1 - 0.13 - rnd.uniform(-0.03, 0.03)))

    def _synthetic_image(self, idx: int) -> Image.Image:
        w, h = self.page_sizes[idx]
        img = Image.new("RGB", (int(w), int(h)), "white")
        dr = ImageDraw.Draw(img)
        rnd = random.Random(idx * 31 + 1)
        box = self._synthetic_text_box(idx, w, h)
        if self.mode == Mode.NORMAL:
            y = box.y0
            while y < box.y1 - 10:
                dr.line([(box.x0, y), (box.x1 - rnd.uniform(0, w * 0.18), y)],
                        fill=(70, 70, 75), width=2)
                y += rnd.uniform(14, 20)
            dr.rectangle([box.x0, box.y0, box.x1, box.y1], outline=(210, 210, 215))
            return img
        dr.rectangle([box.x0, box.y0, box.x1, box.y1], fill=(60, 60, 65))
        for _ in range(40):
            x, yy = rnd.uniform(box.x0, box.x1), rnd.uniform(box.y0, box.y1)
            dr.ellipse([x, yy, x + 3, yy + 3], fill=(230, 230, 225))
        return img.rotate(rnd.uniform(-5, 5), fillcolor="white", resample=Image.Resampling.BICUBIC)

    # ── pages selection ──────────────────────────────────────────────────────
    def resolve_pages(self) -> list[int]:
        try:
            return pages_for_mode(self.pages_mode, self.page_count(), self.current_page,
                                  self.select_pattern)
        except ValueError:
            return []

    def set_pages_mode(self, mode: PagesMode) -> None:
        if mode != PagesMode.SELECT and self.current_follow:
            self.current_follow = False
        self.pages_mode = mode

    def set_select_pattern(self, pattern: str) -> None:
        self.current_follow = False              # a manual Pattern edit ends follow (§11)
        self.select_pattern = pattern

    def set_current_follow(self, on: bool) -> None:
        self.current_follow = on
        if on:                                   # switch to Selected, fill Pattern with the page
            self.pages_mode = PagesMode.SELECT
            self.select_pattern = str(self.current_page + 1)

    # ── detection / crop geometry (§8, §9) ───────────────────────────────────
    def detect_content(self) -> BatchJob:
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        results: dict[int, Box] = {}

        def step(i: int) -> None:
            results[i] = self._detect_box(i)

        return PageJob("Detecting", indices, step, lambda: self._finish_detect(results))

    def _detect_box(self, i: int) -> Box:
        try:
            return self._content_box_page(i)
        except Exception as exc:
            raise ImagingError(f"Page {i + 1}: detection failed ({exc}).") from exc

    def _content_box_page(self, idx: int) -> Box:
        w, h = self._page_dims(idx)
        if self.mode == Mode.NORMAL:
            if self.doc is not None:
                blocks = [b for b in self.doc[idx].get_text("blocks")
                          if b[6] == 0 and b[4].strip()]
                if blocks:
                    return Box(min(b[0] for b in blocks), min(b[1] for b in blocks),
                               max(b[2] for b in blocks), max(b[3] for b in blocks))
                return Box(0, 0, w, h)
            return self._synthetic_text_box(idx, w, h)
        bgr = cv2.cvtColor(np.array(self._work_image(idx)), cv2.COLOR_RGB2BGR)
        g0h, g0w = bgr.shape[:2]
        s = min(1.0, DETECT_MAX_PX / max(g0h, g0w))
        if s < 1.0:
            bgr = cv2.resize(bgr, (max(1, round(g0w * s)), max(1, round(g0h * s))),
                             interpolation=cv2.INTER_AREA)
        gh, gw = bgr.shape[:2]
        bw = core.imaging.clean_document_bilevel(bgr, strength=2, upscale=1.0)
        t = core.imaging.content_box(bw)
        if t is None:
            return Box(0, 0, w, h)
        sx, sy = w / gw, h / gh
        return Box(t[0] * sx, t[1] * sy, t[2] * sx, t[3] * sy)

    def _finish_detect(self, results: dict[int, Box]) -> None:
        d = self.document
        recommit = [i for i in results if i in d.applied]
        if recommit:
            self.history.push(d)            # refreshing committed crops is undoable (§7.4)
        d.detect_cache.update(results)
        good = [b for i, b in results.items()
                if b.width < FULL_PAGE_FRAC * self._page_dims(i)[0]
                or b.height < FULL_PAGE_FRAC * self._page_dims(i)[1]]
        d.union = union_box(good or list(results.values()))
        d.auto_active = True
        for i in recommit:                  # refresh — never drop — the committed crop
            rect = self._crop_rect(i)
            if rect is not None:
                d.applied[i] = [rect]
        if not self.keep_ratio:
            self.ratio = d.union.width / d.union.height if d.union.height else None

    def _active_ratio(self) -> float | None:
        if self.ratio is not None and self.ratio > 0:
            return self.ratio
        u = self.document.union
        return u.width / u.height if u and u.height else None

    def _crop_rect(self, idx: int) -> Box | None:
        d = self.document
        if self.split_count > 1 or not d.auto_active or d.union is None:
            return None
        if not (self.anchor_left or self.anchor_top):
            return None
        w, h = self._page_dims(idx)
        b = d.detect_cache.get(idx) or Box(0, 0, w, h)
        o = d.offsets
        rect = auto_crop_rect(b, d.union, self.anchor_left, self.anchor_top,
                              o.left, o.top, o.right, o.bottom, w, h)
        if self.keep_ratio:
            ratio = self._active_ratio()
            if ratio:
                rect = clamp_box(Box(rect.x0, rect.y0, rect.x1, rect.y0 + rect.width / ratio), w, h)
        return rect

    def set_anchor(self, left: bool | None = None, top: bool | None = None) -> None:
        if left is not None:
            self.anchor_left = left
        if top is not None:
            self.anchor_top = top

    def set_offset(self, edge: Literal["L", "T", "R", "B"], value: float) -> None:
        field = {"L": "left", "T": "top", "R": "right", "B": "bottom"}[edge]
        self.document.offsets = replace(self.document.offsets, **{field: _clamp_offset(value)})

    def commit_offsets(self) -> None:
        """Snap each offset to the largest the page allows (§7.4a): round-trip the live crop
        through its page-clamped rectangle and read each edge back out as its offset."""
        d = self.document
        if not (d.auto_active and d.union):
            o = d.offsets
            d.offsets = Offsets(_clamp_offset(o.left), _clamp_offset(o.top),
                                _clamp_offset(o.right), _clamp_offset(o.bottom))
            return
        idx = self.current_page
        rect = self._crop_rect(idx)
        if rect is None:
            return
        w, h = self._page_dims(idx)
        b = d.detect_cache.get(idx) or Box(0, 0, w, h)
        ab = anchored_base(b, d.union, self.anchor_left, self.anchor_top, w, h)
        u = d.union
        bottom = (d.offsets.bottom if self.keep_ratio        # B is inert while the ratio locks it
                  else round((rect.y1 - (ab.y0 + u.height)) / h * 100.0, 1))
        d.offsets = Offsets(round((ab.x0 - rect.x0) / w * 100.0, 1),
                            round((ab.y0 - rect.y0) / h * 100.0, 1),
                            round((rect.x1 - (ab.x0 + u.width)) / w * 100.0, 1),
                            _clamp_offset(bottom))

    def set_keep_ratio(self, on: bool, ratio: float | None = None) -> None:
        self.keep_ratio = on
        if ratio is not None:
            self.ratio = ratio
        elif on and self.ratio is None:
            u = self.document.union
            self.ratio = u.width / u.height if u and u.height else None

    # ── split (§7.3, §9.6) ───────────────────────────────────────────────────
    def set_split(self, n: int) -> None:
        if n != self.split_count:
            self.document.applied.clear()    # committed crops belong to the previous layout
        self.split_count = n
        if n == 1:
            self.document.crop_rects.clear()
        else:
            self._auto_layout_split(n)

    def _auto_layout_split(self, n: int) -> None:
        w, h = self._page_dims(self.current_page)
        if n == 2:
            self.document.crop_rects = [Box(0, 0, w / 2, h), Box(w / 2, 0, w, h)]
        elif n == 4:
            self.document.crop_rects = [Box(0, 0, w / 2, h / 2), Box(w / 2, 0, w, h / 2),
                                        Box(0, h / 2, w / 2, h), Box(w / 2, h / 2, w, h)]
        else:
            raise ValueError(f"split_count must be 2 or 4, got {n}")

    def set_same_size(self, on: bool) -> None:
        self.same_size = on
        if on and self.split_count > 1:
            self._auto_layout_split(self.split_count)

    # ── scan processing (§10) ────────────────────────────────────────────────
    def run_dewarp(self) -> BatchJob:
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        new_on = not self.document.dewarp_on
        intents = {i: replace(self.document.processed.get(i, PageProcessIntent()), dewarp=new_on)
                   for i in indices}
        return self._scan_job("Dewarp & Deskew", indices, intents, dewarp_on=new_on)

    def set_filter_mode(self, mode: FilterMode) -> BatchJob:
        new_mode = FilterMode.NONE if self.document.filter_mode == mode else mode
        return self._filter_job(new_mode, self.document.filter_strength)

    def set_filter_strength(self, n: int) -> BatchJob:
        if self.document.filter_mode == FilterMode.NONE:    # nothing to recompute; record for later
            def remember() -> None:
                self.document.filter_strength = n           # mutate only on the job's success
            return PageJob("Filter", [], lambda i: None, remember)
        return self._filter_job(self.document.filter_mode, n)

    def _filter_job(self, mode: FilterMode, strength: int) -> BatchJob:
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        filt = None if mode == FilterMode.NONE else (mode, strength)
        intents = {i: replace(self.document.processed.get(i, PageProcessIntent()), filter=filt)
                   for i in indices}
        return self._scan_job("Filtering pages", indices, intents,
                              filter_mode=mode, filter_strength=strength)

    def _scan_job(self, title: str, indices: list[int], intents: dict[int, PageProcessIntent], *,
                  dewarp_on: bool | None = None, filter_mode: FilterMode | None = None,
                  filter_strength: int | None = None) -> BatchJob:
        """Compute each page's work raster under its new intent; commit (intents + cache + flags)
        only once every page succeeds, so a mid-batch failure leaves the document untouched."""
        computed: dict[int, Image.Image] = {}

        def step(i: int) -> None:
            computed[i] = self._render_work(i, intents[i])

        def commit() -> None:
            d = self.document
            self.history.push(d)
            for i, intent in intents.items():
                d.processed[i] = intent
                self.work_cache[i] = computed[i]
            if dewarp_on is not None:
                d.dewarp_on = dewarp_on
            if filter_mode is not None:
                d.filter_mode = filter_mode
            if filter_strength is not None:
                d.filter_strength = filter_strength

        return PageJob(title, indices, step, commit)

    def _render_work(self, i: int, intent: PageProcessIntent) -> Image.Image:
        try:
            return self._compute_work(i, intent)
        except Exception as exc:
            raise ImagingError(f"Page {i + 1}: processing failed ({exc}).") from exc

    # ── apply / rotate / delete (§12.2, §13) ─────────────────────────────────
    def _page_crop_boxes(self, i: int) -> list[Box]:
        if self.split_count > 1:
            return list(self.document.crop_rects)
        w, h = self._page_dims(i)
        return [self._crop_rect(i) or Box(0, 0, w, h)]

    def apply_crop(self) -> None:
        if self.page_count() == 0:
            raise NoDocumentError("Open a document first.")
        if self.split_count > 1 and len(self.document.crop_rects) != self.split_count:
            raise InvalidSplitError(f"Draw exactly {self.split_count} rectangle(s).")
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        self.history.push(self.document)
        for i in indices:
            self.document.applied[i] = self._page_crop_boxes(i)
        self._clamp_view_box()

    def rotate_pages(self) -> None:
        if self.page_count() == 0:
            raise NoDocumentError("Open a document first.")
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        d = self.document
        self.history.push(d)
        for i in indices:
            w, h = self._page_dims(i)            # page size BEFORE this 90° step
            d.rotation[i] = (d.rotation.get(i, 0) + 90) % 360
            self.source_cache.pop(i, None)
            self.work_cache.pop(i, None)
            if i in d.applied:                   # carry the committed crop through the turn
                d.applied[i] = [rotate_box_cw(b, w, h) for b in d.applied[i]]
            if i in d.detect_cache:
                d.detect_cache[i] = rotate_box_cw(d.detect_cache[i], w, h)
        if d.auto_active and d.detect_cache:
            d.union = union_box(list(d.detect_cache.values()))
            d.offsets = Offsets()                # L/T/R/B map to rotated edges → reset to 0
            if not self.keep_ratio:
                self.ratio = d.union.width / d.union.height if d.union.height else None

    def delete_pages(self) -> None:
        if self.page_count() == 0 or self.doc is None:
            raise NoDocumentError("Open a PDF first (the demo document can't be edited).")
        idxs = sorted(set(self.resolve_pages()))
        if not idxs:
            raise EmptySelectionError("Empty Pages selection.")
        if len(idxs) >= self.page_count():
            raise DeleteAllPagesError("Can't delete every page.")
        self.doc.delete_pages(idxs)
        self.page_sizes = [(self.doc[i].rect.width, self.doc[i].rect.height)
                           for i in range(self.doc.page_count)]
        deleted = set(idxs)
        d = self.document
        self.source_cache.clear()
        self.work_cache.clear()
        d.detect_cache = _reindex(d.detect_cache, deleted)
        d.processed = _reindex(d.processed, deleted)
        d.applied = _reindex(d.applied, deleted)
        d.rotation = _reindex(d.rotation, deleted)
        if d.auto_active and d.detect_cache:
            d.union = union_box(list(d.detect_cache.values()))
        else:
            d.union, d.auto_active = None, False
        self.history.clear()
        self.current_page = min(self.current_page, self.page_count() - 1)
        self.view_box = 0

    # ── history / output settings ────────────────────────────────────────────
    def undo(self) -> None:
        restored = self.history.undo(self.document)
        if restored is not None:
            self._install(restored)

    def redo(self) -> None:
        restored = self.history.redo(self.document)
        if restored is not None:
            self._install(restored)

    def _install(self, state: DocumentState) -> None:
        self.document = state
        self.source_cache.clear()                # rotation may differ → re-render rasters
        self.work_cache.clear()
        self.view_box = 0

    def set_compress_preset(self, name: str) -> None:
        self.settings.compress_preset = name

    def set_output_colours(self, mode: str) -> None:
        self.settings.output_colours = mode

    def set_export_format(self, fmt: str) -> None:
        self.settings.export_format = fmt

    def set_undo_depth(self, depth: int) -> None:
        self.settings.undo_depth = max(1, depth)
        self.history.set_depth(self.settings.undo_depth)

    # ── export (§12) ─────────────────────────────────────────────────────────
    def _target_size(self, w: float, h: float) -> tuple[float, float] | None:
        dpi = DPI_PRESETS[self.settings.compress_preset]
        if dpi is None:
            return None
        per_point = (SRC_DPI / 72.0) if self.mode == Mode.SCANNED else 1.0
        k = (dpi / 72.0) / per_point
        return (w * k, h * k)

    def _remove_colours(self) -> bool:
        return self.settings.output_colours == "Grayscale"

    def _output_images(self, i: int) -> list[Image.Image]:
        """Page i's committed output image(s); an uncommitted page still exports through its live
        auto crop, never silently whole (§12.4). Shares render.output_image with the preview."""
        work = self._work_image(i)
        w, h = self._page_dims(i)
        if i in self.document.applied:
            boxes = self.document.applied[i]
        else:
            cb = self._crop_rect(i) if self.split_count == 1 else None
            boxes = [cb] if cb is not None else [Box(0, 0, w, h)]
        rc = self._remove_colours()
        return [render.output_image(work, box, w, h, self._target_size(box.width, box.height), rc)
                for box in boxes]

    def suggested_export_name(self) -> tuple[str, str]:
        base = (os.path.splitext(os.path.basename(self.input_paths[0]))[0]
                if self.input_paths else "output")
        ext = _FMT_EXT[self.settings.export_format]
        folder = self.settings.output_folder.strip() or (
            os.path.dirname(self.input_paths[0]) if self.input_paths else "")
        return (f"{base}{self.settings.output_postfix}.{ext}", folder)

    def export(self, path: Path) -> BatchJob:
        if self.page_count() == 0:
            raise NoDocumentError("Open a document first.")
        indices = self.resolve_pages()
        if not indices:
            raise EmptySelectionError("Empty Pages selection.")
        for i in indices:                        # commit the live/split crop first (§12.4)
            if self.split_count > 1 or i not in self.document.applied:
                self.document.applied[i] = self._page_crop_boxes(i)
        pages = list(range(self.page_count()))
        if self.settings.export_format == "PDF":
            return self._export_pdf_job(path, pages)
        return self._export_images_job(path, pages, self.settings.export_format)

    def _render_page_outputs(self, i: int) -> list[Image.Image]:
        try:
            return self._output_images(i)
        except Exception as exc:
            raise ImagingError(f"Page {i + 1}: render failed ({exc}).") from exc

    def _export_pdf_job(self, path: Path, pages: list[int]) -> BatchJob:
        out_doc = fitz.open()

        def step(i: int) -> None:                # one page of pixels resident at a time (§12.5)
            for img in self._render_page_outputs(i):
                pg = out_doc.new_page(width=img.width, height=img.height)
                pg.insert_image(pg.rect, stream=render.pil_to_png_bytes(img))

        def save() -> None:
            try:
                out_doc.save(str(path), garbage=4, deflate=True)   # garbage-collect + deflate
            except (OSError, RuntimeError) as exc:    # disk full / bad path → routed via Failed
                raise ImagingError(f"Export failed: {exc}") from exc
            finally:
                out_doc.close()

        def discard() -> None:                # cancel before save → drop the in-progress doc
            if not out_doc.is_closed:
                out_doc.close()

        return PageJob("Exporting pages", pages, step, save, discard)

    def _export_images_job(self, path: Path, pages: list[int], fmt: str) -> BatchJob:
        stem, ext = os.path.splitext(str(path))[0], _FMT_EXT[fmt]
        count = 0
        written: list[str] = []

        def step(i: int) -> None:
            nonlocal count
            for img in self._render_page_outputs(i):
                count += 1
                p = f"{stem}_{count:03d}.{ext}"
                if fmt == "JPG":
                    img.save(p, "JPEG", quality=JPEG_QUALITY)
                elif fmt == "PNG":
                    img.save(p, "PNG")
                else:
                    img.save(p, "TIFF", compression="tiff_deflate")
                written.append(p)

        def discard() -> None:                # cancel/failure → delete the files already written
            for p in written:
                try:
                    os.remove(p)
                except OSError:
                    pass

        return PageJob(f"Exporting {fmt}", pages, step, on_abort=discard)

    # ── gesture (page-unit coords from ui/canvas_view; tol is the page-unit hit radius) ──────
    def begin_drag(self, px: float, py: float, tol: float) -> None:
        if self.page_count() == 0:
            return
        self._drag_moved = False
        self.draw_rect = None
        applied = self.document.applied.get(self.current_page)
        if applied and self.split_count == 1:
            self.drag = CropEditDrag((px, py))   # edit within the committed view (§9.3)
            return
        self.prev_applied = self.document.applied.pop(self.current_page, None)
        if self.prev_applied is not None:
            self.view_box = 0                    # committed split → edit on the full page
        if self.split_count > 1:
            self._begin_split(px, py, tol)
        else:
            self._begin_auto(px, py, tol)

    def _begin_auto(self, px: float, py: float, tol: float) -> None:
        box = self._crop_rect(self.current_page)
        w, h = self._page_dims(self.current_page)
        d = self.document
        b = d.detect_cache.get(self.current_page) or Box(0, 0, w, h)
        u = d.union or Box(0, 0, w, h)
        ab = anchored_base(b, u, self.anchor_left, self.anchor_top, w, h)
        handle = hit_handle(box, px, py, tol) if box is not None else None
        if box is not None and handle is not None:
            self.drag = AutoDrag(handle, box, (px, py), w, h, d.offsets, ab.x0, ab.y0)
        elif box is not None and point_in_box(box, px, py):
            self.drag = AutoDrag(None, box, (px, py), w, h, d.offsets, ab.x0, ab.y0)
        else:
            self.drag = DrawDrag((px, py))       # empty area → rubber-band a new crop (§9.4)

    def _begin_split(self, px: float, py: float, tol: float) -> None:
        for i, box in enumerate(self.document.crop_rects):
            handle = hit_handle(box, px, py, tol)
            if handle:
                self.drag = SplitDrag(i, handle, box, (px, py))
                return
            if point_in_box(box, px, py):
                self.drag = SplitDrag(i, None, box, (px, py))
                return

    def update_drag(self, px: float, py: float) -> None:
        d = self.drag
        if d is None:
            return
        self._drag_moved = True
        match d:
            case AutoDrag(handle=str() as handle):
                self._write_auto_offsets(
                    resize_by_handle(d.rect0, handle, px - d.start[0], py - d.start[1],
                                     d.page_w, d.page_h), d)
            case AutoDrag():
                self._write_auto_offsets(
                    move_box(d.rect0, px - d.start[0], py - d.start[1], d.page_w, d.page_h), d)
            case SplitDrag(handle=str() as handle):
                w, h = self._page_dims(self.current_page)
                self.document.crop_rects[d.idx] = resize_by_handle(
                    d.rect0, handle, px - d.start[0], py - d.start[1], w, h)
            case SplitDrag():
                w, h = self._page_dims(self.current_page)
                self.document.crop_rects[d.idx] = move_box(
                    d.rect0, px - d.start[0], py - d.start[1], w, h)
            case DrawDrag() | CropEditDrag():
                bw, bh = self._drag_view_dims()
                sx, sy = d.start
                self.draw_rect = clamp_box(
                    Box(min(sx, px), min(sy, py), max(sx, px), max(sy, py)), bw, bh)

    def _write_auto_offsets(self, new: Box, d: AutoDrag) -> None:
        """Write the four offsets so _crop_rect reproduces `new` exactly (drag/move, §9.3)."""
        u = self.document.union
        if u is None:
            return
        w, h = d.page_w, d.page_h
        self.document.offsets = Offsets(
            _clamp_offset((d.left_base - new.x0) / w * 100.0),
            _clamp_offset((d.top_base - new.y0) / h * 100.0),
            _clamp_offset((new.x1 - (d.left_base + u.width)) / w * 100.0),
            _clamp_offset((new.y1 - (d.top_base + u.height)) / h * 100.0))

    def _drag_view_dims(self) -> tuple[float, float]:
        applied = self.document.applied.get(self.current_page)
        if applied and self.split_count == 1:    # crop-edit coords live in the committed box
            box = applied[min(self.view_box, len(applied) - 1)]
            return box.width, box.height
        return self._page_dims(self.current_page)

    def end_drag(self) -> None:
        d = self.drag
        self.drag = None
        match d:
            case SplitDrag():
                self._finish_split_drag(d)
            case DrawDrag():
                self._commit_drawn_rect()
            case CropEditDrag():
                self._commit_crop_edit()
            case AutoDrag():
                pass                             # live auto crop already updated via offsets
            case None:                           # split miss-click: nothing grabbed → keep the crop
                if self.prev_applied is not None:
                    self._restore_prev_applied()
        self.prev_applied = None

    def _finish_split_drag(self, d: SplitDrag) -> None:
        if not self._drag_moved:
            if self.prev_applied is not None:
                self._restore_prev_applied()
            return
        rects = self.document.crop_rects
        if self.keep_ratio:                      # snap the dragged window to the ratio (§9.7)
            ratio = self._active_ratio()
            if ratio:
                box = rects[d.idx]
                _, h = self._page_dims(self.current_page)
                rects[d.idx] = Box(box.x0, box.y0, box.x1,
                                   box.y0 + min(box.width / ratio, h - box.y0))
        if self.same_size:
            self._apply_same_size(d.idx)
        if self.prev_applied is not None:        # an edited committed split stays committed
            self.document.applied[self.current_page] = list(rects)

    def _apply_same_size(self, src: int) -> None:
        rects = self.document.crop_rects
        if not rects or src >= len(rects):
            return
        tw, th = rects[src].width, rects[src].height
        w, h = self._page_dims(self.current_page)
        for j, box in enumerate(rects):
            if j == src:
                continue
            x0 = min(box.x0, max(0.0, w - tw))
            y0 = min(box.y0, max(0.0, h - th))
            rects[j] = Box(x0, y0, min(w, x0 + tw), min(h, y0 + th))

    def _commit_drawn_rect(self) -> None:
        r = self.draw_rect
        self.draw_rect = None
        if r is None or r.width < 2 * MIN_RECT or r.height < 2 * MIN_RECT:
            if self.prev_applied is not None:    # aborted draw → keep the existing crop (§9.5)
                self._restore_prev_applied()
            return
        if self.keep_ratio:                      # snap a hand-drawn rect to the ratio (§9.7)
            ratio = self._active_ratio()
            if ratio:
                r = Box(r.x0, r.y0, r.x1, r.y0 + r.width / ratio)
        self.history.push(self.document)
        self.document.applied[self.current_page] = [r]
        self._clamp_view_box()

    def _commit_crop_edit(self) -> None:
        cur = self.document.applied.get(self.current_page)
        r = self.draw_rect
        self.draw_rect = None
        if not cur or r is None or r.width < 2 * MIN_RECT or r.height < 2 * MIN_RECT:
            return                               # nothing valid → keep the committed crop (§9.5)
        box = cur[0]                             # r is in the committed box's units → offset in
        new = Box(box.x0 + r.x0, box.y0 + r.y0, box.x0 + r.x1, box.y0 + r.y1)
        if self.keep_ratio:
            ratio = self._active_ratio()
            if ratio:
                new = Box(new.x0, new.y0, new.x1, new.y0 + new.width / ratio)
        self.history.push(self.document)
        self.document.applied[self.current_page] = [new]
        self.view_box = 0

    def _restore_prev_applied(self) -> None:
        if self.prev_applied is not None:
            self.document.applied[self.current_page] = self.prev_applied
        self.prev_applied = None
        self._clamp_view_box()

    def cancel_drag(self) -> None:
        """Esc / right-click mid-drag (§9.3, §9.6): discard the gesture, commit nothing, take no
        snapshot, leave the crop exactly as before the drag began (§22 inv 24)."""
        d = self.drag
        if d is None and self.draw_rect is None:
            return
        self.draw_rect = None
        self.drag = None
        match d:
            case SplitDrag():
                self.document.crop_rects[d.idx] = d.rect0
            case AutoDrag():
                self.document.offsets = d.offsets0
            case _:
                pass
        if self.prev_applied is not None:
            self.document.applied[self.current_page] = self.prev_applied
            self.prev_applied = None
            self.view_box = 0

    # ── navigation (output pages, §12.3) ─────────────────────────────────────
    def next_page(self) -> None:
        if not self.page_count():
            return
        if self.view_box < self._page_box_count(self.current_page) - 1:
            self.view_box += 1
        elif self.current_page < self.page_count() - 1:
            self.current_page, self.view_box = self.current_page + 1, 0
        else:
            return
        self._sync_follow()

    def prev_page(self) -> None:
        if not self.page_count():
            return
        if self.view_box > 0:
            self.view_box -= 1
        elif self.current_page > 0:
            self.current_page -= 1
            self.view_box = self._page_box_count(self.current_page) - 1
        else:
            return
        self._sync_follow()

    def jump_to_output_page(self, n: int) -> None:
        if 1 <= n <= self._view_total():
            self.current_page, self.view_box = viewmodel.flat_to_page_box(
                self.document.applied, self.page_count(), n - 1)
            self._sync_follow()

    def _sync_follow(self) -> None:
        if self.current_follow:
            self.select_pattern = str(self.current_page + 1)

    def _page_box_count(self, i: int) -> int:
        return viewmodel.page_box_count(self.document.applied, i)

    def _view_total(self) -> int:
        return viewmodel.view_total(self.document.applied, self.page_count())

    def _view_position(self) -> int:
        return viewmodel.view_position(self.document.applied, self.current_page, self.view_box)

    # ── queries ──────────────────────────────────────────────────────────────
    def view_snapshot(self) -> ViewSnapshot:
        idx = self.current_page
        w, h = self._page_dims(idx)
        work = self._work_image(idx)
        applied = self.document.applied.get(idx)
        if applied:                              # committed → paint the EXACT export image (§12.1)
            vb = max(0, min(self.view_box, len(applied) - 1))   # local clamp — query is pure
            box = applied[vb]
            image = render.output_image(work, box, w, h, self._target_size(box.width, box.height),
                                        self._remove_colours())
            return ViewSnapshot(image, box.width, box.height, (), self.draw_rect,
                                self._view_position() + 1, self._view_total(), self._status_text())
        return ViewSnapshot(work, w, h, self._overlay_boxes(), self.draw_rect,
                            self._view_position() + 1, self._view_total(), self._status_text())

    def _clamp_view_box(self) -> None:
        self.view_box = max(0, min(self.view_box, self._page_box_count(self.current_page) - 1))

    def _overlay_boxes(self) -> tuple[OverlayBox, ...]:
        if self.split_count > 1:
            return tuple(OverlayBox(b, "split", i)
                         for i, b in enumerate(self.document.crop_rects))
        rect = self._crop_rect(self.current_page)
        return (OverlayBox(rect, "auto", -1),) if rect is not None else ()

    def _status_text(self) -> str:
        total = self._view_total()
        pos = self._view_position() + 1
        cnt = self._page_box_count(self.current_page)
        if cnt > 1:
            return (f"page {pos} / {total}   "
                    f"(page {self.current_page + 1} split {self.view_box + 1}/{cnt})")
        return f"page {pos} / {total}"

    @property
    def has_document(self) -> bool:
        return self.page_count() > 0

    @property
    def can_detect(self) -> bool:
        return (self.page_count() > 0 and self.split_count == 1
                and (self.anchor_left or self.anchor_top))

    @property
    def can_apply(self) -> bool:
        return self.page_count() > 0 and (
            self.split_count == 1 or len(self.document.crop_rects) == self.split_count)

    @property
    def auto_active(self) -> bool:
        return self.document.auto_active

    @property
    def offsets(self) -> Offsets:
        return self.document.offsets

    @property
    def dewarp_on(self) -> bool:
        return self.document.dewarp_on

    @property
    def filter_mode(self) -> FilterMode:
        return self.document.filter_mode

    @property
    def filter_strength(self) -> int:
        return self.document.filter_strength

    @property
    def compress_preset(self) -> str:
        return self.settings.compress_preset

    @property
    def output_colours(self) -> str:
        return self.settings.output_colours

    @property
    def export_format(self) -> str:
        return self.settings.export_format

    @property
    def can_undo(self) -> bool:
        return self.history.can_undo

    @property
    def can_redo(self) -> bool:
        return self.history.can_redo

    @property
    def view_total(self) -> int:
        return self._view_total()

    @property
    def view_position(self) -> int:
        return self._view_position()
