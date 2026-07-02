"""Static Help text (spec §16). One Contents button per section; clicking scrolls the body to it.
Pure data — the help window (ui_build.py) renders this, it never reads the model. The section
list must always end with About (inv 36).
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.constants import APP_VERSION

INTRO = "Crop, straighten, and clean PDFs and scans for e-readers, phones and tablets."


@dataclass(frozen=True)
class HelpSection:
    title: str
    body: str


SECTIONS: tuple[HelpSection, ...] = (
    HelpSection(
        "1. Open files",
        "Press Load Files or Ctrl+O. "
        "You can pick several PDFs and images at once — they are joined into one document "
        "in the order you selected them. "
        "Each PDF adds all its pages. Each image adds one page. "
        "Loading always clears the previous document, all crops, and all history.",
    ),
    HelpSection(
        "2. Document type",
        "SmartCrop reads the document and shows a badge: Normal or Scanned. "
        "Normal means at least one page has real text or vector drawings (a typical PDF). "
        "Scanned means every page is a plain photo or scan with no text layer. "
        "You cannot change this — it is detected automatically. "
        "Scanned mode adds a Scan Processing section that is hidden in Normal mode.",
    ),
    HelpSection(
        "3. Choose which pages to work on",
        "The Pages selector at the top applies to every action below it. "
        "All, Odd, and Even are self-explanatory. "
        "Selected lets you type a pattern: page numbers (1, 3), ranges (2-8), "
        "or slices (1:10:2), mixed freely. "
        "Current sets the pattern to the page you are viewing right now.",
    ),
    HelpSection(
        "4. Scan processing (scanned documents only)",
        "Run these before setting the crop. Each button reads from the original scan, "
        "so you can press it multiple times or try different settings without harm. "
        "\n\n"
        "Dewarp & Deskew straightens curved or tilted pages. Run this first if your scan "
        "has page curl or is slightly rotated. "
        "\n\n"
        "B/W converts the page to pure black and white. Best for text-only scans. "
        "\n\n"
        "Sharpen keeps gray tones but flattens uneven lighting and sharpens the image. "
        "Better for pages with photos or mixed content. "
        "\n\n"
        "B/W and Sharpen cannot both be on at the same time. "
        "Strength 1 is cautious, 2 is the normal default, 3 is aggressive.",
    ),
    HelpSection(
        "5. Set the crop window",
        "The crop window is shown on the canvas as a dashed rectangle with handles. "
        "You have two ways to place it — both behave the same afterwards. "
        "\n\n"
        "Auto-detect: press the button and SmartCrop finds the content on each selected page, "
        "building one shared crop frame that fits all pages the same way. "
        "\n\n"
        "Draw: click and drag on the page to draw the window yourself. It appears on every page, "
        "replaces the auto frame while it exists, and nothing is cropped yet — the page never "
        "zooms until you press Crop. "
        "\n\n"
        "Adjust: drag a corner to resize, a border to move one edge, or the inside to move the "
        "whole window. Esc or right-click during a drag cancels it; pressed again with no drag, "
        "it removes the drawn window (and then deactivates the auto frame). "
        "Press Crop to commit the window to the selected pages.",
    ),
    HelpSection(
        "6. Fine-tune with anchors and offsets",
        "Anchor Left and Anchor Top (in the Detect card) pin that edge of the shared crop "
        "to each page's own content rather than the union of all pages. "
        "Useful when margins differ across pages. At least one anchor must stay on. "
        "\n\n"
        "The Advanced card has four offset fields (L T R B). "
        "Each nudges one edge by a percentage of the page size. "
        "Positive values shrink the crop; negative values expand it. "
        "Out-of-range values snap to the page border automatically.",
    ),
    HelpSection(
        "7. Split pages",
        "Use Split (1 / 2 / 4) to turn each source page into that many output pages. "
        "Useful for scanning two book pages side by side. "
        "Choosing 2 or 4 draws an even grid of windows on the canvas. "
        "You can drag and resize each window just like a normal crop. "
        "Press Apply when all windows look right — the button requires exactly N windows per page. "
        "Same size keeps all windows the same dimensions.",
    ),
    HelpSection(
        "8. Keep ratio",
        "When Keep ratio is on, the crop height is always locked to width / ratio. "
        "This applies to every way you can change the crop: dragging handles, "
        "editing offsets, drawing a window, and split windows. "
        "The ratio field is editable and follows what you do: it starts at the page ratio, "
        "updates to the detected content after Auto-detect, and to your window after a draw — "
        "so turning the lock on keeps exactly the shape you see.",
    ),
    HelpSection(
        "9. Crop (commit)",
        "Press Crop (or Ctrl+Enter) to commit the current window — drawn or auto — to the "
        "selected pages. The canvas then shows each page exactly as it will be saved. "
        "Pages in the selection without any window are skipped, never blind-cropped. "
        "A committed page stays cropped while you work on others; drawing on it places a new "
        "window over the cropped view (still nothing moves until you press Crop again). "
        "Only Undo or Reset returns a page to its full extent. "
        "If the selection did not include the page you were viewing, the view jumps to the first "
        "processed page so you can check the result.",
    ),
    HelpSection(
        "10. Rotate and delete",
        "Rotate turns the selected pages 90° clockwise. Press it again for 180°, again for 270°. "
        "Delete removes the selected pages from the document. "
        "Both act on the Pages selector. Delete cannot be undone.",
    ),
    HelpSection(
        "11. Compress and colour",
        "These apply at the very end — after the crop — in both the preview and the export. "
        "\n\n"
        "Compress Document resamples each page to a target resolution. "
        "Original resolution keeps the native pixels. "
        "High (300 dpi), Medium (150 dpi), and Low (75 dpi) reduce file size. "
        "\n\n"
        "Output colours: Grayscale desaturates every page while keeping its tonal range. "
        "It is not a hard black-and-white — gradients and photos are preserved in gray. "
        "\n\n"
        "These settings survive Undo — they are not part of the crop history.",
    ),
    HelpSection(
        "12. Export",
        "Press Export or Ctrl+S. "
        "Pages with a committed crop export exactly as shown on screen. "
        "Pages without one export through the live auto-crop. "
        "\n\n"
        "PDF writes one file. JPG, PNG, and TIFF write one file per output page, "
        "numbered automatically. Use the arrow on the Export button to switch format. "
        "\n\n"
        "A progress bar appears for multi-page jobs. Cancel stops cleanly — "
        "no partial file is written.",
    ),
    HelpSection(
        "Undo, Redo, Reset",
        "Undo and Redo step through crop, rotation, and scan-processing history. "
        "The depth (how many steps are kept) is set in Settings. "
        "\n\n"
        "Reset clears everything — crops, rotation, processing, and history — "
        "and reloads the document. It cannot be undone.",
    ),
    HelpSection(
        "Keyboard shortcuts",
        "Ctrl+O  —  Load files\n"
        "Ctrl+Enter  —  Apply crop\n"
        "Ctrl+S  —  Export\n"
        "Ctrl+Z  —  Undo\n"
        "Ctrl+Y  —  Redo\n"
        "Left / Right  —  Previous / next page\n"
        "PgUp / PgDn  —  Previous / next page\n"
        "Mouse wheel on canvas  —  Previous / next page\n"
        "◀ ▶ on the canvas edges (appear on hover)  —  Previous / next page\n"
        "Enter in page box  —  Jump to that page\n"
        "Ctrl + / −  —  Scale the UI\n"
        "Ctrl 0  —  Reset UI scale\n"
        "Esc or right-click  —  Cancel a drag; with none, remove the crop window",
    ),
    HelpSection(
        "About",
        f"SmartCrop PDF {APP_VERSION}\n"
        "Crop, straighten, clean and compress PDFs and scans for comfortable reading "
        "on e-readers, phones and tablets.\n\n"
        "Built with Python, CustomTkinter, PyMuPDF, OpenCV and docuwarp.",
    ),
)
