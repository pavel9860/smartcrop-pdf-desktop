# SmartCropPDF — Goals

## Purpose
Open-source, cross-platform (Windows/Ubuntu/macOS) desktop app that prepares book PDFs — native or scanned — for comfortable reading on e-readers, tablets, and phones: crop to content, optionally clean/straighten scans, optionally split pages, resize to a target device. One PDF in, one PDF out, one file per run.

## In scope

| Capability | Behavior |
|---|---|
| Mode detection | Per-page classify Normal (vector) vs Scanned (raster) by text length + image coverage; document mode = majority vote, bias Normal on ties; manual override badge resets detection/cache |
| Crop | Auto-detect content box — text-block union (Normal) or ink-mask bbox (Scanned) — with manual L/T/R/B offset override, per-edge anchors, drag handles; optional aspect-ratio lock (single-crop mode only) |
| Split | Manual 1/2/4-way split via user-drawn rectangles in reading order (①…④), applied uniformly across the document; enabling split disables auto-detect/anchors/offsets |
| Scan cleanup | Dewarp (mesh unwarp) + deskew, plus optional clean (bilevel B/W or grayscale-sharpen, 3 strength levels); explicit button press only, never automatic |
| Resize | Applied last: original size, device/monitor preset, or custom W×H |
| Output | PDF only. Normal: vector preserved via clipped page re-render. Scanned: processed/cropped raster embedded as image page. Split N → N output pages |
| History | Bounded undo/redo covering crop, rotate, dewarp, clean; per-page reset to source |

## Non-functional goals

| Target |
|---|
| UI never blocks; long operations run off main thread with cancelable progress |
| ≤~150 ms/page for clean/dewarp at 200 DPI on a laptop |
| Raster cache LRU-bounded; resident memory independent of total page count |
| Detection and scan processing idempotent, re-run-safe from unprocessed source |
| All PyMuPDF/Tk access on main thread; workers touch only numpy/cv2 buffers |

## Platform & distribution
Python 3.10+, Tkinter/ttk UI, PyMuPDF (PDF I/O), OpenCV/NumPy/scikit-image (imaging), optional ONNX dewarp model (degrades to deskew-only if absent). Native on Windows, Ubuntu, macOS. Source released open-source.

## Explicit non-goals
- OCR / searchable-text generation
- Thumbnail-based page picker
- Arbitrary N×M auto-grid split (fixed at 1/2/4, manually placed)
- Multi-file batch in one run (one document per run; "batch" elsewhere = intra-document parallel page processing)

## Open item
- MIT license.
