"""Launch ``system_q_console`` (optional), foreground it, save a PNG — **does not** close the app by default."""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

HWND = ctypes.c_void_p
DWORD = ctypes.c_ulong
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong


class _PidHwnd(ctypes.Structure):
    _fields_ = [("pid", DWORD), ("out", ctypes.c_void_p)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


SW_RESTORE = 9
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = ctypes.c_bool


def _foreground_system_q_console(hwnd: HWND) -> None:
    """Raise the Tk chrome so the PNG matches what the operator sees."""

    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)


def _window_bbox(hwnd: HWND) -> tuple[int, int, int, int]:
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError("GetWindowRect failed")
    left, top = int(rect.left), int(rect.top)
    right, bottom = int(rect.right), int(rect.bottom)
    return (left, top, right, bottom)


class _PidHwndAny(ctypes.Structure):
    """target_pid == 0: first visible ``System Q Console``; else match that PID."""

    _fields_ = [("pid", DWORD), ("out", ctypes.c_void_p)]


def _make_enum_proc_any_console():
    @ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, ctypes.POINTER(_PidHwndAny))
    def cb(hwnd: HWND, pdata: ctypes.POINTER(_PidHwndAny)) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        want = int(pdata.contents.pid.value if hasattr(pdata.contents.pid, "value") else pdata.contents.pid)
        if want != 0:
            cpid = DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(cpid))
            if int(cpid.value) != want:
                return True
        n = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(n)
        user32.GetWindowTextW(hwnd, buf, n)
        if buf.value.startswith("System Q Console"):
            pdata.contents.out = hwnd
            return False
        return True

    return cb


def _find_system_q_hwnd(proc_pid: int | None = None) -> HWND | None:
    data = _PidHwndAny(DWORD(proc_pid or 0), None)
    user32.EnumWindows(_make_enum_proc_any_console(), ctypes.byref(data))
    return data.out


def _make_enum_proc():
    @ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, ctypes.POINTER(_PidHwnd))
    def cb(hwnd: HWND, pdata: ctypes.POINTER(_PidHwnd)) -> bool:  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        cpid = DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(cpid))
        want_pid = (
            int(pdata.contents.pid)
            if isinstance(pdata.contents.pid, int)
            else int(pdata.contents.pid.value)
        )
        if int(cpid.value) != want_pid:
            return True
        n = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(n)
        user32.GetWindowTextW(hwnd, buf, n)
        title = buf.value
        if title.startswith("System Q Console"):
            pdata.contents.out = hwnd
            return False
        return True

    return cb


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture desktop to eq_working_proof.png")
    ap.add_argument(
        "--grab-only",
        action="store_true",
        help="Only ImageGrab; do not start another console process.",
    )
    ap.add_argument(
        "--kill-after",
        action="store_true",
        help="After capture, terminate the spawned console (old automation behavior).",
    )
    ap.add_argument(
        "--window",
        action="store_true",
        help="Capture only the System Q Console window (foreground it first).",
    )
    ap.add_argument("-o", "--output", type=Path, default=None, help="PNG path (default: eq_working_proof.png here)")
    args = ap.parse_args()

    software = Path(__file__).resolve().parent
    out = args.output or (software / "eq_working_proof.png")
    proc = None
    if not args.grab_only:
        proc = subprocess.Popen(
            [sys.executable, str(software / "system_q_console.py")],
            cwd=str(software),
        )
    try:
        hwnd = None
        if proc is not None:
            data = _PidHwnd(DWORD(proc.pid), None)
            enum_cb = _make_enum_proc()
            for _ in range(50):
                time.sleep(0.2)
                data.out = None
                user32.EnumWindows(enum_cb, ctypes.byref(data))
                h = data.out
                if h:
                    hwnd = h
                    break
            # Tk needs a moment after hwnd exists — especially polar redraw + layout.
            time.sleep(3.5 if proc is not None else 0)
        elif args.window:
            for _ in range(30):
                hwnd = _find_system_q_hwnd(None)
                if hwnd:
                    break
                time.sleep(0.2)

        if args.window:
            if hwnd is None and proc is not None:
                hwnd = _find_system_q_hwnd(proc.pid)
            if hwnd is None:
                raise SystemExit("No visible window titled «System Q Console». Run system_q_console.py first.")
            _foreground_system_q_console(hwnd)
            time.sleep(0.45)
            bbox = _window_bbox(hwnd)
            ImageGrab.grab(bbox=bbox).save(out)
        else:
            if hwnd:
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
            elif proc is not None:
                time.sleep(2.0)
            ImageGrab.grab().save(out)
        print(f"Saved {out}")
    finally:
        if proc is not None and args.kill_after:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
