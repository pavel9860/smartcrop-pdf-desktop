# SmartCropPDF — Goals

## Purpose

Open-source, cross-platform (Windows/Ubuntu/macOS) desktop app that prepares books — native PDFs, scanned PDFs, or loose images — for comfortable reading on e-readers, tablets, and phones: combine many inputs into one document, crop to content, optionally filter/straighten scans, optionally split pages, compress to a target DPI, optionally output in grayscale. Many files in, one document out, in a chosen format (PDF / JPG / PNG / TIFF).

## In scope

|Capability|Behavior|
|-|-|
|Load & combine|Open one or many files at once (PDFs and/or images: jpg/jpeg/png/tif/tiff), combined into one document in selection order (one-by-one = click order; range/Select-All = directory order); each image = one page|
|Mode detection|Classify Normal (native) when any page carries vector data (text or drawing paths); Scanned only when every page is image-only; sets the mode badge on load|
|Crop|Manual or auto-detect content box — text-block union (Normal) or ink-mask bbox (Scanned) — with manual L/T/R/B offset override (in a collapsible Advanced card), per-edge anchors, drag handles; aspect-ratio lock enforced in every gesture|
|Split|2 and 4 preset with drag handles, manual 1/2/4-way split via user-drawn rectangles in reading order (①…④), applied uniformly across the document; enabling split disables auto-detect/anchors/offsets|
|Scan filter|Dewarp & deskew, plus optional filter (bilevel B/W or Sharpen — continuous-tone unsharp, 3 strength levels); explicit button press only, never automatic|
|Compress|Applied last: resample every embedded image to a chosen DPI (Original / High 300 / Medium 150 / Low 72) and fix wasteful encoding (deflate, garbage-collect) so the file is never bloated|
|Output colours|Live Compress-card control (Original colours / Grayscale): Grayscale desaturates every output page (tonal range preserved, no thresholding), in preview and export; takes effect immediately and is excluded from undo/redo history|
|Output|Export as PDF, JPG, PNG, or TIFF, via a split button. PDF = one file; JPG/PNG/TIFF = one file per output page. Split N → N, 2N or 4N output pages|
|History|Bounded undo/redo covering crop, rotate, dewarp, filter; per-page reset to source. Compress DPI and Output colours are excluded (live settings, not document state). Next actions do not override previous except filters and split to a different number of pages|

## Non-functional goals

|Target|
|-|
|UI never blocks; long operations run off main thread with cancelable progress|
|≤~150 ms/page for filter/dewarp at 200 DPI on a laptop|
|Raster cache LRU-bounded; resident memory independent of total page count|
|Detection and scan processing idempotent, re-run-safe from unprocessed source|
|All PyMuPDF/Tk access on main thread; workers touch only numpy/cv2 buffers|

## Platform & distribution

Python 3.10+, Tkinter/ttk UI, Docuwrap, PyMuPDF (PDF I/O), OpenCV/NumPy/scikit-image (imaging), optional ONNX dewarp model (degrades to deskew-only if absent). Native on Windows, Ubuntu, macOS. Source released open-source.

## Explicit non-goals

* OCR / searchable-text generation
* Thumbnail-based page picker
* Arbitrary N×M auto-grid split (fixed at 1/2/4, manually placed)

(Note: loading and combining several files in one run is now **in scope** — see Load & combine above. The output is still one document per run.)

## Open item

* MIT license.

