"""Locate the Microwind / DSCH installation and describe it.

Detection order: explicit config value → environment variable. There are no
machine-specific built-in install paths; callers pass or export a product folder.
Nothing here writes to the install; every path is read-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MW_SUBDIR = "microwind35 full"
DSCH_SUBDIR = "dsch35 full"


@dataclass
class Install:
    product: str
    root: Path
    exe: Path | None
    extra_exes: list[Path] = field(default_factory=list)
    rules: list[Path] = field(default_factory=list)
    examples_dir: Path | None = None
    example_count: int = 0
    version: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "root": str(self.root),
            "exe": str(self.exe) if self.exe else None,
            "extra_exes": [str(p) for p in self.extra_exes],
            "rule_files": [p.name for p in self.rules],
            "examples_dir": str(self.examples_dir) if self.examples_dir else None,
            "example_count": self.example_count,
            "version": self.version,
            "notes": self.notes,
            "installed": self.exe is not None,
        }


def _first_existing(*cands: str | Path | None) -> Path | None:
    for cand in cands:
        if cand and Path(cand).is_dir():
            return Path(cand)
    return None


def _first_product_root(*cands: str | Path | None, subdir: str) -> Path | None:
    """Accept either a product folder or its parent, and require ``system/``."""
    for cand in cands:
        if not cand:
            continue
        base = Path(cand).expanduser()
        for root in (base, base / subdir):
            if (root / "system").is_dir():
                return root
    return None


def find_microwind(home: str | Path | None = None) -> Install | None:
    root = _first_product_root(
        home,
        os.environ.get("MICROWIND_HOME"),
        subdir=MW_SUBDIR,
    )
    if root is None:
        return None
    notes: list[str] = []
    exe = root / "system" / "Microwind35.exe"
    if not exe.is_file():
        # tolerate other version names, but say so
        candidates = sorted((root / "system").glob("Microwind*.exe")) if (root / "system").is_dir() else []
        exe = candidates[0] if candidates else None
        if exe is not None:
            notes.append(f"expected Microwind35.exe, using {exe.name}")
    extra = [p for p in (root / "system").glob("Silicon.exe")] if (root / "system").is_dir() else []
    rules = sorted((root / "rules").glob("*.rul")) if (root / "rules").is_dir() else []
    examples = _first_existing(root / "Examples", root / "examples")
    count = len(list(examples.rglob("*.[mM][sS][kK]"))) if examples else 0
    version = ""
    version_file = root.parent / "Microwind_v35.pdf"
    if version_file.is_file():
        notes.append("manual present: Microwind_v35.pdf")
    return Install("microwind", root, exe, extra, rules, examples, count, version, notes)


def find_dsch(home: str | Path | None = None) -> Install | None:
    root = _first_product_root(
        home,
        os.environ.get("DSCH_HOME"),
        subdir=DSCH_SUBDIR,
    )
    if root is None:
        return None
    notes: list[str] = []
    exe = root / "system" / "Dsch35.exe"
    if not exe.is_file():
        candidates = sorted((root / "system").glob("Dsch*.exe")) if (root / "system").is_dir() else []
        exe = candidates[0] if candidates else None
        if exe is not None:
            notes.append(f"expected Dsch35.exe, using {exe.name}")
    tech = sorted((root / "rules").glob("*.tec")) if (root / "rules").is_dir() else []
    examples = _first_existing(root / "examples", root / "Examples")
    count = len(list(examples.rglob("*.sch"))) if examples else 0
    return Install("dsch", root, exe, [], tech, examples, count, "", notes)


def detect(home: str | Path | None = None, dsch_home: str | Path | None = None) -> dict:
    mw = find_microwind(home)
    dsch = find_dsch(dsch_home)
    return {
        "microwind": mw.to_dict() if mw else {"installed": False},
        "dsch": dsch.to_dict() if dsch else {"installed": False},
        "config": {
            "MICROWIND_HOME": str(mw.root) if mw else None,
            "DSCH_HOME": str(dsch.root) if dsch else None,
        },
    }
