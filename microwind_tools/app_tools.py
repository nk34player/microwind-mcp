"""Application-control tools: detect, open, screenshot, close.

Only verified mechanisms are used:

* launch is `subprocess.Popen`
* loading a document is File->Open driven through the real menu (the 3.1 command line is
  ignored by 3.5 — measured, see docs/LIVE_VERIFICATION.md)
* screenshots are whole-desktop captures taken with .NET, no Python imaging dependency
* closing terminates exactly the PID this server started, never by image name
"""

from __future__ import annotations

import time
from pathlib import Path

from microwind import app
from microwind.config import load_config
from microwind.install import detect, find_dsch, find_microwind
from microwind.safety import ensure_writable, resolve_in_roots

#: processes this server started: pid -> {"product", "exe", "document"}
_MANAGED: dict[int, dict] = {}


def _home(product: str):
    cfg = load_config()
    install = find_microwind(cfg.microwind_home) if product == "microwind" else find_dsch(cfg.dsch_home)
    if install is None or install.exe is None:
        raise app.AppError(f"{product} is not installed or was not detected")
    return install


def detect_installations() -> dict:
    """Detect Microwind and DSCH: executables, versions, rule files and example counts."""
    cfg = load_config()
    return detect(cfg.microwind_home, cfg.dsch_home)


def open_microwind(document: str | None = None, settle: float = 5.0) -> dict:
    """Launch Microwind 3.5 and optionally load a `.MSK` layout through File -> Open."""
    install = _home("microwind")
    proc = app.launch(install.exe)
    app.wait_for_window(proc.pid, timeout=60)
    time.sleep(settle)
    closed = app.dismiss_startup_dialogs(proc.pid)
    result: dict = {"pid": proc.pid, "exe": str(install.exe), "startup_dialogs_closed": closed}
    if document:
        loaded = app.open_document(proc.pid, document)
        result.update({
            "document": str(Path(document)),
            "window_title": loaded["window_title"],
            "loaded": loaded["ok"] and loaded["title_shows_document"],
            "dialogs": loaded["dialogs"],
        })
    else:
        result["window_title"] = app.main_window(proc.pid).title
    _MANAGED[proc.pid] = {"product": "microwind", "exe": str(install.exe), "document": document}
    return result


def open_dsch(document: str | None = None, settle: float = 5.0) -> dict:
    """Launch DSCH 3.5 and optionally load a `.sch` schematic through File -> Open."""
    install = _home("dsch")
    proc = app.launch(install.exe)
    app.wait_for_window(proc.pid, timeout=60)
    time.sleep(settle)
    closed = app.dismiss_startup_dialogs(proc.pid)
    result: dict = {"pid": proc.pid, "exe": str(install.exe), "startup_dialogs_closed": closed}
    if document:
        loaded = app.open_document(proc.pid, document)
        result.update({
            "document": str(Path(document)),
            "window_title": loaded["window_title"],
            "loaded": loaded["ok"] and loaded["title_shows_document"],
            "dialogs": loaded["dialogs"],
        })
    else:
        result["window_title"] = app.main_window(proc.pid).title
    _MANAGED[proc.pid] = {"product": "dsch", "exe": str(install.exe), "document": document}
    return result


def screenshot(output: str) -> dict:
    """Capture the current desktop (including the application window) to a PNG file."""
    ensure_writable()
    target = resolve_in_roots(output, load_config().roots())
    path = app.screenshot(target)
    return {"path": str(path), "bytes": path.stat().st_size}


def window_state(pid: int | None = None) -> dict:
    """List the visible windows of a running app (titles verbatim, plus any dialogs)."""
    if pid is None:
        if not _MANAGED:
            return {"running": [], "note": "no application started by this server is tracked"}
        windows = []
        for managed_pid, meta in _MANAGED.items():
            try:
                win = app.main_window(managed_pid)
            except app.AppError:
                continue
            windows.append({"pid": managed_pid, "product": meta["product"], "title": win.title})
        return {"running": windows}
    wins = [w.to_dict() for w in app.list_windows(pid=pid)]
    return {
        "pid": pid,
        "windows": wins,
        "dialogs": [d.title for d in app.find_dialogs(pid)],
        "managed": _MANAGED.get(pid),
    }


def close_application(pid: int) -> dict:
    """Terminate exactly the given PID (the one this server launched) and report the result."""
    if pid not in _MANAGED:
        return {
            "ok": False,
            "closed": False,
            "error": "pid was not started by this server; refusing to terminate an unknown process",
        }
    closed = app.close(pid)
    meta = _MANAGED.pop(pid, None)
    return {"closed": closed, "pid": pid, "product": (meta or {}).get("product")}
