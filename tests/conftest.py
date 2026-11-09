"""Shared test fixtures: locate the real Microwind 3.5 / DSCH 3.5 installation.

Vendor files are read-only ground truth and are never copied into this repo, so the
fixture-driven tests skip (rather than fail or fabricate) when the install is absent.

Resolution order:
  * ``MICROWIND_HOME``  -> Microwind root (holds ``system/``, ``Examples/``, ``rules/``)
  * ``DSCH_HOME``       -> DSCH root (holds ``system/``, ``examples/``)
  * no implicit machine-specific defaults: fixture tests skip when neither is set
"""

from __future__ import annotations

from pathlib import Path

import pytest

from microwind.install import find_dsch, find_microwind

MW_SUBDIR = "microwind35 full"
DSCH_SUBDIR = "dsch35 full"


def microwind_home() -> Path | None:
    found = find_microwind()
    return found.root if found else None


def dsch_home() -> Path | None:
    found = find_dsch()
    return found.root if found else None


def _collect(root: Path, *patterns: str, subdirs: tuple[str, ...] = ("Examples", "examples")) -> list[Path]:
    """Recursively collect files by case-insensitive extension, deduped by real path."""
    seen: dict[Path, Path] = {}
    for sub in subdirs:
        base = root / sub
        if not base.is_dir():
            continue
        for pattern in patterns:
            for path in base.rglob(pattern):
                if path.is_file():
                    seen.setdefault(path.resolve(), path)
    return sorted(seen.values(), key=lambda p: (p.name.lower(), str(p).lower()))


@pytest.fixture(scope="session")
def mw_home() -> Path:
    home = microwind_home()
    if home is None:
        pytest.skip("Microwind installation not found; set MICROWIND_HOME")
    return home


@pytest.fixture(scope="session")
def dsch_root() -> Path:
    home = dsch_home()
    if home is None:
        pytest.skip("DSCH installation not found; set DSCH_HOME")
    return home


@pytest.fixture(scope="session")
def msk_files(mw_home: Path) -> list[Path]:
    files = _collect(mw_home, "*.MSK", "*.msk")
    if not files:
        pytest.skip("no .MSK fixtures found")
    return files


@pytest.fixture(scope="session")
def sch_files(dsch_root: Path) -> list[Path]:
    files = _collect(dsch_root, "*.sch")
    if not files:
        pytest.skip("no .sch fixtures found")
    return files


@pytest.fixture(scope="session")
def sym_files(dsch_root: Path) -> list[Path]:
    files = _collect(dsch_root, "*.sym")
    if not files:
        pytest.skip("no .sym fixtures found")
    return files


@pytest.fixture(scope="session")
def rul_files(mw_home: Path) -> list[Path]:
    return sorted(p for p in (mw_home / "rules").glob("*.rul") if p.is_file())
