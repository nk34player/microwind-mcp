"""Generate the example layouts shipped in `examples/generated/`.

    python scripts/generate_examples.py [technologies/cmos012.rul]

Everything here is produced by the library, so re-running regenerates the same shapes
(deterministic; only the VERSION timestamp moves).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microwind.cmos import build_cell  # noqa: E402
from microwind.install import find_microwind  # noqa: E402
from microwind.msk import MskFile  # noqa: E402
from microwind.power_grid import PowerGridSpec, generate_power_grid  # noqa: E402
from microwind.rul import Technology  # noqa: E402

OUT = ROOT / "examples" / "generated"


def main() -> int:
    install = find_microwind()
    tech_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if tech_path is None and install and install.rules:
        tech_path = next((p for p in install.rules if p.name == "cmos012.rul"), install.rules[0])
    tech = Technology.load(tech_path) if tech_path and tech_path.is_file() else None
    OUT.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for gate in ("inverter", "nand2", "nor2"):
        cell = build_cell(gate, tech)
        cell.msk.path = OUT / f"{gate}.MSK"
        written.append(cell.msk.save(cell.msk.path, make_backup=False))

    # gates with a power grid attached, proving the two engines compose
    for gate in ("inverter", "nand2"):
        cell = build_cell(gate, tech)
        msk = cell.msk
        spec = PowerGridSpec(
            layers=["ME", "M2"],
            width=120,
            height=100,
            columns=3,
            rows=2,
            offset=(0, 90),
            auto_place=False,
        )
        generate_power_grid(msk, spec)
        msk.path = OUT / f"{gate}_power_grid.MSK"
        written.append(msk.save(msk.path, make_backup=False))

    # a standalone grid on an empty layout
    msk = MskFile.new(240, 180, path="POWER_GRID.MSK")
    generate_power_grid(msk, PowerGridSpec(layers=["ME", "M2"], width=220, height=160, columns=4, rows=3, margin=10))
    msk.path = OUT / "power_grid.MSK"
    written.append(msk.save(msk.path, make_backup=False))

    print(f"technology: {tech_path}")
    for path in written:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
