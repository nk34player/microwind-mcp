# FILE FORMATS — Microwind 3.5 `.MSK`/`.RUL` and DSCH 3.5 `.sch`/`.sym`/`.tec`

Every statement is either **CONFIRMED** (measured on the files shipped with Microwind &
DSCH 3.5, or stated by the 3.5 help pages / `Microwind_v35.pdf`) or **ASSUMED** (a
plausible reading that no code may depend on). Evidence is a fixture name, a count, or a
doc page.

Reproduce every count here with:

```
python scripts/analyze_fixtures.py
```

Set `MICROWIND_HOME` / `DSCH_HOME`, or pass a product root as the only argument.

Fixtures are **read-only**. Nothing in this project writes into the installation. Tests
read them in place and write only to `tmp_path`.

Install roots (overridable via `MICROWIND_HOME` / `DSCH_HOME`):

| Product | Root | Executable |
|---|---|---|
| Microwind 3.5 | `<microwind-home>` | `system\Microwind35.exe`, `system\Silicon.exe` |
| DSCH 3.5 | `<dsch-home>` | `system\Dsch35.exe` |
| Manual | `<microwind-root>\Microwind_v35.pdf` | 4,484 lines of text (LITE user manual, 21/09/2009) |

---

## 1. Fixture inventory (measured on the 3.5 install)

| Location | Pattern | Count | Endings |
|---|---|---|---|
| `microwind35 full\Examples\**` | `*.msk` (case-insensitive) | **245** | CRLF, all 245 |
| `microwind35 full\rules` | `*.rul` | **16** | mixed |
| `microwind35 full\Html` | `*.htm` + images | 31 files | — |
| `dsch35 full\examples\**` | `*.sch` | **52** (+1 in `system/` = 53 total) | 52 CRLF-only; the 53rd (`system/example.sch`) is LF |
| `dsch35 full\ieee` + `examples` | `*.sym` | **95** (+1 in `system/` = 96 total) | CRLF, all |
| `dsch35 full\examples\**` | `*.cir` | 2 | — |
| `dsch35 full\rules` | `*.tec` | **8** | — |
| `dsch35 full\system` | `example.sch`, `example.v`, `example.cir`, `dsch3.ini`, `9tSram.sym` | 5 | — |

Encoding: **latin-1** for every fixture (non-ASCII only inside comments/`HELP` text,
e.g. `0.12µm`). Read and write as latin-1 bytes; never UTF-8.

The 245 layouts are organised by topic: `adders`, `amplifiers`, `analog`, `basic gates`,
`capacitance`, `counters`, `fpga`, `inductance`, `interconnects`, `inverter`, `ios`,
`latches`, `maths`, `memory`, `misc`, `mixers`, `mos`, `multiplexor`, `multiplier`,
`oscillator`, `pll`, `power_amplifier`, `sensor`, `soi`, `techno`, `adc - dac`.

---

## 2. `.MSK` — Microwind layout

### 2.1 Skeleton — CONFIRMED (245/245)

```
VERSION <M/D/YYYY H:MM:SS AM|PM>
FIG #<absolute path>
BB(<x1>,<y1>,<x2>,<y2>)
SIMU #<float>
[ZOOM(<x1>,<y1>,<x2>,<y2>)]
<body: REC / TITLE+$ / RLCR / ...>
FFIG <absolute path>
```

- First five keywords: `VERSION, FIG, BB, SIMU, REC` in **239** files,
  `…, ZOOM` in **6**. `ZOOM` is viewport state, not geometry.
- `FIG` keeps a leading `#`; `FFIG` repeats the same path without it.
- `BB` **contains** the geometry union; it is not always equal to it
  (`adc - dac\adc.msk`: `BB(-32,2,241,260)` vs geometry `(0,2,241,260)`).
  Writer recomputes the exact union only when geometry changed.
- `SIMU #<value>` values include `#2.00`, `#2.50`, `#20.00`. Meaning **ASSUMED**
  (simulation step). Preserved verbatim.
- No comment syntax anywhere. Unrecognised records must survive byte-exactly.

### 2.2 `REC` — rectangle — CONFIRMED (170,671 occurrences)

```
REC(x, y, w, h, LAYER)              base form
REC(x, y, w, h, LAYER, VALUE)       212 occurrences in the 3.5 set
```

- `(x,y)` = lower-left in **lambda** units, ints, may be negative; `w,h ≥ 0`.
  `REC(40,-25,0,0,…)` (zero-size) appears in DSCH-compiled layouts — legal.
- The 6th argument occurs only for `OP` and `P2`:
  `OP`: 0(17), 1(8), 2(22), 16(21), 32(18), **256(1)** · `P2`: 0(125).
  Semantics **ASSUMED** (device variant / parameter). Stored as an optional int and
  re-emitted unchanged.
- Microwind's via tool stamps a fresh `V<n>` + `4×4` pad on each adjacent metal even
  where metal already exists → overlapping duplicate rectangles are normal. Connectivity
  must union same-layer shapes; never assume one rectangle per wire.

### 2.3 Layer codes — CONFIRMED (all seen in 3.5 fixtures)

| Code | Meaning (from the `.rul` `cif` map) | Rects |
|---|---|---|
| `NW` | nwell | 1,011 |
| `DN` | diffn (N+ diffusion) | 14,472 |
| `DP` | diffp (P+ diffusion) | 10,898 |
| `PO` | poly | 18,544 |
| `CO` | contact | 37,112 |
| `ME` | metal1 | 30,988 |
| `M2`–`M8` | metal2 … metal8 | 17,154 / 5,504 / 418 / 427 / 288 / **5** / **5** |
| `VI` | via metal1↔metal2 | 13,446 |
| `V2`–`V7` | via2 … via7 | 5,353 / 462 / 330 / 292 / **6,716** / **6,716** |
| `PA` | passiv (passivation / pad opening) | 316 |
| `P2` | poly2 (MIM capacitor / floating gate) | 127 |
| `OP` | not in any `cif` line — **ASSUMED** device/variant overlay | 87 |

`M7`, `M8`, `V6`, `V7` are **3.5-only** and number in the thousands for `V6`/`V7`, so they
are real, not typos. The layer table is therefore data-driven: it merges the `.rul` `cif`
list with a known-code table, and refuses to drop an unknown code from a parsed file.

`.rul` `cif` grammar: `cif <microwind-layer> <cif-number> <overetch>`; `cmos012.rul` has
38 such lines (`nwell 1`, `diffp 17`, `diffn 16`, `aarea 2`, `poly 13`, `contact 19`,
`metal 23`, `via 25`, `metal2 27`, `via2 32`, …, `metal8`, `via7`, `passiv 31`, `text 94`).

### 2.4 `TITLE` + `$` codes — CONFIRMED grammar, PARTIAL semantics (3,126 labels)

```
TITLE <x> <y>  #<free text label>       ← two spaces before '#'
$<code> <a> <b> [<more...>]             ← immediately after the TITLE line
```

`(x,y)` is resolved by point-in-shape hit test to attach the label to geometry.

| code | arity | example | meaning |
|---|---|---|---|
| `$-` | 3 | `$- 1000 0` | plain net label (1,608) — the generic case |
| `$0` | 3 | `$0 1000 0` | VSS / logic 0 (347) |
| `$1` | 3 | `$1 1000 0` | VDD / logic 1 (293) |
| `$v` | 3 | `$v 1000 0` | probe / monitored node (477) |
| `$c` | 7 | `$c 1000 0   0.48   0.50   0.98   1.00` | clock, 4 floats (221) |
| `$C` | 7 | `$C 1000 0   1.00   1.05   2.05   2.10` | complementary clock (26) |
| `$s` | 7 | `$s 500 42 1000.0000 0.5000 0.0000 0.0000` | supply/sampling declaration (57) |
| `$p` | 3 / 7 | `$p 0 2750` | pulse source (9) |
| `$w` | 4…20 | `$w 1000 0 3 0.00 0 1.00 1 2.00 0` | waveform `<a> <b> <n> (t v)*n` (24) |
| `$O $T $Z $m $P $2 $W` | 3 / 7 | `$O 583 500` | unclassified, preserved verbatim |

Anything past `$-/$0/$1/$v` is **ASSUMED** (mV / delay / phase). The parser guarantees
only the binding: a `TITLE` plus the immediately following `$` record.

### 2.5 Other body records — CONFIRMED grammar

| Record | Grammar | Count |
|---|---|---|
| `RLCR` | `RLCR x1 y1 x2 y2 <int> #<value>` (`#20000`, `#R(poly)=3500`) | 148 |
| `RLCC` | `RLCC x1 y1 x2 y2 <int> #<float>` | 42 |
| `RLCL` | `RLCL x1 y1 x2 y2 <int> #<int>` | 23 |
| `RST` | `RST x y #<text>` | 34 |
| `CAPA` | `CAPA x y #<float>` | 21 |
| `SELF` | `SELF x y #<int>` | 4 |
| `HELP` | `HELP <free text>` — multi-line block emitted by the DSCH→layout compiler | 79 |
| `<numeric>` | bare number lines inside `$w`/`HELP` continuations | 68 |

---

## 3. `.RUL` — Microwind technology / design rules — CONFIRMED (16 files)

```
MICROWIND 3.5                                  plain header
NAME CMOS 0.12µm - 6 Metal                     plain line, free text
*  comment line
// trailing comment (also /* … */ in places)
lambda = 0.06    (Lambda is set to half the gate size)    key = value, optional description
cif metal 23 0.0125                                       layer ↔ CIF number ↔ overetch
```

- 213–434 lines per file; `cmos012.rul` has **254** `key = value` pairs and 38 `cif` lines.
- Plain lines also carry the MOS flavour selectors (`MOS1 low leakage`, `NMOS`, `PMOS`).

Key groups:

| Group | Keys | Meaning |
|---|---|---|
| switches | `lambda`, `metalLayers`, `lowK`, `salicide`, `edram`, `efram`, `mimcapa`, `strain` | `lambda` = µm per lambda = half minimum gate length |
| rules | `r101…rf10`, `rp01…rp05` | width/spacing/area; the numbering scheme is **ASSUMED** (`rN01` width, `rN02` spacing, `rN10` min surface) |
| stacks | `th*`, `he*` | layer thickness / height |
| resistivity | `re*` | sheet resistance per layer |
| capacitance | `c*` | aF/µm² or aF/µm |
| models | `l3*` (Level-3), `b4*` (BSIM4) | SPICE parameters |
| simulation | `deltaT`, `vdd`, `hvdd`, `temperature`, `riseTime` | defaults |

The reader exposes each numeric value plus its raw text; no key is assumed to be a DRC
rule unless it is in the table above.

### 3.1 DSCH `.tec` — CONFIRMED (8 files, 3.5 only)

```
DSCH 2.0 - technology file
NAME "CMOS 0.12um"
VERSION 14.12.2001
TIMEUNIT = 0.01
VDD = 1.2
TDelay = 0.03
ML  = "0.12u"
```

Same `key = value` shape as `.rul` but with quoted string values and no `cif` block; the
single technology reader handles both (`microwind.rul.Technology`).

---

## 4. DSCH `.sch` — schematic — CONFIRMED (53 files)

### 4.1 Skeleton

```
DSCH <version>                     e.g. DSCH 3.1, 3.5, 2.6i, "DSCH Ver 3.0"
VERSION <timestamp>
BB(<x1>,<y1>,<x2>,<y2>)            global drawing bounds
<symbol blocks, TEXT, CNC, OPTION, MEM …>
FFIG <absolute path>
```

Header versions measured across the 3.5 example set: `DSCH 3.1` (25), `3.1i`-style (10),
`2.6h` (5), `2.6b` (5), `2.6a` (3), `Ver 3.0` (2), `3.5` (2), `2.7a`, `2.5f`, `2.6c`
— the reader must accept any `DSCH…` string and never assume one version's grammar.
Endings: CRLF, except `clock\Clk24H00.sch` which mixes 400 CRLF with 1 LF.

### 4.2 Symbol block — CONFIRMED (919 blocks)

```
SYM  #<symbol name>                ← two spaces before '#'
BB(x1,y1,x2,y2)
TITLE <x> <y>  #<instance name>
MODEL <int>                        primitive id (85, 2084, 1, 69, …)
PROP <padded property string>       trailing spaces are significant
REC(x,y,w,h,r)                     'r' = body style
VIS <int>
PIN(<x>,<y>,<f>,<f>)<name>         no space before the pin name
LIG(<x1>,<y1>,<x2>,<y2>)           wire segment — 11,586 across the set
VLG   <verilog text>               compiled netlist line, free-form after 'VLG'
FSYM                               end of block
```

- Duplicate pin names are legal: DSCH writes `null` for several unconnected pins.
- **Records wrap across physical lines** in one fixture:
  `REC(40,-25,0,0,` then `)`. Records are assembled by paren balance, not by line.
- `VLG` carries the Verilog netlist DSCH generated for the schematic
  (`VLG   and #(15) and2_Cl12_Cl30(w43,w31,w42);`, `VLG  endmodule`).

### 4.3 Global records — CONFIRMED

| Record | Grammar | Count |
|---|---|---|
| `TEXT` | `TEXT x y #<free text>` | 131 |
| `CNC` | `CNC(<x> <y>)` (space-separated) | 362 |
| `OPTION` | `OPTION <int>` | present in the older fixtures |
| `MEM` | `MEM;` opens an assembly block; `MEM<label> <text>` lines follow | — |

`CNC` and `MODEL` semantics are **ASSUMED** (connection point; primitive id table is not
published). The reader exposes `SYM #name`, pins, wires, `MODEL` id and `VLG` text, which
is what a consumer actually needs.

### 4.4 `.sym` — user symbol — CONFIRMED (96 files, CRLF)

Variants seen: `USER SYMBOL by DSCH <ver>` (8), `DSCH<n>` (39+24+…), bare `SYM  #name`
(4). Body records: `BB`, `TITLE`, `MODEL`, `REC` (4 args), `PIN`, `LIG`, sometimes
`PROP`/`VIS`/`VLG`/`MEM`/`DATE`. No `FFIG`.

The `.sym` library in `dsch35 full\examples` (96 files) is the practical reference for
symbol encoding; 3.1 shipped only 5, so 3.5 is decisively the better fixture set.

### 4.5 `.cir` — SPICE export

Plain SPICE with `* File name:`, `* Software version: DSCH 3.x`, sources
(`VCLK1 2 0 DC 0 PULSE(0 1.2 10.00N …)`), `.MODEL TN NMOS` with `+` continuations.
`spice.lib` (1 file) holds the models. Read-only in this goal.

---

## 5. Documented automation surfaces (3.5 help pages + `Microwind_v35.pdf`)

- **Command line (inherited from 3.1's `Html\index.htm`, unchanged):** the executable
  accepts two parameters — the mask file to load and the rule file to load, e.g.
  `Microwind35.exe fadd.MSK cmos018.rul`. This is the only documented non-GUI entry
  point and it is what `microwind_open` uses to preload a layout + technology.
- **`Html\file.htm` / manual ch. 1:** `.MSK` is the native layout; *File → Insert* merges
  a layout at the lower-right without renaming the current file; CIF import/export uses
  the `.RUL` `cif` map with per-layer overetch; *Convert Into → CIF* exports.
- **`Html\compile.htm` / manual ch. 4:** two compilers — *Compile One Line*
  (`Out=~(a.b)`; manual table gives `&`, `|`, `~`, `^`, with `.` also usable as AND) and
  *Compile Verilog File* with a fixed primitive set: `dreg, inv/not, and, nand, or, nor,
  xor, nmos`, 2–4 inputs. AND is built as NAND+inverter. If space is already occupied the
  cell origin is shifted right until free. The compiler also fixes VDD/VSS and assigns
  default clocks to the inputs.
- **`dsch35 full\html\verilog.htm`:** DSCH exports a restricted Verilog —
  `module`, `input`, `output`, primitive instances (`not1`, `nand2`, `xor2`, `nor2`, …),
  `endmodule`, with simulation parameters as comments (`// A CLK 10 10`).
- **`Microwind_v35.pdf` ch. 0:** the installed tree is
  `Microwind35\{examples *.MSK, html, rules *.RUL, system *.EXE}` and
  `Dsch35\{examples *.SCH/*.SYM, html, rules *.TEC, system *.EXE, ieee}` — confirming
  `.TEC` is DSCH's technology file and `.SYM` its symbol library.
- **Not documented anywhere in 3.5:** a batch/scripting mode, a DRC deck language, a
  netlist query API, or an inter-process interface. The file formats are therefore the
  automation surface, with GUI launch/screenshot as the only application control.

---

## 6. 3.1 → 3.5 delta (measured, not assumed)

| Aspect | 3.1 (older install) | 3.5 (this goal's reference) |
|---|---|---|
| Microwind executable | `system\Microwind31.exe` | `system\Microwind35.exe` |
| Layout fixtures | 276 `.MSK`, flat `examples\` | **245 `.MSK`**, 25 topic folders |
| Layout line endings | CRLF | CRLF |
| Metal layers used | `ME, M2…M6` | `ME, M2…**M8**` |
| Via layers used | `VI, V2…V5` | `VI, V2…**V7**` |
| `V6`/`V7` volume | absent | 6,716 each — the highest via counts after `VI` |
| `OP` 6th-arg value | 0,1,2,8,16,32,64,192 | 0,1,2,16,32,**256** |
| `P2` 6th-arg value | 0,1950,2000 | 0 only |
| DSCH executable | `dsch2\Dsch2.exe` | `dsch35 full\system\Dsch35.exe` |
| Schematic fixtures | 256 `.sch`, LF | **53 `.sch`**, CRLF (1 mixed) |
| Symbol fixtures | 5 `.sym` | **96 `.sym`** |
| DSCH technology files | none | **8 `.tec`** |
| DSCH help | `dsch2\Html\` | `dsch35 full\html\` |
| Schematic header versions | up to `DSCH 2.7a` | up to `DSCH 3.5` |
| MSK record keywords | REC/TITLE/$/RLCR/RLCL/RLCC/RST/CAPA/SELF/HELP | identical set |

Conclusion: 3.5 **extends** the format (more layers, more `.tec`/`.sym`, new `OP` value)
and does not redesign it. Anything written for 3.1 parses 3.5 unchanged, which the
round-trip harness proves.

---

## 7. Parser contract derived from this document

1. Read **bytes**, decode latin-1, split on `\n`, strip one trailing `\r` per line, keep
   the file's dominant ending and re-emit each line with its own ending.
2. Assemble logical records by parenthesis balance (the DSCH `REC` split case).
3. Classify each record by keyword; keep `raw` text for every record.
4. Writer re-emits in order: known+untouched records from `raw`, modified records
   regenerated, unknown records from `raw`. Untouched files must round-trip byte-exactly.
5. Never reorder, renumber or "clean" anything: duplicate via pads, zero-size rectangles,
   empty labels, `null` pins and `PROP` padding are all legitimate content.
