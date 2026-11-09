"""Round-trip and schematic-query proof over the DSCH 3.5 fixtures."""

from __future__ import annotations

from pathlib import Path

from microwind.dsch import DschFile


def test_roundtrip_sch(sch_files: list[Path]) -> None:
    failures: list[str] = []
    for path in sch_files:
        original = path.read_bytes().decode("latin-1")
        emitted = DschFile.parse(original, path).dumps()
        if original != emitted:
            first = next(
                (i for i, (a, b) in enumerate(zip(original.splitlines(), emitted.splitlines())) if a != b),
                None,
            )
            failures.append(f"{path.name}: differs at line {first}")
    assert not failures, "round-trip mismatches:\n" + "\n".join(failures[:10])


def test_roundtrip_sym(sym_files: list[Path]) -> None:
    failures: list[str] = []
    for path in sym_files:
        original = path.read_bytes().decode("latin-1")
        if not original:
            continue
        emitted = DschFile.parse(original, path).dumps()
        if original != emitted:
            failures.append(path.name)
    assert not failures, f"sym round-trip mismatches: {failures[:10]}"


def test_sch_structure(sch_files: list[Path]) -> None:
    assert len(sch_files) >= 52, f"expected 52+ .sch fixtures, found {len(sch_files)}"
    total_symbols = 0
    for path in sch_files:
        d = DschFile.load(path)
        if not d.records:
            continue
        assert d.version.upper().startswith("DSCH"), f"{path.name}: bad header {d.version!r}"
        problems = d.validate()
        assert not problems, f"{path.name}: {problems}"
        total_symbols += len(d.symbols)
    assert total_symbols > 500, f"only {total_symbols} symbol blocks parsed across all schematics"


def test_components_and_pins(sch_files: list[Path]) -> None:
    by_name = {p.name.lower(): p for p in sch_files}
    target = by_name.get("add4.sch")
    assert target is not None, "Add4.sch not found in the DSCH 3.5 examples"
    d = DschFile.load(target)
    comps = d.components()
    assert comps, "no components parsed from Add4.sch"
    assert all(c["pins"] or c["bbox"] for c in comps), "components without pins or geometry"
    labels = {c["label"] for c in comps if c["label"]}
    assert {"halfAdder", "fullAdder"} <= labels, f"expected sub-symbols, got {sorted(labels)[:12]}"
    pin_names = {p["name"] for c in comps for p in c["pins"]}
    assert {"A0", "A1", "A2", "A3"} <= pin_names, f"expected A0..A3 pins, got {sorted(pin_names)[:12]}"


def test_net_extraction(sch_files: list[Path]) -> None:
    by_name = {p.name.lower(): p for p in sch_files}
    targets = [by_name["add4.sch"]]
    other = next((p for p in sch_files if p.stat().st_size > 4000 and p.name.lower() != "add4.sch"), None)
    if other is not None:
        targets.append(other)
    for path in targets:
        d = DschFile.load(path)
        nets = d.nets()
        assert nets, f"no nets extracted from {path.name}"
        pin_count = sum(n["pin_count"] for n in nets)
        total_pins = sum(len(s.pins) for s in d.symbols)
        assert pin_count <= total_pins
        # a schematic with wires must produce at least one multi-pin net
        assert any(n["pin_count"] > 1 for n in nets), f"no multi-pin nets in {path.name}"
