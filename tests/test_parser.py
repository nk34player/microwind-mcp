"""Round-trip and structural proof over every shipped Microwind 3.5 .MSK fixture."""

from __future__ import annotations

from pathlib import Path

from microwind.msk import MskFile

#: layers the 3.5 examples actually use (measured across all 245 fixtures)
EXPECTED_LAYERS = {
    "NW", "DN", "DP", "PO", "CO", "ME",
    "M2", "M3", "M4", "M5", "M6", "M7", "M8",
    "VI", "V2", "V3", "V4", "V5", "V6", "V7",
    "PA", "P2", "OP",
}

#: layer codes that exist only in the 3.5 example set, not in 3.1
ONLY_35 = {"M7", "M8", "V6", "V7"}


def test_roundtrip_all_fixtures(msk_files: list[Path]) -> None:
    failures: list[str] = []
    for path in msk_files:
        original = path.read_bytes().decode("latin-1")
        emitted = MskFile.parse(original, path).dumps()
        if original != emitted:
            first = next(
                (i for i, (a, b) in enumerate(zip(original.splitlines(), emitted.splitlines())) if a != b),
                None,
            )
            failures.append(f"{path.name}: differs at logical line {first}")
    assert not failures, "round-trip mismatches:\n" + "\n".join(failures[:10])


def test_every_file_parsed(msk_files: list[Path]) -> None:
    assert len(msk_files) >= 245, f"expected 245+ MSK fixtures, found {len(msk_files)}"
    for path in msk_files:
        msk = MskFile.load(path)
        # every file must classify its whole body: REC records are typed, the rest kept raw
        for rec in msk.records:
            if rec.kind == "REC":
                assert rec.__class__.__name__ == "Rect", f"{path.name}: REC not parsed"
        assert msk.records, f"{path.name}: no records"


def test_layers_cover_the_35_extensions(msk_files: list[Path]) -> None:
    seen: dict[str, int] = {}
    for path in msk_files:
        for rect in MskFile.load(path).rects:
            seen[rect.layer] = seen.get(rect.layer, 0) + 1
    missing = EXPECTED_LAYERS - set(seen)
    assert not missing, f"documented layers never parsed: {sorted(missing)}"
    absent = ONLY_35 - set(seen)
    assert not absent, f"3.5-only layers not found in fixtures: {sorted(absent)}"


def test_six_argument_rectangles_preserved(msk_files: list[Path]) -> None:
    seen = 0
    for path in msk_files:
        msk = MskFile.load(path)
        seen += sum(1 for r in msk.rects if r.extra is not None)
    assert seen == 212, f"expected 212 six-argument REC records in the 3.5 set, parsed {seen}"


def test_bbox_contains_geometry(msk_files: list[Path]) -> None:
    checked = 0
    for path in msk_files:
        msk = MskFile.load(path)
        if not msk.rects:
            continue
        checked += 1
        problems = [p for p in msk.validate() if p.startswith("BB ")]
        assert not problems, f"{path.name}: {problems}"
    assert checked >= 245


def test_labels_parsed(msk_files: list[Path]) -> None:
    total = sum(len(MskFile.load(p).labels) for p in msk_files)
    assert total == 3126, f"expected 3126 TITLE labels in the 3.5 set, got {total}"
