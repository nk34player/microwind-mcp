"""CMOS generator tests: structure, rule cleanliness, round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from microwind.cmos import NETLISTS, build_cell, check_cell, verify_cell
from microwind.msk import MskFile
from microwind.rul import Technology


@pytest.fixture(scope="module")
def tech(rul_files: list[Path]) -> Technology:
    return Technology.load(next(p for p in rul_files if p.name == "cmos012.rul"))


@pytest.mark.parametrize("gate", sorted(NETLISTS))
def test_structure_is_electrically_sound(gate: str, tech: Technology) -> None:
    cell = build_cell(gate, tech)
    result = verify_cell(cell)
    assert result["ok"], result["shorts_or_opens"]
    # every net must exist exactly once, and no net may share a component
    assert len(result["nets"]) == len({n for d in cell.devices for n in (d.source, d.drain, d.gate)})


@pytest.mark.parametrize("gate", sorted(NETLISTS))
def test_no_width_or_spacing_violations(gate: str, tech: Technology) -> None:
    report = check_cell(build_cell(gate, tech), tech)
    assert report["min_width_violations"] == [], report["min_width_violations"][:3]
    assert report["min_spacing_violations"] == [], report["min_spacing_violations"][:3]
    assert report["ok"]


@pytest.mark.parametrize("gate", sorted(NETLISTS))
def test_roundtrip_and_reload(gate: str, tech: Technology, tmp_path: Path) -> None:
    cell = build_cell(gate, tech)
    path = cell.msk.save(tmp_path / f"{gate}.MSK")
    text = path.read_bytes().decode("latin-1")
    reloaded = MskFile.parse(text, path)
    assert reloaded.dumps() == text, "generated file must round-trip byte-exactly"
    assert reloaded.validate() == []
    assert len(reloaded.rects) == len(cell.msk.rects)


def test_device_composition(tech: Technology) -> None:
    nand = build_cell("nand2", tech)
    kinds = [d.kind for d in nand.devices]
    assert kinds.count("n") == 2 and kinds.count("p") == 2
    assert len([r for r in nand.msk.rects if r.layer == "DN"]) == 2, "one diffusion per NMOS"
    assert len([r for r in nand.msk.rects if r.layer == "DP"]) == 2, "one diffusion per PMOS"
    assert len([r for r in nand.msk.rects if r.layer == "NW"]) == 2, "each PMOS needs a well"
    # series NMOS: the MID net joins n1 drain to n2 source
    mid = [d for d in nand.devices if d.source == "MID" or d.drain == "MID"]
    assert {d.name for d in mid} == {"n1", "n2"}
    assert len(nand.nets["MID"]["terminals"]) == 2

    nor = build_cell("nor2", tech)
    mid = [d for d in nor.devices if d.source == "MID" or d.drain == "MID"]
    assert {d.name for d in mid} == {"p1", "p2"}, "NOR2 needs series PMOS"
    assert {d.name for d in nor.devices if d.kind == "n" and d.drain == "Y" and d.source == "VSS"} == {"n1", "n2"}


def test_power_labels_present(tech: Technology) -> None:
    inv = build_cell("inverter", tech)
    codes = {l.code for l in inv.msk.labels}
    assert {"$1", "$0"} <= codes
    names = {l.text for l in inv.msk.labels}
    assert {"VDD", "VSS", "A"} <= names


def test_unknown_gate_rejected() -> None:
    from microwind.cmos import CmosError

    with pytest.raises(CmosError):
        build_cell("xor3")
