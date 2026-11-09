"""Filesystem safety: path confinement, backups, atomic writes.

Mirrors the two hard-won behaviours documented in salitronic/eda-agent (Apache-2.0):
staged write + ``os.replace`` with a retry loop (Windows AV/indexers hold the
target open and ``os.replace`` fails with WinError 5/32), and a read-only mode
switch that refuses every mutating operation.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

READONLY_ENV = "MICROWIND_MCP_READONLY"
BACKUP_SUFFIX = ".bak"


class SafetyError(RuntimeError):
    """Raised when an operation is refused for safety reasons."""


def readonly() -> bool:
    if os.environ.get(READONLY_ENV, "").strip() not in ("", "0", "false", "False"):
        return True
    try:
        from .config import load_config

        return bool(load_config().readonly)
    except Exception:  # noqa: BLE001 - a broken config must not block safety checks
        return False


def ensure_writable() -> None:
    if readonly():
        raise SafetyError(
            f"server is read-only ({READONLY_ENV} is set); refusing to modify files"
        )


def resolve_in_roots(path: str | Path, roots: list[Path]) -> Path:
    """Resolve `path` and require it to live under one of `roots`."""
    p = Path(path).expanduser().resolve()
    for root in roots:
        try:
            p.relative_to(root.resolve())
        except ValueError:
            continue
        return p
    raise SafetyError(
        f"path {p} is outside the allowed project directories "
        f"({', '.join(str(r) for r in roots)}); set MICROWIND_MCP_PROJECTS to widen"
    )


def backup(path: str | Path) -> Path:
    """Copy `path` to ``<name>.bak`` (or ``.bak1`` … ) and return the backup path."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(src)
    dest = src.with_suffix(src.suffix + BACKUP_SUFFIX)
    n = 1
    while dest.exists():
        dest = src.with_suffix(f"{src.suffix}.bak{n}")
        n += 1
    shutil.copy2(src, dest)
    return dest


def atomic_write(path: str | Path, text: str, encoding: str = "latin-1") -> Path:
    """Write `text` to `path` atomically, retrying the Windows rename race."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".mwmcp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        last: Exception | None = None
        for attempt in range(6):
            try:
                os.replace(tmp, target)
                return target
            except PermissionError as exc:  # WinError 5 / 32
                last = exc
                time.sleep(0.05 * (attempt + 1))
        raise SafetyError(f"could not replace {target}: {last}")
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
