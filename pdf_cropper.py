#!/usr/bin/env python3
"""SmartCrop PDF — entry point.  Run:  python pdf_cropper.py"""
import tkinter as tk

from smartcrop import PDFCropperApp


def main() -> None:
    root = tk.Tk()
    PDFCropperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
