"""Geometry, layer table, technology reader and independent-check tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from microwind import checks
from microwind.geometry import (
    contains,
    expand,
    gap,
    merge_boxes,
    overlap_area,
    union_find_components,
)
from microwind.layers import (
    KNOWN_LAYERS,
    METALS,
    VIAS,
    LayerTable,
    is_metal,
    metal_index,
    via_between,
)
from microwind.msk import MskFile, Rect
from microwind.rul import Technology


def rect(x, y, w, h, layer="ME"):
    return Rect.make(x, y, w, h, layer)


# -- geometry ---------------------------------------------------------------

def test_gap_and_overlap() -> None:
    a, b = rect(0, 0, 10, 10), rect(20, 0, 10, 10)
    assert gap(a, b) == 10
    assert overlap_area(a, b) == 0
    assert not a.touches(b)
    c = rect(10, 0, 10, 10)
    assert a.touches(c) and not a.overlaps(c)  # shared edge: touching, no area
    d = rect(5, 5, 10, 10)
    assert overlap_area(a, d) == 25
    assert a.overlaps(d)


def test_merge_boxes_joins_touching() -> None:
    boxes = [(0, 0, 10, 10), (10, 0, 20, 10), (40, 0, 50, 10)]
    assert merge_boxes(boxes) == [(0, 0, 20, 10), (40, 0, 50, 10)]


def test_point_half_open() -> None:
    assert contains((0, 0, 10, 10), 0, 0)
    assert contains((0, 0, 10, 10), 9, 9)
    assert not contains((0, 0, 10, 10), 10, 5)


def test_expand() -> None:
    assert expand((10, 10, 20, 20), 2) == (8, 8, 22, 22)


def test_components_group_by_layer() -> None:
    comps = union_find_components([rect(0, 0, 10, 10), rect(10, 0, 10, 10), rect(0, 0, 10, 10, "M2")])
    assert {c.layer for c in comps} == {"ME", "M2"}
    assert len([c for c in comps if c.layer == "ME"]) == 1


# -- layers -----------------------------------------------------------------

def test_layer_table_is_data_driven() -> None:
    assert set(METALS) == {"ME", "M2", "M3", "M4", "M5", "M6", "M7", "M8"}
    assert via_between("M7", "M8") == "V7"
    assert via_between("M8", "M7") == "V7"
    assert via_between("ME", "M3") is None
    assert metal_index("ME") == 1 and metal_index("M8") == 8
    assert is_metal("ME") and not is_metal("VI")
    assert "OP" in KNOWN_LAYERS


def test_layer_table_accepts_unknown_cif_entries() -> None:
    table = LayerTable({"weird": (99, 0.0)})
    assert not table.is_known("ZZ")
    assert table.unknown(["ME", "ZZ", "M7"]) == ["ZZ"]


# -- technology -------------------------------------------------------------

def test_rule_file_parsing(rul_files: list[Path]) -> None:
    assert len(rul_files) >= 16, f"expected 16 .rul files, found {len(rul_files)}"
    for path in rul_files:
        tech = Technology.load(path)
        assert tech.version, f"{path.name}: no MICROWIND version line"
        assert tech.name, f"{path.name}: no NAME line"
        assert tech.lam > 0, f"{path.name}: lambda not parsed"
        assert tech.value("vdd") is not None, f"{path.name}: vdd not parsed"
        assert tech.cif, f"{path.name}: no cif mapping"
        assert tech.metal_layers >= 1


def test_rule_values_are_physical(rul_files: list[Path]) -> None:
    tech = Technology.load(next(p for p in rul_files if p.name == "cmos012.rul"))
    assert tech.lam == pytest.approx(0.06)
    assert tech.metal_layers == 6
    assert tech.value("r302") == 2          # gate length in lambda
    assert tech.gate_length() == pytest.approx(0.12)
    assert tech.cif["metal"][0] == 23


# -- independent checks -----------------------------------------------------

def test_width_violation_detected(rul_files: list[Path]) -> None:
    tech = Technology.load(next(p for p in rul_files if p.name == "cmos012.rul"))
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 1, 20, "ME")         # r501 = 3 lambda
    findings = checks.check_width(msk, tech)
    assert findings and findings[0]["rule"] == "min_width"
    msk2 = MskFile.new(100, 100)
    msk2.add_rect(0, 0, 20, 20, "ME")
    assert checks.check_width(msk2, tech) == []


def test_spacing_violation_detected(rul_files: list[Path]) -> None:
    tech = Technology.load(next(p for p in rul_files if p.name == "cmos012.rul"))
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 20, 20, "ME")
    msk.add_rect(21, 0, 20, 20, "ME")       # 1 lambda gap, r502 = 4
    findings = checks.check_spacing(msk, tech)
    assert findings and findings[0]["gap"] == 1
    msk2 = MskFile.new(100, 100)
    msk2.add_rect(0, 0, 20, 20, "ME")
    msk2.add_rect(24, 0, 20, 20, "ME")      # exactly the rule: no violation
    assert checks.check_spacing(msk2, tech) == []


def test_duplicate_pads_are_not_overlaps() -> None:
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 4, 4, "ME")
    msk.add_rect(0, 0, 4, 4, "ME")
    assert checks.check_overlaps(msk) == []
    msk.add_rect(2, 2, 4, 4, "ME")
    assert len(checks.check_overlaps(msk)) == 2


def test_connectivity_through_via() -> None:
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 20, 20, "ME")
    msk.add_rect(8, 8, 4, 4, "M2")
    msk.add_rect(9, 9, 2, 2, "VI")
    comps = checks.connectivity(msk)
    assert len(comps) == 1, comps
    assert comps[0]["layers"] == ["M2", "ME", "VI"]
    # remove the via: two separate components
    msk2 = MskFile.new(100, 100)
    msk2.add_rect(0, 0, 20, 20, "ME")
    msk2.add_rect(8, 8, 4, 4, "M2")
    assert len(checks.connectivity(msk2)) == 2


def test_power_labels_attached_and_short_detected() -> None:
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 20, 20, "ME")
    msk.add_rect(40, 0, 20, 20, "ME")
    msk.add_label(5, 5, "VDD", "$1")
    msk.add_label(45, 5, "VSS", "$0")
    report = checks.check_power(msk)
    assert report["ok"], report
    assert report["label_count"] == {"VDD": 1, "VSS": 1}
    # now short them by connecting the two shapes
    msk.add_rect(20, 0, 20, 20, "ME")
    assert not checks.check_power(msk)["ok"]


def test_unattached_label_reported() -> None:
    msk = MskFile.new(100, 100)
    msk.add_rect(0, 0, 10, 10, "ME")
    msk.add_label(50, 50, "VDD", "$1")
    report = checks.check_power(msk)
    assert not report["ok"]
    assert report["unattached_labels"][0]["text"] == "VDD"


def test_run_all_labels_its_engine() -> None:
    msk = MskFile.new(20, 20)
    msk.add_rect(0, 0, 20, 20, "ME")
    report = checks.run_all(msk)
    assert "not Microwind native DRC" in report["engine"]
    assert report["native_drc_run"] is False
