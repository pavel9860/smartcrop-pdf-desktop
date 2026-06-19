"""SmartCrop PDF — modular Tkinter/PyMuPDF crop utility.

`PDFCropperApp` is imported lazily so that headless use of `smartcrop.imaging`
(cv2/skimage only) does not require tkinter / a display.
"""
__all__ = ["PDFCropperApp"]
__version__ = "6.0"


def __getattr__(name):
    if name == "PDFCropperApp":
        from .app import PDFCropperApp
        return PDFCropperApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
