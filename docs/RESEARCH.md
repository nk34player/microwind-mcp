# RESEARCH — Microwind / DSCH automation prior art

Status: Phase 1 output. Every repo below was cloned and its source read locally under
`.research/` (git-ignored). Nothing here is described from a search-result snippet.

Date of inspection: 2026-11-04.

---

## 0. Local ground truth (the most important source)

Before any third-party repo, the authoritative reference is the installed application itself.

| Path | Contents | Count |
|---|---|---|
| `<microwind-home>\system\Microwind35.exe` | Layout editor + simulator | 1 |
| `…\system\Silicon.exe` | Silicon cross-section viewer | 1 |
| `…\Examples\**\*.MSK` | Real layouts, 25 topic folders | 245 |
| `…\rules\*.rul` | Technology / design-rule files | 16 |
| `…\Html\*.htm` | Application help | 31 files incl. images |
| `<microwind-root>\Microwind_v35.pdf` | Official LITE user manual (21/09/2009) | 4,484 text lines |
| `<dsch-home>\system\Dsch35.exe` | DSCH 3.5 schematic editor + simulator | 1 |
| `dsch35 full\examples\**\*.sch` | Real schematics | 53 |
| `dsch35 full\examples\**\*.sym` | Symbol library | 96 |
| `dsch35 full\rules\*.tec` | DSCH technology files (3.5 only) | 8 |
| `dsch35 full\system\example.v` | DSCH-emitted Verilog sample | 1 |

**Verdict:** every format claim in this project must be traceable to one of these files, and
`python scripts/analyze_fixtures.py` regenerates every number quoted in
`docs/FILE_FORMATS.md`. The 245 `.MSK` layouts and 96 `.sym` files are a far stronger evidence
base than any public repo (the best public one has 5 hand-made samples). The older 3.1
install is no longer on this machine; the 3.5 set supersedes it.

### 0.1 Automation surface, as documented by the vendor itself

Mined from `Html\index.htm`, `Html\file.htm`, `Html\compile.htm`,
`dsch35 full\html\verilog.htm` and `Microwind_v35.pdf`:

- **Command line:** `Microwind35.exe <mask.MSK> <rules.rul>` preloads a layout and a
  technology. The only documented non-GUI entry point.
- **Two layout compilers:** *Compile One Line* (`Out=~(a.b)`, operators `& | ~ ^`, names
  ≤ 8 chars) and *Compile Verilog File* (primitives `dreg, inv/not, and, nand, or, nor,
  xor, nmos`, 2–4 inputs). Both emit native `.MSK`, fix VDD/VSS, and shift the cell right
  when the target area is occupied.
- **CIF bridge:** import/export through the `.RUL` `cif` map with per-layer overetch.
- **DSCH → Microwind path:** DSCH emits restricted Verilog (documented in its own help),
  which Microwind's Verilog compiler turns into a layout.
- **Absent everywhere:** batch mode, DRC deck language, netlist query API, IPC/RPC. The
  file formats are therefore the automation surface; the GUI is only a launch/screenshot
  supplement.

---

## 1. OdaiJ/microwind-power-grid-generator — HIGHEST PRIORITY

- **URL:** https://github.com/OdaiJ/microwind-power-grid-generator
- **License:** none declared (no `LICENSE` file in the repo, no license field anywhere).
  Absence of a license means **no right to redistribute**. Consequence for this project:
  read it for the format research, re-implement independently, do not copy code verbatim.
- **Activity:** single commit `b8aad5a "chore: init"`, 2026-08-30. Not maintained.
- **Size:** 612-line `generate_power_grid.py`, 166-line format note, `config.json`,
  `example_power_grid.MSK`, and a raw `claude_chat_history_with_msk_examples.txt`.

### Files read
- `generate_power_grid.py` (full)
- `microwind_msk_format_notes.md` (full)
- `config.json`, `example_power_grid.MSK` (structure only)

### What it contributes (genuinely valuable)
- A **confidence-labelled** `.MSK` field table: `VERSION` / `FIG #` / `BB` / `SIMU #` /
  `ZOOM` / body / `FFIG`, with 🔬 observed vs ❓ hypothesis marks. The author's discipline
  of never upgrading a hypothesis to fact is the single best idea in the repo and this
  project adopts it.
- `BB` = union bounding box of all shapes, recomputed on save. Corroborated by the 302 fixtures.
- `REC(x, y, w, h, LAYER)` with `(x,y)` = lower-left corner.
- Layer codes `NW, DP, DN, PO, CO, ME, M2, M3, M4`; vias `VI (ME↔M2), V2 (M2↔M3), V3 (M3↔M4)`.
- Minimum via unit = 2λ via centred in a 4λ pad on **both** adjacent metals (1λ enclosure).
- Microwind's via-drop tool stamps a *fresh* pad+via triple even when metal already exists,
  so duplicate overlapping `REC` lines are normal → union same-layer rects for connectivity.
- Net tagging: `TITLE x y  #name` followed by a `$` code line; `$1`=VDD, `$0`=VSS.
  The `(x,y)` point is resolved by point-in-shape hit test.

### What it gets wrong or leaves open (verified against the real fixtures)
- Claims `ME` is the only metal not following the `M<n>` pattern and that `M5/M6` are
  unconfirmed hypotheses. The installed `rules/` set and `examples/*.MSK` settle several of
  these — see `docs/FILE_FORMATS.md` for what the fixtures actually show.
- Treats `REC` as the only primitive ("not observed in any example"). The 302 fixtures
  contain 189,201 `REC` lines plus `RLCR/RLCC/RLCL`, `CAPA`, `RST`, `SELF`, `HELP`,
  `RLCR`, and many more `$` codes — so the primitive set is much larger.
- Never resolves the via-array-vs-single-via question for wide rails.
- No connectivity model, no DRC, no test suite, no parser — it is a one-shot emitter that
  concatenates strings, so it cannot read an existing layout.

### Reuse decision
Re-implement from first principles against the fixtures. Keep these ideas:
parity-based row/column orientation, voltage pattern → via only on matching supply,
confidence labels on every format claim. Credit the repo in README and in
`microwind/power_grid.py` docstrings.

---

## 2. SiliCAD/EDA_MCP

- **URL:** https://github.com/SiliCAD/EDA_MCP
- **License:** MIT (© 2026 SiliCAD / Vaibhav Singh) — reusable with attribution.
- **Activity:** active, last merge 2026-10-25.
- **Files read:** `README.md`, `server.py` (30-line shim), `src/server.py`,
  `src/core/command_guard.py`, `src/core/ssh_client.py`, `src/clients/virtuoso_client.py`,
  directory layout of `src/clients/`.

### Architecture
FastMCP server (Python) that SSHes into a Linux EDA cluster and drives Cadence Virtuoso
(SKILL) and Siemens Eldo. The MCP layer is thin; the real work is remote script execution
over a persistent SSH channel, with a local `daemon.py`.

### Reusable ideas
- `src/core/command_guard.py`: a **denylist + allowed-directory** model for shell strings
  (blocks `mkfs`, `dd of=/dev/*`, `shutdown`, fork bombs; confines cwd to `DEFAULT_ALLOWED_DIRS`).
  Directly informs our `security.py` restricted-project-dirs rule.
- Strict separation between the MCP surface and the vendor-specific client layer — the shape
  we mirror with `tools/` ↔ `microwind/`.
- Skill/context documents shipped beside the server so the agent knows the flow, not just
  the tools.

### Not reusable
Everything vendor-specific (Virtuoso SKILL, Calibre, Eldo, SSH transport) is inapplicable —
Microwind is a local Windows GUI with no RPC interface.

**Verdict:** pattern-only. No code.

---

## 3. NellyW8/MCP4EDA

- **URL:** https://github.com/NellyW8/MCP4EDA
- **License:** ISC (`package.json`), no `LICENSE` file at repo root.
- **Activity:** last commit 2025-07-29; paper arXiv:2507.19570. Effectively dormant.
- **Language:** TypeScript, MCP TypeScript SDK, single `src/index.ts` implementing the tools.
- **Files read:** `README.md`, `src/index.ts` (tool registry + handler bodies), `package.json`.

### Tool surface (6 tools, all read from source)
`synthesize_verilog` (Yosys), `simulate_verilog` (Icarus + auto testbench), `view_waveform`
(GTKWave), `run_openlane` (Docker), `view_gds` (KLayout), `read_openlane_reports`.

### Reusable ideas
- The **flow-shaped tool grouping** (synthesize → simulate → inspect → report) rather than
  raw per-tool wrappers. Our power-grid and CMOS tools are grouped the same way.
- Explicit "run external binary, parse its stdout into structured JSON" adapter shape.

### Not reusable / explicitly not adopted
- OpenLane/GDSII does **not** feed Microwind. `.MSK` is a lambda-unit box list with no GDSII
  import path in 3.1; converting OpenLane output would be a lossy, unvalidated detour.
  Recorded as out-of-scope, not silently dropped.
- Requires Docker + a full OpenLane install for any value — an unjustifiable dependency for
  a layout-file MCP server.

**Verdict:** pattern-only for tool grouping. No code.

---

## 4. salitronic/eda-agent

- **URL:** https://github.com/salitronic/eda-agent
- **License:** Apache-2.0 (© 2026 George Saliba) — reusable with attribution.
- **Activity:** very active, last commit 2026-11-04. Python ≥3.11, `mcp>=1.0,<2`.
- **Files read:** `README.md`, `pyproject.toml`, `src/eda_agent/server.py` (head),
  `src/eda_agent/safety.py` (head), `src/eda_agent/atomicfile.py` (head), directory listing.

### Architecture
`FastMCP` + a **persistent script bridge** into a live desktop app (Altium via DelphiScript;
KiCad / EasyEDA backends selectable at startup, ~600 tools). Backend chosen by env var so
each user only sees their own toolset. Separates `tools/`, `ui/windows.py`, `config`,
`scope`, `saving`, `checkpoint`, `atomicfile`, `safety`.

This is the closest architectural analogue to what we need: drive a **closed-source Windows
desktop EDA app** from an MCP server.

### Reusable ideas (adopted)
- **`atomicfile.py`**: stage to temp, `os.replace` over target, with a retry loop because
  Windows AV/indexers hold the destination open (`WinError 5/32`) — measured 2 failures in 8
  renames on the author's machine. Our writer uses this exact strategy.
- **`_ThreadAwareStdout`**: keeps the MCP JSON-RPC stream on the real stdout and pushes every
  background-thread write to stderr, because strict clients close the transport on one stray
  byte. Adopted verbatim in spirit (our server makes stdout the sole JSON-RPC channel).
- **`safety.py` read-only env switch** (`EDA_AGENT_READONLY`) plus a written statement of the
  threat model (design-file free text reaches the model; a human is assumed to be watching).
  We adopt the read-only switch and the honesty about limits.
- **`scope`** module (path confinement) and **`checkpoint`** (restorable backup blobs) — the
  same two guards our constraints require.
- Backend/toolset registry so unimplemented capabilities simply do not appear.

### Not reusable
Altium DelphiScript bridge, PCB domain logic, dashboard UI.

**Verdict:** highest-value reference for server hardening and Windows file safety. Patterns
adopted, no code copied.

---

## 5. External EDA tools — evaluated, not integrated in this goal

| Tool | URL | License | Role | Decision for this goal |
|---|---|---|---|---|
| Yosys | github.com/YosysHQ/yosys | ISC | Verilog synthesis | Out of scope (no Verilog path yet); planned |
| Icarus Verilog | github.com/steveicarus/iverilog | GPL-2.0 | Functional simulation | Out of scope; planned |
| Verilator | github.com/verilator/verilator | LGPL-3.0 / Artistic-2.0 | Fast Verilog sim | Out of scope; planned |
| ngspice | github.com/ngspice/ngspice | BSD-3-Clause | SPICE simulation | Planned; DSCH already emits `.cir` |
| KLayout | github.com/KLayout/klayout | GPL-3.0 | GDSII/OASIS inspection | Not applicable — `.MSK` is not GDSII |
| Magic | github.com/RTimothyEdwards/magic | BSD-style | Layout/DRC | Not applicable — needs a Microwind-compatible tech file |
| OpenROAD | github.com/The-OpenROAD-Project/OpenROAD | Apache-2.0 | Physical design | Not applicable to `.MSK` |
| OpenLane | github.com/The-OpenROAD-Project/OpenLane | Apache-2.0 | RTL→GDSII | Not applicable to `.MSK` |

Every one of these is complementary at the *flow* level and incompatible at the *file* level.
Nothing is claimed as integrated.

---

## 6. Automation libraries

| Library | URL | License | Decision |
|---|---|---|---|
| pywinauto | github.com/pywinauto/pywinauto | BSD-3-Clause | Candidate for window detection + UIA if native launch/screenshot is insufficient |
| pyautogui | github.com/asweigart/pyautogui | BSD-3-Clause | Last resort only; coordinate clicking is brittle by construction |

Both are Win32/GUI tools, not file-format tools. This goal prefers `subprocess` launch +
Win32 `FindWindow`/screenshot first and adds a dependency only if that fails in practice.

---

## 6b. Corrections to the public `microwind_msk_format_notes.md` (OdaiJ)

Each row checked against the Microwind 3.5 fixture set (counts in `docs/FILE_FORMATS.md`).

| Public note claim | Fixture evidence |
|---|---|
| `M5`/`M6` are hypotheses | **Real**: 427 / 288 rects |
| `V4`/`V5` are hypotheses | **Real**: 330 / 292 rects |
| only `REC` observed as a primitive | 12+ keywords: `RLCR/RLCC/RLCL/RST/CAPA/SELF/HELP/TITLE/$…` |
| `REC` has 5 args | 212 rects carry a 6th arg (`OP`, `P2` only; `OP` includes 256) |
| layer set = 9 codes | 23 codes, incl. `PA`, `P2`, `OP`, `M7`, `M8`, `V6`, `V7` |
| `$- 1000 0` meaning unconfirmed | generic net label (1,608 uses); `$1`/`$0` are the power roles |
| no files shipped | 245 real layouts on this machine as ground truth |

Everything else in that note (skeleton, via pad rule, duplicate pads, TITLE point-in-shape,
voltage-pattern idea) matched the fixtures and is reused with attribution.

---

## 6c. What this project borrows, and from where

| Borrowed idea | Source | License | Where it lives |
|---|---|---|---|
| Confidence-labelled format claims | OdaiJ | none declared | every claim in `FILE_FORMATS.md` is CONFIRMED or ASSUMED |
| Voltage-pattern power grid, parity row/column orientation | OdaiJ | none declared | re-implemented in `microwind/power_grid.py` |
| Atomic write + Windows rename retry | eda-agent | Apache-2.0 | `microwind/safety.py` |
| Read-only switch + path confinement | eda-agent / EDA_MCP | Apache-2.0 / MIT | `microwind/safety.py` |
| stdout purity for strict MCP clients | eda-agent | Apache-2.0 | `server.py` logging setup |
| Flow-grouped tool names | MCP4EDA | ISC | `tools/*.py` naming |

No code was copied. OdaiJ has no license, so only its ideas are used.

---

## 7. Consolidated verdict

1. **Build the format layer from the local fixtures**, not from the public notes. The OdaiJ
   note is a strong starting hypothesis set, not a specification.
2. **Copy no code.** OdaiJ has no license; adopt only its ideas and its confidence-labelling
   discipline.
3. **Adopt eda-agent's Windows-safety patterns**: atomic replace with retry, stdout purity,
   read-only mode, path confinement, restorable backups.
4. **Adopt EDA_MCP's command guard** for anything that shells out.
5. **Adopt MCP4EDA's flow grouping** for tool naming, and explicitly reject GDSII/OpenLane
   interop as incompatible rather than pretending it works.
6. Microwind and DSCH expose **no documented RPC/CLI interface** — the only durable
   automation surface is their text file formats, with GUI launch/screenshot as a thin
   verified supplement.
