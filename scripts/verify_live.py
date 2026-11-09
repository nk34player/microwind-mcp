"""Live verification against the real Microwind 3.5 / DSCH 3.5 executables.

For each document: launch the application, close the `About` splash, load the document
through File->Open (the command line is ignored by 3.5 — measured), confirm the window
title now shows that document, look for modal dialogs, take a screenshot, then terminate
exactly the PID that was started.

Every result is written verbatim into `docs/LIVE_VERIFICATION.md`.  Nothing is asserted
that was not observed.

    python scripts/verify_live.py [--skip-dsch]
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microwind import app  # noqa: E402
from microwind.install import find_dsch, find_microwind  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"
GENERATED = ROOT / "examples" / "generated"
DOC = ROOT / "docs" / "LIVE_VERIFICATION.md"
MW_FILES = ["inverter.MSK", "nand2.MSK", "nor2.MSK", "inverter_power_grid.MSK", "power_grid.MSK"]


def verify(exe: Path, document: Path, shot: Path, product: str) -> dict:
    row = {"app": product, "file": document.name, "title": "", "dialogs": "", "screenshot": "",
           "result": "", "detail": ""}
    proc_pid = None
    try:
        proc = app.launch(exe)
        proc_pid = proc.pid
        app.wait_for_window(proc.pid, timeout=60)
        closed = app.dismiss_startup_dialogs(proc.pid)
        result = app.open_document(proc.pid, document)
        win = app.main_window(proc.pid)
        app.focus(win.hwnd)
        app.screenshot(shot)
        row.update({
            "title": result["window_title"].replace(str(ROOT), "<repo>"),
            "dialogs": "; ".join(result["dialogs"]) or "none",
            "screenshot": str(shot.relative_to(ROOT)),
            "result": "LOADED" if (result["ok"] and result["title_shows_document"]) else "NOT CONFIRMED",
            "detail": "startup dialogs closed: " + (", ".join(closed) or "none"),
        })
    except Exception as exc:                      # noqa: BLE001 - reported, never hidden
        row["result"] = "FAILED"
        row["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        if proc_pid is not None:
            row["detail"] = (row["detail"] + f"; process terminated={app.close(proc_pid)}").strip("; ")
    return row


def run(include_dsch: bool = True) -> int:
    mw, dsch = find_microwind(), find_dsch()
    SHOTS.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    if mw and mw.exe:
        for name in MW_FILES:
            path = GENERATED / name
            if not path.is_file():
                rows.append({"app": "Microwind 3.5", "file": name, "title": "", "dialogs": "",
                             "screenshot": "", "result": "MISSING", "detail": "run scripts/generate_examples.py"})
                continue
            rows.append(verify(mw.exe, path, SHOTS / f"microwind_{path.stem}.png", "Microwind 3.5"))
    else:
        rows.append({"app": "Microwind 3.5", "file": "-", "title": "", "dialogs": "",
                     "screenshot": "", "result": "NOT RUN", "detail": "installation not found"})

    if include_dsch:
        if dsch and dsch.exe:
            base = dsch.examples_dir or Path()
            sources: list[Path] = []
            for cand in ("adder/Add4.sch", "counters/Counter4.sch", "basic/Nand2.sch"):
                p = base / cand
                if p.is_file():
                    sources.append(p)
            if len(sources) < 3:
                for cand in sorted(base.rglob("*.sch"), key=lambda q: q.stat().st_size):
                    if cand not in sources:
                        sources.append(cand)
                    if len(sources) >= 3:
                        break
            if not sources:
                rows.append({"app": "DSCH 3.5", "file": "-", "title": "", "dialogs": "",
                             "screenshot": "", "result": "NOT RUN", "detail": "no .sch example found"})
            for source in sources[:3]:
                copy = GENERATED / f"dsch_{source.stem.lower()}_copy.sch"
                shutil.copy2(source, copy)      # copy; the install stays untouched
                rows.append(verify(dsch.exe, copy, SHOTS / f"dsch35_{source.stem.lower()}.png", "DSCH 3.5"))
        else:
            rows.append({"app": "DSCH 3.5", "file": "-", "title": "", "dialogs": "",
                         "screenshot": "", "result": "NOT RUN", "detail": "installation not found"})

    lines = [
        "# LIVE VERIFICATION — real applications",
        "",
        f"Run: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Method per document: launch the executable → close the `About` splash (`WM_CLOSE`) →",
        "focus the main window → **Alt, F, O** (`SendInput`) → set the filename field",
        "(`WM_SETTEXT`) → Enter → read the window title → look for `#32770` modal dialogs →",
        "capture the screen → terminate only that PID.",
        "",
        "The command line that the 3.1 help documents (`Microwind35.exe mask.MSK rules.rul`)",
        "is **ignored by 3.5**: tested with a full path, a bare name with matching cwd, and a",
        "path plus rule file — the title stayed `Microwind35 - example` in all three cases.",
        "Menu navigation is therefore the only verified load path.",
        "",
        "Window titles are shown verbatim with the repository prefix replaced by `<repo>`.",
        "",
        "| app | document | window title (verbatim) | dialogs | result | screenshot |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['app']} | `{row['file']}` | {row.get('title') or '—'} | {row.get('dialogs') or '—'} "
            f"| **{row['result']}** | {row.get('screenshot') or '—'} |"
        )
    details = [r for r in rows if r.get("detail")]
    if details:
        lines += ["", "## Diagnostics", ""]
        lines += [f"- **{r['app']}** `{r['file']}` — {r['detail']}" for r in details]
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for row in rows:
        print(f"{row['app']:14} {row['file']:26} {row['result']:15} {row.get('title', '')[:60]}")
    print(f"\nwrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run("--skip-dsch" not in sys.argv))
