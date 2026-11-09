"""Print the three round-trip summaries quoted in the verification contract.

    python scripts/roundtrip_report.py [MICROWIND_HOME]

With no argument the server's own installation detection is used.

Read-only. Every fixture shipped with Microwind 3.5 / DSCH 3.5 is parsed and re-emitted;
this prints how many files match byte-for-byte and, for any mismatch, where.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microwind.dsch import DschFile  # noqa: E402
from microwind.install import find_dsch, find_microwind  # noqa: E402
from microwind.msk import MskFile  # noqa: E402


def collect(base: Path, pattern: str) -> list[Path]:
    seen: dict[Path, Path] = {}
    for path in base.rglob(pattern):
        if path.is_file():
            seen.setdefault(path.resolve(), path)
    return sorted(seen.values(), key=lambda p: str(p).lower())


def run(files: list[Path], loader, label: str) -> int:
    total_bytes = 0
    ok = 0
    failures = []
    for path in files:
        original = path.read_bytes().decode("latin-1")
        total_bytes += len(original)
        emitted = loader(original, path).dumps()
        if emitted == original:
            ok += 1
        else:
            first = next(
                (i for i, (a, b) in enumerate(zip(original.splitlines(), emitted.splitlines())) if a != b),
                None,
            )
            failures.append(f"{path.name} (line {first})")
    status = "PASS" if ok == len(files) else "FAIL"
    print(f"{label:14} files={len(files):4} byte-identical={ok:4} bytes={total_bytes:9} {status}")
    for failure in failures[:10]:
        print(f"    mismatch: {failure}")
    return 0 if ok == len(files) else 1


def main() -> int:
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    mw_install = find_microwind(arg)
    dsch_install = find_dsch(arg)
    if mw_install and not dsch_install:
        dsch_install = find_dsch(mw_install.root.parent)
    if dsch_install and not mw_install:
        mw_install = find_microwind(dsch_install.root.parent)
    if mw_install is None or dsch_install is None:
        print("Microwind or DSCH installation not found; set MICROWIND_HOME and DSCH_HOME", file=sys.stderr)
        return 2
    msk = collect(mw_install.root / "Examples", "*.msk")
    sch = collect(dsch_install.root, "*.sch")
    sym = collect(dsch_install.root, "*.sym")
    rc = 0
    rc |= run(msk, MskFile.parse, "Microwind MSK")
    rc |= run(sch, DschFile.parse, "DSCH SCH")
    rc |= run(sym, DschFile.parse, "DSCH SYM")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
