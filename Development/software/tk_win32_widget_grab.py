"""Grab a Tk widget as a Pillow image via Win32 BitBlt (window DC only).

Use this instead of :func:`PIL.ImageGrab.grab` when you must avoid copying
whatever is visible on the monitor behind or around the window (IDE, browser).

Requires Windows. Callers should run ``widget.update()`` / ``update_idletasks()``
shortly before grabbing so pixels are current.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

if sys.platform != "win32":
    raise ImportError("tk_win32_widget_grab is Windows-only")

from PIL import Image

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


def grab_tk_widget_win32(widget: "tk.Misc") -> Image.Image:
    """Return RGB image of the widget's HWND (``GetWindowDC``), not a screen rectangle."""

    widget.update_idletasks()
    widget.update()

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    w = max(1, int(widget.winfo_width()))
    h = max(1, int(widget.winfo_height()))
    hwnd = wintypes.HWND(int(widget.winfo_id()))

    hdc_scr = user32.GetWindowDC(hwnd)
    if not hdc_scr:
        raise OSError("GetWindowDC failed")
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_scr)
        if not hdc_mem:
            raise OSError("CreateCompatibleDC failed")
        bmp = gdi32.CreateCompatibleBitmap(hdc_scr, w, h)
        if not bmp:
            gdi32.DeleteDC(hdc_mem)
            raise OSError("CreateCompatibleBitmap failed")

        old = gdi32.SelectObject(hdc_mem, bmp)
        try:
            if not gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_scr, 0, 0, SRCCOPY):
                raise OSError("BitBlt failed")

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32

            raw = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(hdc_mem, bmp, 0, h, raw, ctypes.byref(bmi), DIB_RGB_COLORS)
            if int(lines) == 0:
                raise OSError("GetDIBits failed")
            return Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", 0, 1)
        finally:
            gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(hdc_mem)
    finally:
        user32.ReleaseDC(hwnd, hdc_scr)
