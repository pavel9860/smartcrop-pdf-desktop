"""Document & raster layer for SmartCropApp: open/classify/reset PDFs, page sizing, the
synthetic placeholder, and the cached source/work rasters (deskew/dewarp/filter).
Mixed into SmartCropApp; see core/app.py.
"""
from __future__ import annotations

import os
import random
from tkinter import filedialog, messagebox
from typing import List, Tuple

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw

import core.imaging
from core.constants import (SRC_DPI, NORMAL_DPI, SYNTH_PAGES, MODE_TEXT_MIN, IMAGE_LOAD_EXT,
                            CLEAN_AMOUNT, STATUS_IDLE_MS, THEMES)
from core.enums import Mode, FilterMode
from core.geometry import Box

class DocumentMixin:
    """PDF I/O, classification, page sizing and the source/work raster caches."""
    # ════════════════════════════════════════════════════════════════════
    #  DOCUMENT
    # ════════════════════════════════════════════════════════════════════
    def _load_synthetic(self) -> None:
        self.doc = None
        rnd = random.Random(7)
        self._pt_size = [(600 + rnd.uniform(-15, 15), 820 + rnd.uniform(-20, 20))
                         for _ in range(SYNTH_PAGES)]
        self._reset_doc_state()
        self._set_mode(Mode.NORMAL)
        self.status_msg(f"Synthetic {SYNTH_PAGES}-page sample — Load Files for real files.")

    def load_files(self) -> None:
        """Open one or many files (PDFs and/or images) and combine them in selection order (§7.1a)."""
        img_globs = " ".join("*" + e for e in IMAGE_LOAD_EXT)
        paths = filedialog.askopenfilenames(
            title="Load Files", filetypes=[("PDF & images", img_globs), ("All files", "*.*")])
        if paths:
            self._open_files(list(paths))

    def _open_files(self, paths: List[str]) -> None:
        """Concatenate the chosen files into ONE working document in selection order: each PDF
        contributes all its pages, each image becomes one page sized to the image (§7.1a). Then
        classify (§4) and set the mode. Reset re-runs this with the same inputs (§13)."""
        try:
            doc = self._combine_files(paths)
            if doc.page_count == 0:
                raise ValueError("No pages to load.")
        except Exception as exc:
            messagebox.showerror("Load Files", f"Could not open the selected files:\n{exc}")
            return
        self.doc = doc
        self._input_paths = list(paths)
        self._pdf_path = paths[0]                     # drives the suggested export name / title
        title = os.path.basename(paths[0]) + (f"  (+{len(paths) - 1} more)" if len(paths) > 1 else "")
        self.root.title(f"SmartCrop PDF — {title}")
        self._pt_size = [(doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)]
        self._reset_doc_state()
        mode = self._classify_document()
        self._set_mode(mode)
        self.status_msg(f"Loaded {len(paths)} file(s) → {doc.page_count} pages — "
                        f"classified {mode.capitalize()}.")

    @staticmethod
    def _combine_files(paths: List[str]) -> fitz.Document:
        combined = fitz.open()
        for path in paths:
            if os.path.splitext(path)[1].lower() == ".pdf":
                with fitz.open(path) as src:
                    combined.insert_pdf(src)
            else:                                    # image → one page sized to the image
                with fitz.open(path) as img:
                    pdf_bytes = img.convert_to_pdf()
                with fitz.open("pdf", pdf_bytes) as img_pdf:
                    combined.insert_pdf(img_pdf)
        return combined

    def reset_document(self):
        """Reset everything to the just-opened state: re-load + re-combine the same input files
        (or the synthetic demo), clearing all crops/rotations/processing/history (§13)."""
        if self.doc is not None and self._input_paths:
            self.history.clear(); self.redo_stack.clear()
            self._open_files(self._input_paths)
        else:                                        # synthetic demo doc
            self._reset_doc_state()
            self._set_mode(Mode.NORMAL)
            self._load_synthetic()
        self.status_msg("Reset to the original document.")

    def _reset_doc_state(self) -> None:
        self.current_page = 0
        self.view_box = 0
        self.current_follow = False
        for d in (self._processed, self._source_cache, self._work_cache, self._detect_cache):
            d.clear()
        self._union = None
        self.auto_active = False
        self.split_count = 1                          # back to single-crop; rects belong to no split
        self.crop_rects.clear()
        self.history.clear()
        self.redo_stack.clear()
        self.dewarp_on = False
        self.filter_mode = FilterMode.NONE
        self.filter_strength = 2
        self._applied.clear()
        self._rotation.clear()
        for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
            var.set(0.0)
        if hasattr(self, "split_seg"):                # resync split widgets so Split is usable
            self.split_seg.set("1")
            self._sync_split_ui()
            self._set_detect_enabled(True)
        if hasattr(self, "strength_seg"):
            self.strength_seg.set("2")
        if hasattr(self, "btn_bw"):                   # drop highlight of reset functions
            self._refresh_scan_buttons()
        if hasattr(self, "btn_current"):
            self._refresh_current_btn()

    def page_count(self) -> int:
        return len(self._pt_size)

    def _classify_document(self) -> str:
        """Normal if ANY page carries vector data — real text (≥ MODE_TEXT_MIN chars) or a vector
        drawing path; Scanned only when every page is image-only (§4). One native page (a mixed
        load including a born-digital PDF) makes the whole document Normal."""
        if self.doc is None:
            return self.mode
        for i in range(self.doc.page_count):
            page = self.doc[i]
            if len(page.get_text().strip()) >= MODE_TEXT_MIN or page.get_drawings():
                return Mode.NORMAL
        return Mode.SCANNED

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._detect_cache.clear()
        self._work_cache.clear()
        self._union = None
        self.auto_active = False
        if hasattr(self, "scan_card"):
            if mode == Mode.SCANNED:
                self.scan_card.pack(fill="x", padx=4, pady=6, after=self.pages_card)   # §6 order
            else:
                self.scan_card.pack_forget()
            self.controls._parent_canvas.yview_moveto(0.0)   # no gap at top after switch
        self._refresh_mode_badge()
        self.render_page()

    def _refresh_mode_badge(self) -> None:
        if not hasattr(self, "mode_badge"):
            return
        scan = self.mode == Mode.SCANNED
        self.mode_badge.configure(text="SCANNED" if scan else "NORMAL",
                                  fg_color=THEMES["dark"]["BADGE_SCAN"] if scan
                                  else THEMES["dark"]["BADGE_NORMAL"])

    def status_msg(self, text: str) -> None:
        if hasattr(self, "status"):
            self.status.configure(text=text)
            self.root.after(STATUS_IDLE_MS, self._status_idle)

    def _status_idle(self) -> None:
        if not self._busy and hasattr(self, "status"):
            self.status.configure(text=self._view_status())

    def _page_dims(self, idx: int) -> Tuple[float, float]:
        w, h = self._pt_size[idx]
        if self.mode == Mode.SCANNED:
            k = SRC_DPI / 72.0
            w, h = w * k, h * k
        if self._rotation.get(idx, 0) % 180 == 90:    # rotation swaps page dimensions
            return h, w
        return w, h

    # ════════════════════════════════════════════════════════════════════
    #  RASTER
    # ════════════════════════════════════════════════════════════════════
    def _source_image(self, idx: int) -> Image.Image:
        img = self._source_cache.get(idx)
        if img is not None:
            return img
        if self.doc is not None:
            pm = self.doc[idx].get_pixmap(dpi=int(SRC_DPI if self.mode == Mode.SCANNED else NORMAL_DPI),
                                          alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        else:
            img = self._synthetic_image(idx)
        ang = self._rotation.get(idx, 0)              # apply page rotation
        if ang:
            img = img.rotate(-ang, expand=True)       # PIL rotates CCW; -ang = clockwise
        self._source_cache[idx] = img
        return img

    def _synthetic_image(self, idx: int) -> Image.Image:
        w, h = self._pt_size[idx]
        img = Image.new("RGB", (int(w), int(h)), "white")
        d = ImageDraw.Draw(img)
        rnd = random.Random(idx * 31 + 1)
        box = self._synthetic_text_box(idx, w, h)
        if self.mode == Mode.NORMAL:
            y = box.y0
            while y < box.y1 - 10:
                d.line([(box.x0, y), (box.x1 - rnd.uniform(0, w * 0.18), y)],
                       fill=(70, 70, 75), width=2)
                y += rnd.uniform(14, 20)
            d.rectangle([box.x0, box.y0, box.x1, box.y1], outline=(210, 210, 215))
            return img
        d.rectangle([box.x0, box.y0, box.x1, box.y1], fill=(60, 60, 65))
        for _ in range(40):
            x, y = rnd.uniform(box.x0, box.x1), rnd.uniform(box.y0, box.y1)
            d.ellipse([x, y, x + 3, y + 3], fill=(230, 230, 225))
        return img.rotate(rnd.uniform(-5, 5), fillcolor="white", resample=Image.BICUBIC)

    def _synthetic_text_box(self, idx, w, h) -> Box:
        rnd = random.Random(idx * 17 + 3)
        return Box(w * (0.09 + rnd.uniform(-0.02, 0.03)), h * (0.10 + rnd.uniform(-0.02, 0.03)),
                   w * (1 - 0.09 - rnd.uniform(-0.02, 0.03)), h * (1 - 0.13 - rnd.uniform(-0.03, 0.03)))

    def _work_image(self, idx: int) -> Image.Image:
        cached = self._work_cache.get(idx)
        if cached is not None:
            return cached
        src = self._source_image(idx)
        if self.mode != Mode.SCANNED:
            self._work_cache[idx] = src
            return src
        proc = self._processed.get(idx, {})
        bgr = cv2.cvtColor(np.array(src), cv2.COLOR_RGB2BGR)
        if proc.get("dewarp"):
            bgr = self._dewarp_bgr(bgr)
        filt = proc.get("filter")
        if filt:
            fmode, strength = filt
            if fmode == FilterMode.BW:
                g = core.imaging.clean_document_bilevel(bgr, strength=strength, upscale=1.0)
            else:
                g = core.imaging.sharpen_grayscale(bgr, strength=strength,
                                                   amount=CLEAN_AMOUNT[strength])
            bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        out = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        self._work_cache[idx] = out
        return out

    def _dewarp_bgr(self, bgr: np.ndarray) -> np.ndarray:
        """Real learned mesh dewarp when docuwarp is present; otherwise deskew-only."""
        if core.imaging.unwarp_available():
            try:
                return core.imaging.unwarp_bgr(bgr)
            except Exception:
                pass
        return core.imaging.deskew_auto(bgr)[0]

    def _gray_for_detect(self, idx: int) -> np.ndarray:
        img = self._work_image(idx) if self.mode == Mode.SCANNED else self._source_image(idx)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

