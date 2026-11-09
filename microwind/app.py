"""Launch, inspect and screenshot the real Microwind / DSCH windows.

ctypes only — no pywinauto, no pyautogui, no extra dependency.  Everything here is
best-effort and always reports what it actually observed: a screenshot is taken of the
live screen, and a window title is returned verbatim so a caller can prove what was open.

Scope limits, stated up front:
  * window control is menu-keyboard only (Alt, F, O); no mouse clicks and no UIA tree walk
  * `close()` kills only the PID we started, never by image name
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:  # import-safe on Linux/macOS; every app-control entry point raises clearly
    wintypes = None
    user32 = None
    EnumWindowsProc = None


# ---------------------------------------------------------------------------
# Keyboard injection (SendInput).  PostMessage key events do not work on VCL apps:
# the menu only opens for input that went through the real message pump.  Measured:
# Alt, F, O opens Microwind's File->Open dialog; Ctrl+O does nothing (no such shortcut).
# ---------------------------------------------------------------------------


if _IS_WINDOWS:

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def _key(vk: int, up: bool = False) -> None:
        inp = _INPUT()
        inp.type = 1                      # INPUT_KEYBOARD
        inp.u.ki.wVk = vk
        inp.u.ki.dwFlags = 2 if up else 0  # KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def tap(vk: int, hold: float = 0.05) -> None:
        _key(vk)
        time.sleep(hold)
        _key(vk, up=True)

    def _edit_handle(dialog: int) -> int:
        """The filename edit of the Win32 common file dialog."""
        combo_ex = user32.FindWindowExW(dialog, 0, "ComboBoxEx32", None)
        combo = user32.FindWindowExW(combo_ex, 0, "ComboBox", None) if combo_ex else 0
        edit = user32.FindWindowExW(combo, 0, "Edit", None) if combo else 0
        return edit or user32.FindWindowExW(dialog, 0, "Edit", None)


VK_ALT, VK_F, VK_O, VK_RETURN, VK_ESC, VK_CTRL, VK_A = 0x12, 0x46, 0x4F, 0x0D, 0x1B, 0x11, 0x41


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int

    def to_dict(self) -> dict:
        return {"hwnd": self.hwnd, "title": self.title, "pid": self.pid}


class AppError(RuntimeError):
    pass


def _require_windows() -> None:
    if not _IS_WINDOWS:
        raise AppError("application-control tools require Windows")


def _window_pid(hwnd: int) -> int:
    _require_windows()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def list_windows(pid: int | None = None, title_contains: str | None = None) -> list[WindowInfo]:
    _require_windows()
    found: list[WindowInfo] = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        wpid = _window_pid(hwnd)
        if pid is not None and wpid != pid:
            return True
        if title_contains and title_contains.lower() not in title.lower():
            return True
        found.append(WindowInfo(int(hwnd), title, wpid))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def find_dialogs(pid: int) -> list[WindowInfo]:
    """Modal dialogs (`#32770`) belonging to `pid` — i.e. load/parse error boxes."""
    out = []
    for win in list_windows(pid=pid):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(win.hwnd, cls, 64)
        if cls.value == "#32770" and win.title:
            out.append(win)
    return out


def focus(hwnd: int) -> bool:
    _require_windows()
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    return bool(user32.SetForegroundWindow(hwnd))


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    _require_windows()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def screenshot(path: str | Path) -> Path:
    """Capture the whole screen with .NET (no Python imaging dependency).

    The whole desktop is captured because it reliably contains the target window without
    needing window-handle plumbing; `focus()` is called first by the caller.
    """
    _require_windows()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    quoted = str(target).replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
        "$g=[System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); "
        f"$bmp.Save('{quoted}',[System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose()"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0 or not target.is_file():
        raise AppError(
            "screenshot failed: " + (proc.stderr.decode("utf-8", "replace")[:400] or "no file produced")
        )
    return target


def launch(exe: str | Path, args: list[str] | None = None, cwd: str | Path | None = None) -> subprocess.Popen:
    _require_windows()
    exe = Path(exe)
    if not exe.is_file():
        raise AppError(f"executable not found: {exe}")
    cmd = [str(exe)] + [str(a) for a in (args or [])]
    return subprocess.Popen(cmd, cwd=str(cwd or exe.parent))


def wait_for_window(pid: int, timeout: float = 40.0, title_contains: str | None = None) -> WindowInfo:
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = list_windows(pid=pid, title_contains=title_contains)
        if wins:
            return wins[0]
        time.sleep(0.5)
    raise AppError(f"no window appeared for pid {pid} within {timeout:.0f}s")


def close(pid: int, wait: float = 10.0) -> bool:
    """Terminate exactly the process we started (never by image name)."""
    _require_windows()
    proc = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if not list_windows(pid=pid):
            return proc.returncode == 0
        time.sleep(0.3)
    return False


def dismiss_startup_dialogs(pid: int, attempts: int = 6, pause: float = 1.0) -> list[str]:
    """Close the `About` splash so the main window can take focus."""
    closed: list[str] = []
    for _ in range(attempts):
        targets = [w for w in list_windows(pid=pid) if "about" in w.title.lower()]
        if not targets:
            break
        for win in targets:
            user32.PostMessageW(win.hwnd, 0x0010, 0, 0)     # WM_CLOSE
            closed.append(win.title)
        time.sleep(pause)
    return closed


def main_window(pid: int, prefer: str | None = None) -> WindowInfo:
    """The largest non-splash window of the process (optionally title-filtered)."""
    wins = [w for w in list_windows(pid=pid) if "about" not in w.title.lower()]
    if prefer:
        hits = [w for w in wins if prefer.lower() in w.title.lower()]
        if hits:
            wins = hits
    if not wins:
        raise AppError(f"no main window for pid {pid}")
    return max(wins, key=lambda w: (window_rect(w.hwnd)[2] - window_rect(w.hwnd)[0])
               * (window_rect(w.hwnd)[3] - window_rect(w.hwnd)[1]))


def open_document(pid: int, path: str | Path, timeout: float = 25.0) -> dict:
    """File -> Open via the real menu, then type the path into the dialog.

    The documented command line that worked in 3.1 is **ignored** by 3.5 (measured: the
    title stays `Microwind35 - example` for a mask argument, a name-only argument, and an
    argument plus rule file).  Menu navigation is the only verified way to load a file.
    """
    target = Path(path).resolve()
    win = main_window(pid)
    focus(win.hwnd)
    time.sleep(0.8)
    tap(VK_ALT)
    time.sleep(0.6)
    tap(VK_F)
    time.sleep(1.0)
    tap(VK_O)
    deadline = time.time() + timeout
    dialog = None
    while time.time() < deadline:
        hits = [w for w in list_windows(pid=pid) if w.title.strip().lower() == "open"]
        if hits:
            dialog = hits[0]
            break
        time.sleep(0.4)
    if dialog is None:
        raise AppError("File->Open dialog did not appear")
    edit = _edit_handle(dialog.hwnd)
    if not edit:
        raise AppError("could not find the filename field in the Open dialog")
    user32.SendMessageW(edit, 0x000C, 0, ctypes.c_wchar_p(str(target)))   # WM_SETTEXT
    time.sleep(0.5)
    tap(VK_RETURN)
    time.sleep(3.5)

    deadline = time.time() + timeout
    title = ""
    while time.time() < deadline:
        try:
            title = main_window(pid).title
        except AppError:
            title = ""
        if str(target).lower() in title.lower() or target.name.lower() in title.lower():
            break
        time.sleep(0.5)
    dialogs = find_dialogs(pid)
    return {
        "requested": str(target),
        "window_title": title,
        "title_shows_document": target.name.lower() in title.lower() or str(target).lower() in title.lower(),
        "dialogs": [d.title for d in dialogs],
        "ok": not dialogs,
    }


def launch_and_open(exe: str | Path, document: str | Path, settle: float = 5.0) -> dict:
    proc = launch(exe)
    wait_for_window(proc.pid, timeout=60)
    time.sleep(settle)
    closed = dismiss_startup_dialogs(proc.pid)
    result = open_document(proc.pid, document)
    result.update({"pid": proc.pid, "startup_dialogs_closed": closed})
    return result
