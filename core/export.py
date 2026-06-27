"""Scan processing (dewarp/filter), pages/resize options and apply/export/rotate for
SmartCropApp. Long operations run page-by-page on the main thread (`_run_batch`) under the
in-canvas progress overlay, so memory stays bounded and PyMuPDF/Tk stay main-thread.
Mixed into SmartCropApp.
"""
from __future__ import annotations

import os
from tkinter import filedialog, messagebox
from typing import List

import fitz
import numpy as np
from PIL import Image

import core.imaging
from core import render
from core.constants import DPI_PRESETS, SRC_DPI
from core.enums import FilterMode, Mode, PagesMode
from core.geometry import Box, rotate_box_cw, union_box

_FMT_EXT = {"PDF": "pdf", "JPG": "jpg", "PNG": "png", "TIFF": "tif"}


class ExportMixin:
    """Dewarp/filter, pages/resize, apply, export and rotate."""
    # ════════════════════════════════════════════════════════════════════
    #  SCAN PROCESSING
    # ════════════════════════════════════════════════════════════════════
    def run_dewarp(self):
        if self._busy:
            return
        self.dewarp_on = not self.dewarp_on
        self._refresh_scan_buttons()
        self._snapshot_history()
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Dewarp & Deskew", "Empty Pages selection.")
            return
        for i in indices:
            self._processed.setdefault(i, {})["dewarp"] = self.dewarp_on
        self._work_cache.clear()
        if self.dewarp_on and core.imaging.unwarp_available():     # warm the model first so the
            try:                                                   # first page isn't slow/skipped
                core.imaging.unwarp_bgr(np.full((32, 32, 3), 255, np.uint8))
            except Exception:
                pass
        self._run_batch(indices, self._work_image, lambda i, img: None,
                        lambda ok: self.render_page(), "Dewarp & Deskew")

    def set_filter_mode(self, mode: str):
        if self._busy:
            return
        self.filter_mode = FilterMode.NONE if self.filter_mode == mode else mode
        self._refresh_scan_buttons()
        self._run_filter()

    def set_filter_strength(self, n: int):
        self.filter_strength = n
        if self.filter_mode != FilterMode.NONE:
            self._run_filter()

    def _refresh_scan_buttons(self):
        self._set_active(self.btn_dewarp, self.dewarp_on)
        self._set_active(self.btn_bw, self.filter_mode == FilterMode.BW)
        self._set_active(self.btn_sharpen, self.filter_mode == FilterMode.SHARPEN)

    def _run_filter(self):
        self._snapshot_history()
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Filter", "Empty Pages selection.")
            return
        filt = None if self.filter_mode == FilterMode.NONE else (self.filter_mode, self.filter_strength)
        for i in indices:
            self._processed.setdefault(i, {})["filter"] = filt
        self._work_cache.clear()
        self._run_batch(indices, self._work_image, lambda i, img: None,
                        lambda ok: self.render_page(), "Filtering pages")

    def _run_batch(self, indices, work_fn, on_result, on_done, title):
        """Process `indices` one page per Tk tick on the MAIN thread, so PyMuPDF/Tk stay on the
        main thread and the raster caches stay LRU-bounded (one page resident at a time instead
        of prerendering and holding all of them). `on_result(i, value)` consumes each page's
        output immediately; `on_done(ok)` runs at the end with ok=False if the user cancelled or
        a page errored. The overlay shows progress; Cancel sets `self._cancelled` and stops
        promptly. The UI stays responsive between pages (events run between ticks)."""
        indices = list(indices)
        total = len(indices)
        if total <= 1:                               # fast path: no overlay for a single page
            for i in indices:
                on_result(i, work_fn(i))
            on_done(True)
            return
        self._busy = True
        self._cancelled = False
        self._set_controls_enabled(False)
        self._show_progress(title, total)
        st = {"n": 0}

        def tick():
            if self._cancelled:
                self._hide_progress(); self._finish_busy(); on_done(False); return
            i = indices[st["n"]]
            try:
                on_result(i, work_fn(i))
            except Exception as exc:
                self._hide_progress(); self._finish_busy()
                messagebox.showerror(title, str(exc)); on_done(False); return
            st["n"] += 1
            self.ov_bar.set(st["n"] / total)
            self.ov_count.configure(text=f"{st['n']} / {total}")
            if st["n"] >= total:
                self._hide_progress(); self._finish_busy(); on_done(True); return
            self.root.update_idletasks()             # flush the bar/counter redraw before the next
            #                                          heavy page, so progress advances smoothly
            #                                          instead of in starved, fragmental jumps
            self.root.after(1, tick)

        self.root.after(1, tick)

    def _finish_busy(self):
        self._busy = False
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in (getattr(self, n, None) for n in
                  ("btn_apply", "btn_detect", "btn_dewarp", "btn_bw", "btn_sharpen")):
            if b is not None:
                try:
                    b.configure(state=state)
                except Exception:
                    pass

    # ════════════════════════════════════════════════════════════════════
    #  PAGES / RESIZE
    # ════════════════════════════════════════════════════════════════════
    def set_pages_mode(self, value: str):
        self.pages_mode = {"All": PagesMode.ALL, "Odd": PagesMode.ODD,
                           "Even": PagesMode.EVEN, "Selected": PagesMode.SELECT}[value]
        if value != "Selected" and self.current_follow:       # leaving Selected ends follow mode
            self.current_follow = False
            self._refresh_current_btn()
        if hasattr(self, "pages_seg") and self.pages_seg.get() != value:
            self.pages_seg.set(value)                # reflect programmatic changes (e.g. Current, #3)
        self._sync_pages_ui()

    def _sync_pages_ui(self):
        if self.pages_mode == PagesMode.SELECT:
            self.select_row.pack(fill="x", pady=(8, 0))
        else:
            self.select_row.pack_forget()

    def _target_size(self, w, h):
        """Output pixel size for a crop of page-size w×h (page units), or None to keep the native
        crop pixels. Driven by Compress Document (§7.6, §12.6): `Original resolution` → None;
        High/Medium/Low resample the crop to `dpi/72 · crop-size-in-points` (§12.1). Box dims are
        points (Normal) or px@SRC_DPI (Scanned), so convert to points before scaling by the DPI."""
        dpi = DPI_PRESETS[self.compress_var.get()]
        if dpi is None:
            return None
        per_point = (SRC_DPI / 72.0) if self.mode == Mode.SCANNED else 1.0
        k = (dpi / 72.0) / per_point
        return (w * k, h * k)

    def _remove_colours(self) -> bool:
        """True when Output colours = Grayscale (desaturate every output page, §7.6)."""
        return self.colours_var.get() == "Grayscale"

    # ════════════════════════════════════════════════════════════════════
    #  APPLY / EXPORT / ROTATE
    # ════════════════════════════════════════════════════════════════════
    def _page_crop_boxes(self, i: int) -> List[Box]:
        """Crop box(es) for page i in page coords (split → N rects, auto → the crop rect)."""
        w, h = self._page_dims(i)
        if self.split_count > 1:
            return list(self.crop_rects)
        return [self._crop_rect(i) or Box(0, 0, w, h)]

    def apply_crop(self):
        if self._busy or self.page_count() == 0:
            return
        if self.split_count > 1 and len(self.crop_rects) != self.split_count:
            messagebox.showwarning("Apply Crop", f"Draw exactly {self.split_count} rectangle(s).")
            return
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Apply Crop", "Empty Pages selection.")
            return
        self._snapshot_history()
        for i in indices:                            # commit the crop state per page
            self._applied[i] = self._page_crop_boxes(i)
        self.view_box = 0                            # land on the first split of the current page
        self.render_page()
        n_out = sum(len(self._applied[i]) for i in indices)
        self.status_msg(f"✓ Cropped {len(indices)} page(s) → {n_out} output page(s). "
                        f"Export to save.")

    def _output_images(self, i: int) -> List[Image.Image]:
        """Render page i to its committed output image(s). A page with no committed crop still
        exports through its **live** crop (the auto-detect rectangle shown in the preview) — it is
        never silently exported whole — so a crop visible on screen is never dropped from the file.
        Shares `render.output_image` with the preview so on-screen == saved (WYSIWYG)."""
        work = self._work_image(i)
        w, h = self._page_dims(i)
        if i in self._applied:
            boxes = self._applied[i]
        else:
            cb = self._crop_rect(i) if self.split_count == 1 else None
            boxes = [cb] if cb is not None else [Box(0, 0, w, h)]
        rc = self._remove_colours()
        return [render.output_image(work, box, w, h, self._target_size(box.width, box.height), rc)
                for box in boxes]

    def export(self):
        """Export every page in the chosen format (§12.7): PDF = one file (images embedded);
        JPG/PNG/TIFF = one file per output page with an index suffix. Commits the live crop of any
        uncommitted selected page first (and re-commits all under Split), so a crop on screen is
        always written; already-committed pages keep their box. Streams page-by-page (§12.5)."""
        if self._busy or self.page_count() == 0:
            return
        fmt = self.format_var.get()
        ext = _FMT_EXT[fmt]
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning(f"Export {fmt}", "Empty Pages selection.")
            return
        for i in indices:
            if self.split_count > 1 or i not in self._applied:
                self._applied[i] = self._page_crop_boxes(i)
        base = os.path.splitext(os.path.basename(self._pdf_path))[0] if self._pdf_path else "output"
        stem = base + self.output_postfix_var.get()  # <name><postfix>.<ext> (§12.5)
        folder = self.output_folder_var.get().strip() or (
            os.path.dirname(self._pdf_path) if self._pdf_path else "")   # default: source folder
        path = filedialog.asksaveasfilename(title=f"Export {fmt}", defaultextension="." + ext,
                                            initialdir=folder or None, initialfile=f"{stem}.{ext}",
                                            filetypes=[(fmt, f"*.{ext}")])
        if not path:
            return
        pages = list(range(self.page_count()))       # every page (committed = cropped, else whole)
        if fmt == "PDF":
            self._export_pdf(path, pages)
        else:
            self._export_images(path, pages, fmt, ext)

    def _export_pdf(self, path, pages):
        out_doc = fitz.open()
        count = {"n": 0}

        def write(i, images):                        # insert this page's crop(s) and drop them —
            for img in images:                       # only one page of pixels is ever resident
                pg = out_doc.new_page(width=img.width, height=img.height)
                pg.insert_image(pg.rect, stream=render.pil_to_png_bytes(img))
                count["n"] += 1

        def done(ok):
            if not ok:                               # cancelled / errored → discard, no file written
                out_doc.close()
                return
            try:
                out_doc.save(path, garbage=4, deflate=True)   # garbage-collect + deflate (§12.6)
            except Exception as exc:
                out_doc.close()
                messagebox.showerror("Export PDF", str(exc))
                return
            out_doc.close()
            self.status_msg(f"✓ Exported {count['n']} page(s).")
            messagebox.showinfo("Export PDF", f"Saved {count['n']} page(s) to:\n{path}")

        self._run_batch(pages, self._output_images, write, done, "Exporting pages")

    def _export_images(self, path, pages, fmt, ext):
        """One file per output page: <stem>_001.<ext>, _002, … (§12.7). Streams page-by-page."""
        stem = os.path.splitext(path)[0]
        count = {"n": 0}

        def write(i, images):
            for img in images:
                count["n"] += 1
                p = f"{stem}_{count['n']:03d}.{ext}"
                if fmt == "JPG":
                    img.save(p, "JPEG", quality=88)
                elif fmt == "PNG":
                    img.save(p, "PNG")
                else:                                # TIFF — deflate-compressed
                    img.save(p, "TIFF", compression="tiff_deflate")

        def done(ok):
            if not ok:
                return
            self.status_msg(f"✓ Exported {count['n']} file(s).")
            messagebox.showinfo(f"Export {fmt}",
                                f"Saved {count['n']} file(s):\n{stem}_001.{ext} …")

        self._run_batch(pages, self._output_images, write, done, f"Exporting {fmt}")

    def rotate_pages(self):
        if self._busy or self.page_count() == 0:
            return
        indices = self._resolve_pages()
        if not indices:
            messagebox.showwarning("Rotate", "Empty Pages selection.")
            return
        self._snapshot_history()
        for i in indices:                            # angle-map rotate: undoable, works in scan mode
            w, h = self._page_dims(i)                # page size BEFORE this 90° step
            self._rotation[i] = (self._rotation.get(i, 0) + 90) % 360
            for d in (self._source_cache, self._work_cache):
                d.pop(i, None)                       # re-render at the new angle
            if i in self._applied:                   # carry the committed crop through the turn
                self._applied[i] = [rotate_box_cw(b, w, h) for b in self._applied[i]]
            if i in self._detect_cache:              # keep the detected content box too
                self._detect_cache[i] = rotate_box_cw(self._detect_cache[i], w, h)
        if self.auto_active and self._detect_cache:  # rebuild the live frame from rotated boxes
            self._union = union_box(list(self._detect_cache.values()))
            self._suspend = True                     # L/T/R/B map to rotated edges → reset to 0
            for var in (self.left_off, self.top_off, self.right_off, self.bottom_off):
                var.set(0.0)
            self._suspend = False
            self._sync_ratio_label()
        self._refresh_detect_enabled()
        self.render_page()
        self.status_msg(f"Rotated {len(indices)} page(s) 90° CW; crop preserved.")

