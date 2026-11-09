"""Print the fixture statistics quoted in docs/FILE_FORMATS.md.

Read-only. Regenerates every count that document claims, so a claim can be
re-checked after an install upgrade instead of silently rotting::

    python scripts/analyze_fixtures.py [MICROWIND_HOME]

With no argument the server's own installation detection is used.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microwind.install import find_dsch, find_microwind  # noqa: E402


def collect(base: Path, pattern: str) -> list[Path]:
    seen: dict[Path, Path] = {}
    for path in base.rglob(pattern):
        if path.is_file():
            seen.setdefault(path.resolve(), path)
    return sorted(seen.values(), key=lambda p: str(p).lower())


def read(path: Path) -> str:
    return path.read_bytes().decode("latin-1")


def msk_stats(files: list[Path]) -> None:
    keywords: collections.Counter = collections.Counter()
    layers: collections.Counter = collections.Counter()
    six: collections.Counter = collections.Counter()
    dollars: collections.Counter = collections.Counter()
    eols: collections.Counter = collections.Counter()
    header = collections.Counter()
    empty = 0
    for path in files:
        text = read(path)
        if not text:
            empty += 1
            continue
        eols["CRLF" if "\r\n" in text else "LF"] += 1
        lines = text.replace("\r\n", "\n").split("\n")
        header[tuple(re.match(r"^[A-Za-z]+", l).group(0) for l in [x for x in lines if x.strip()][:5])] += 1
        for line in lines:
            s = line.strip()
            if not s:
                continue
            m = re.match(r"^([A-Za-z$][A-Za-z0-9$]*)", s)
            kind = m.group(1) if m else "<numeric>"
            keywords[kind] += 1
            if kind.startswith("$"):
                dollars[kind] += 1
            if kind == "REC":
                parts = s[4:-1].split(",")
                layers[parts[4]] += 1
                if len(parts) == 6:
                    six[(parts[4], parts[5])] += 1
    print(f"MSK files: {len(files)} (empty: {empty})  endings: {dict(eols)}")
    print(f"header skeletons: {header.most_common(3)}")
    print(f"keywords: {keywords.most_common(30)}")
    print(f"dollar codes: {sorted(dollars.items(), key=lambda kv: -kv[1])}")
    print(f"layers: {sorted(layers.items(), key=lambda kv: -kv[1])}")
    print(f"6-arg REC: {six.most_common(12)}  total={sum(six.values())}")


def sch_stats(files: list[Path], label: str) -> None:
    keywords: collections.Counter = collections.Counter()
    versions: collections.Counter = collections.Counter()
    eols: collections.Counter = collections.Counter()
    empty = 0
    for path in files:
        text = read(path)
        if not text:
            empty += 1
            continue
        eols["CRLF" if "\r\n" in text else "LF"] += 1
        first = text.split("\n")[0].strip()
        versions[re.sub(r"\d", "N", first)] += 1
        for line in text.replace("\r\n", "\n").split("\n"):
            s = line.strip()
            if not s:
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9]*)", s)
            keywords[m.group(1) if m else "<numeric>"] += 1
    print(f"{label} files: {len(files)} (empty: {empty})  endings: {dict(eols)}")
    print(f"{label} header versions: {versions.most_common(8)}")
    print(f"{label} keywords: {keywords.most_common(25)}")


def rul_stats(files: list[Path], label: str) -> None:
    for path in files[:1]:
        text = read(path)
        kv = sum(1 for l in text.split("\n") if re.match(r"^\s*[A-Za-z_]\w*\s*=", l))
        cif = sum(1 for l in text.split("\n") if re.match(r"^\s*cif\b", l, re.I))
        print(f"{label} example {path.name}: {len(text.splitlines())} lines, {kv} key=value, {cif} cif lines")
    print(f"{label} count: {len(files)}")


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
    mw, dsch = mw_install.root, dsch_install.root
    msk_stats(collect(mw / "Examples", "*.msk") + [p for p in collect(mw / "Examples", "*.MSK")
                                                   if p not in collect(mw / "Examples", "*.msk")])
    print()
    sch_stats(collect(dsch, "*.sch"), "SCH")
    print()
    sch_stats(collect(dsch, "*.sym"), "SYM")
    print()
    rul_stats(sorted((mw / "rules").glob("*.rul")), "RUL")
    rul_stats(sorted((dsch / "rules").glob("*.tec")), "TEC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
