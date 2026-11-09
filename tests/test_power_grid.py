"""Power-grid engine tests: geometry, collisions, preservation, reload."""

from __future__ import annotations

from pathlib import Path

import pytest

from microwind import checks
from microwind.msk import MskFile
from microwind.power_grid import (
    PowerGridError,
    PowerGridSpec,
    analyze_power_grid,
    generate_power_grid,
    generate_power_rails,
)


def test_grid_on_empty_layout(tmp_path: Path) -> None:
    msk = MskFile.new(400, 400)
    spec = PowerGridSpec(layers=["ME", "M2"], width=200, height=200, columns=4, rows=3)
    report = generate_power_grid(msk, spec)
    assert report["rails_planned"] == 7
    assert report["vias_planned"] > 0, "same-supply crossings must get vias"
    assert report["collision_count"] == 0
    assert report["preserved_existing"] is True
    assert report["labels"] == {"VDD": 1, "VSS": 1}

    layers = {r.layer for r in msk.rects}
    assert {"ME", "M2", "VI"} <= layers

    out = msk.save(tmp_path / "grid.MSK")
    reloaded = MskFile.load(out)
    assert len(reloaded.rects) == len(msk.rects)
    assert reloaded.validate() == []
    assert {l.code for l in reloaded.labels} == {"$1", "$0"}


def test_rail_widths_and_margins_applied() -> None:
    msk = MskFile.new(400, 400)
    spec = PowerGridSpec(
        layers=["ME", "M2"],
        width=200,
        height=200,
        columns=2,
        rows=2,
        wire_width=4,
        rail_widths={"M2": 9},
        margin=10,
        offset=(50, 60),
    )
    report = generate_power_grid(msk, spec)
    rails = report["rail_rects"]
    me = [r for r in rails if r["layer"] == "ME"]
    m2 = [r for r in rails if r["layer"] == "M2"]
    assert all(r["bbox"][2] - r["bbox"][0] == 4 for r in me), "ME rails use wire_width"
    assert all(r["bbox"][3] - r["bbox"][1] == 9 for r in m2), "M2 rows use their per-layer width"
    assert min(r["bbox"][0] for r in me) >= 50 + 10


def test_single_layer_rails_have_no_vias() -> None:
    msk = MskFile.new(300, 300)
    report = generate_power_rails(msk, "ME", count=3, pitch=40, length=150, width=6)
    assert report["vias_planned"] == 0
    assert len([r for r in msk.rects if r.layer == "ME"]) == 3
    assert all(r.h == 150 for r in msk.rects), "vertical rails span the length"


def test_collision_detected_and_reported() -> None:
    msk = MskFile.new(300, 300)
    msk.add_rect(0, 0, 20, 200, "ME")          # sits exactly where the first column goes
    spec = PowerGridSpec(layers=["ME", "M2"], width=100, height=100, columns=2, rows=2, auto_place=False)
    report = generate_power_grid(msk, PowerGridSpec(**{**spec.__dict__, "check_only": True}))
    assert report["collision_count"] > 0
    assert report["changed"] is False
    assert len(msk.rects) == 1, "check_only must not modify the layout"

    with pytest.raises(PowerGridError):
        generate_power_grid(msk, spec)


def test_auto_place_moves_grid_right_of_existing() -> None:
    msk = MskFile.new(600, 400)
    existing = msk.add_rect(0, 0, 100, 100, "ME")
    spec = PowerGridSpec(layers=["ME", "M2"], width=100, height=100, columns=2, rows=2)
    report = generate_power_grid(msk, spec)
    assert report["collision_count"] == 0, "auto_place must remove collisions"
    rails = [r for r in msk.rects if r.layer == "ME" and r is not existing]
    assert rails and min(r.x for r in rails) >= existing.x2


def test_existing_geometry_preserved_on_real_fixture(msk_files: list[Path], tmp_path: Path) -> None:
    # smallest real layout keeps the test fast while still proving behaviour on real data
    target = min(msk_files, key=lambda p: p.stat().st_size)
    msk = MskFile.load(target)
    before = list(msk.records)
    before_raw = [r.raw for r in before if r.kind != "BB"]

    spec = PowerGridSpec(layers=["ME", "M2"], width=120, height=120, columns=3, rows=3, auto_place=True)
    report = generate_power_grid(msk, spec)

    after = list(msk.records)
    for rec in before:
        if rec.kind == "BB":
            continue
        assert any(rec is a for a in after), f"record lost: {rec.body[:40]}"
    emitted = msk.dumps()
    for raw in before_raw:
        assert raw.rstrip("\r\n") in emitted, f"original line not re-emitted: {raw[:40]}"
    assert report["preserved_existing"] is True

    out = msk.save(tmp_path / f"grid_{target.stem}.MSK")
    reloaded = MskFile.load(out)
    assert reloaded.validate() == []
    assert len(reloaded.rects) == len(msk.rects)


def test_generated_grid_is_connected() -> None:
    msk = MskFile.new(300, 300)
    generate_power_grid(msk, PowerGridSpec(layers=["ME", "M2"], width=150, height=150, columns=3, rows=3))
    power = checks.check_power(msk)
    assert power["ok"], power
    # VDD rails must be one connected structure, and so must VSS
    comps = checks.connectivity(msk)
    vdd_comps = [c for c in comps if any(l["code"] == "$1" for l in c["labels"])]
    vss_comps = [c for c in comps if any(l["code"] == "$0" for l in c["labels"])]
    assert len(vdd_comps) == 1, vdd_comps
    assert len(vss_comps) == 1, vss_comps


def test_analyze_power_grid_sees_the_rails() -> None:
    msk = MskFile.new(300, 300)
    generate_power_grid(msk, PowerGridSpec(layers=["ME", "M2"], width=150, height=150, columns=3, rows=3))
    report = analyze_power_grid(msk)
    assert report["rail_count"] >= 6
    assert report["power_labels"]["VDD"] and report["power_labels"]["VSS"]
    assert report["power_components"]


def test_spec_validation() -> None:
    with pytest.raises(PowerGridError):
        generate_power_grid(MskFile.new(10, 10), PowerGridSpec(layers=["ZZ"]))
    with pytest.raises(PowerGridError):
        generate_power_grid(MskFile.new(10, 10), PowerGridSpec(voltage_pattern=["FOO"]))
    with pytest.raises(PowerGridError):
        generate_power_grid(MskFile.new(10, 10), PowerGridSpec(via_size=4, via_pad=4))
