"""Logic compiler tests: parsing, synthesis, sizing, layout and simulation."""

from __future__ import annotations

import shutil

import pytest

from microwind.logic import LogicError, check_circuit, parse_expression, synthesize
from microwind.spice import measure_delays, run, truth_table_switch


def test_parse_precedence_and_negation():
    name, ast = parse_expression("F=~(A&B|C)")
    assert name == "F"
    assert str(ast) == "~((A&B)|C)"
    assert [v for v in ("A", "B", "C") if v in str(ast)] == ["A", "B", "C"]


@pytest.mark.parametrize("bad", ["F", "1x=A", "F=", "F=(A&B", "F=A$B"])
def test_bad_expressions_rejected(bad):
    with pytest.raises(LogicError):
        parse_expression(bad)


def test_monotone_complement_makes_one_complex_stage():
    circuit = synthesize("F=~((A&B&C)|D)")
    assert len(circuit.stages) == 1
    assert circuit.stages[0]["stage"] == "complex"
    assert len(circuit.devices) == 8


def test_non_monotone_complement_is_decomposed_into_stages():
    circuit = synthesize("F=((A|B|C)&D)")
    gates = [s.get("gate") for s in circuit.stages]
    assert gates == ["NOR", "INV", "NAND", "INV"]
    assert len(circuit.devices) == 3 + 1 + 2 + 1 + 3 + 1 + 2 + 1


def test_series_devices_are_sized_to_the_unit_inverter():
    # PDN = (A.B.C) + D: the three series nMOS are 3x4, D is 1x4;
    # PUN = (A+B+C).D: every pMOS sits in a two-device path, 2x8.
    circuit = synthesize("F=~((A&B&C)|D)")
    widths = {(d.gate, d.kind): d.width for d in circuit.devices}
    assert widths[("A", "n")] == widths[("B", "n")] == widths[("C", "n")] == 12
    assert widths[("D", "n")] == 4
    assert all(widths[(g, "p")] == 16 for g in "ABCD")


def test_layout_is_rule_clean_and_structurally_closed():
    circuit = synthesize("F=~((A&B&C)|D)")
    report = check_circuit(circuit)
    assert report["structural"]["ok"] is True
    assert report["min_width_violations"] == []
    assert report["min_spacing_violations"] == []
    assert report["overlaps"] == []


def test_body_ties_present_for_both_device_types():
    circuit = synthesize("F=~((A&B&C)|D)")
    layers = {r.layer for r in circuit.msk.rects}
    assert {"DN", "DP", "NW"} <= layers
    assert "VSS" in circuit.nets and "VDD" in circuit.nets
    # one extra tie terminal on each supply net besides the transistor terminals
    assert len(circuit.nets["VSS"]["terminals"]) >= 2
    assert len(circuit.nets["VDD"]["terminals"]) >= 2


def test_layout_round_trips_through_the_parser(tmp_path):
    from microwind.msk import MskFile

    circuit = synthesize("F=~(A^B)")
    path = tmp_path / "xor.MSK"
    circuit.msk.save(path, make_backup=False)
    again = MskFile.load(path)
    assert len(again.rects) == len(circuit.msk.rects)
    assert again.dumps() == path.read_bytes().decode("latin-1")


def test_switch_level_truth_tables_match_the_functions():
    for expr, check in {
        "F=~((A&B&C)|D)": lambda a, b, c, d: int(not (a and b and c) and not d)
                           if not (a and b and c) and not d else 0,
        "Y=~(A|B)": lambda a, b: int(not (a or b)),
    }.items():
        circuit = synthesize(expr)
        for row in truth_table_switch(circuit):
            values = row["inputs"]
            if expr.startswith("F="):
                expected = 1 if not (values["A"] and values["B"] and values["C"]) and not values["D"] else 0
            else:
                expected = 1 if not (values["A"] or values["B"]) else 0
            assert row["output"] == expected, (expr, values, row["output"], expected)


@pytest.fixture(scope="module")
def spice_env(dsch_root):
    if not shutil.which("ngspice"):
        pytest.skip("ngspice not installed")
    libs = list((dsch_root / "rules").glob("spice.lib"))
    if not libs:
        pytest.skip("spice.lib not found")
    return libs[0]


def test_ngspice_truth_table_matches_switch_level(spice_env, tmp_path):
    circuit = synthesize("F=~((A&B&C)|D)")
    result = run(circuit, tmp_path, spice_env)
    sim = {tuple(sorted(r["inputs"].items())): r["output"] for r in result["truth_table"]}
    assert len(sim) == 16
    for row in truth_table_switch(circuit):
        assert sim[tuple(sorted(row["inputs"].items()))] == row["output"]


def test_measure_delays_returns_positive_per_edge(spice_env, tmp_path):
    circuit = synthesize("F=~((A&B&C)|D)")
    delays = measure_delays(circuit, tmp_path / "steps", spice_env)
    assert set(delays) == {"A", "B", "C", "D"}
    for name, rec in delays.items():
        for key in ("tpLH_ps", "tpHL_ps"):
            if rec.get(key) is not None:
                assert 0 < rec[key] < 5000


def test_no_floating_nwell_island():
    """Every nwell island needs a well tap (contact on NW), or Microwind warns."""
    circuit = synthesize("F=((A|B|C)&D)")
    nw = [r for r in circuit.msk.rects if r.layer == "NW"]
    taps = [r for r in circuit.msk.rects if r.layer == "CO"]
    assert nw

    parent = list(range(len(nw)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(nw):
        for j, b in enumerate(nw[i + 1:], start=i + 1):
            if a.overlaps(b) or a.touches(b):
                parent[find(j)] = find(i)

    islands: dict[int, list] = {}
    for i, rect in enumerate(nw):
        islands.setdefault(find(i), []).append(rect)
    for rects in islands.values():
        assert any(t.overlaps(n) or t.touches(n) for t in taps for n in rects), \
            f"nwell island at {(rects[0].x, rects[0].y)} has no well tap"
