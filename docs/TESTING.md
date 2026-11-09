# TESTING

All tests run against the real Microwind 3.5 / DSCH 3.5 fixtures. No test fabricates a
result, and the fixture-driven ones **skip** (never pass silently) when the install is
absent.

```powershell
python -m pytest -q                     # 68 tests
python scripts/roundtrip_report.py      # byte-level proof over every fixture
python scripts/mcp_smoke.py             # real STDIO client, 32 tools, 15 calls
python scripts/verify_live.py           # opens documents in the real apps, screenshots
```

## What each file proves

| File | Tests | Proves |
|---|---|---|
| `tests/test_parser.py` | 6 | 245/245 `.MSK` round-trip byte-identical; 23 layer codes parsed incl. `M7/M8/V6/V7`; 212 six-arg `REC` preserved; `BB` contains geometry for 245 files; 3,126 labels parsed |
| `tests/test_dsch_parser.py` | 5 | 53/53 `.sch` and 96/96 `.sym` round-trip; 919 symbol blocks; `Add4.sch` components/pins (`A0..A3`); multi-pin nets on two schematics; `null` duplicate pins accepted |
| `tests/test_geometry.py` | 16 | rectangle maths, merging, half-open point test; layer/via table incl. `M7↔V6/V7`; all 16 `.rul` parsed (lambda, `cif`, vdd); min-width and min-spacing violations detected **and** the exact-rule case passes; duplicate pads excused; via connectivity; VDD/VSS short detection; engine labelled non-native |
| `tests/test_power_grid.py` | 9 | 7 rails + vias on empty layout; per-layer widths/margins/offset; single-layer rails; collision detected with `check_only` non-mutating and commit raising; auto-placement right of existing geometry; **real fixture preservation** (every original record kept and re-emitted); one VDD component and one VSS component, no short; reload through the parser |
| `tests/test_cmos.py` | 12 | structural net verification (each net one component, no shorts) for all three gates; zero width/spacing violations against `cmos012.rul`; byte-exact round-trip of generated files; series NMOS in NAND2, series PMOS in NOR2; power labels; unknown gate rejected |
| `tests/test_logic.py` | 16 | one-line parser and precedence, bad input rejected, complex-gate path, NAND/NOR/INV decomposition, unit-inverter widths (12/2 and 4/2 nMOS, 16/2 pMOS), rule-clean layout, body ties, `.MSK` round-trip, switch-level truth tables, ngspice truth-table equality and positive tpLH/tpHL |
| `tests/test_server.py` | 1 | real `initialize` + `tools/list` over STDIO; ≥20 tools; every tool has a description and input schema; every stdout line parses as JSON-RPC |
| `tests/test_safety.py` | 3 | screenshot writes are confined to project roots, refused by env read-only mode, and refused by config read-only mode |

## Round-trip report (expected output)

```
Microwind MSK  files= 245 byte-identical= 245 bytes=  ... PASS
DSCH SCH       files=  53 byte-identical=  53 bytes=  ... PASS
DSCH SYM       files=  96 byte-identical=  96 bytes=  ... PASS
```

The report re-parses and re-emits each file and compares bytes, so any loss — reordered
records, normalised whitespace, dropped unknown declarations — fails the run.

## Live verification

`scripts/verify_live.py` writes `docs/LIVE_VERIFICATION.md` and PNGs in
`docs/screenshots/`. Result of the recorded run: all 5 generated layouts **LOADED** in
`Microwind35.exe` and 3 copied schematics (`Add4`, `adder`, `and`) **LOADED** in
`Dsch35.exe`; for each document
the window title showed the full path and no modal dialog appeared.

Method (also documented in that file): launch → `WM_CLOSE` the `About` splash → focus →
`SendInput` Alt, F, O → `WM_SETTEXT` the filename field → Enter → read title → look for
`#32770` dialogs → screenshot → terminate that PID.

## Not covered by automated tests

* Microwind's own SPICE / native DRC — not driven (no automation interface); the
  compiler's simulation uses ngspice with the vendor model cards.
* DSCH schematic *creation* — not implemented.
* Behaviour on Microwind versions other than 3.5 — untested; 3.1 is no longer installed.
* Interaction with a locked/remote desktop; screenshots then fail by design.

## Reproducing from scratch

```powershell
python -m pip install .[dev]
python -m pytest -q
python scripts/analyze_fixtures.py    # every count in FILE_FORMATS.md; uses MICROWIND_HOME/DSCH_HOME
python scripts/roundtrip_report.py
python scripts/generate_examples.py
python scripts/verify_live.py
python scripts/mcp_smoke.py
```
