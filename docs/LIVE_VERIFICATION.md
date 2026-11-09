# LIVE VERIFICATION — real applications

Run: 2026-11-04T23:07:25

Method per document: launch the executable → close the `About` splash (`WM_CLOSE`) →
focus the main window → **Alt, F, O** (`SendInput`) → set the filename field
(`WM_SETTEXT`) → Enter → read the window title → look for `#32770` modal dialogs →
capture the screen → terminate only that PID.

The command line that the 3.1 help documents (`Microwind35.exe mask.MSK rules.rul`)
is **ignored by 3.5**: tested with a full path, a bare name with matching cwd, and a
path plus rule file — the title stayed `Microwind35 - example` in all three cases.
Menu navigation is therefore the only verified load path.

Window titles are shown verbatim with the repository prefix replaced by `<repo>`.

| app | document | window title (verbatim) | dialogs | result | screenshot |
|---|---|---|---|---|---|
| Microwind 3.5 | `inverter.MSK` | Microwind35 - <repo>\examples\generated\inverter.MSK | none | **LOADED** | docs\screenshots\microwind_inverter.png |
| Microwind 3.5 | `nand2.MSK` | Microwind35 - <repo>\examples\generated\nand2.MSK | none | **LOADED** | docs\screenshots\microwind_nand2.png |
| Microwind 3.5 | `nor2.MSK` | Microwind35 - <repo>\examples\generated\nor2.MSK | none | **LOADED** | docs\screenshots\microwind_nor2.png |
| Microwind 3.5 | `inverter_power_grid.MSK` | Microwind35 - <repo>\examples\generated\inverter_power_grid.MSK | none | **LOADED** | docs\screenshots\microwind_inverter_power_grid.png |
| Microwind 3.5 | `power_grid.MSK` | Microwind35 - <repo>\examples\generated\power_grid.MSK | none | **LOADED** | docs\screenshots\microwind_power_grid.png |
| DSCH 3.5 | `dsch_add4_copy.sch` | Dsch3.5 - <repo>\examples\generated\dsch_add4_copy.sch | none | **LOADED** | docs\screenshots\dsch35_add4.png |
| DSCH 3.5 | `dsch_adder_copy.sch` | Dsch3.5 - <repo>\examples\generated\dsch_adder_copy.sch | none | **LOADED** | docs\screenshots\dsch35_adder.png |
| DSCH 3.5 | `dsch_and_copy.sch` | Dsch3.5 - <repo>\examples\generated\dsch_and_copy.sch | none | **LOADED** | docs\screenshots\dsch35_and.png |

## Diagnostics

- **Microwind 3.5** `inverter.MSK` — startup dialogs closed: About MicroWind; process terminated=True
- **Microwind 3.5** `nand2.MSK` — startup dialogs closed: About MicroWind; process terminated=True
- **Microwind 3.5** `nor2.MSK` — startup dialogs closed: About MicroWind; process terminated=True
- **Microwind 3.5** `inverter_power_grid.MSK` — startup dialogs closed: About MicroWind; process terminated=True
- **Microwind 3.5** `power_grid.MSK` — startup dialogs closed: About MicroWind; process terminated=True
- **DSCH 3.5** `dsch_add4_copy.sch` — startup dialogs closed: none; process terminated=True
- **DSCH 3.5** `dsch_adder_copy.sch` — startup dialogs closed: none; process terminated=True
- **DSCH 3.5** `dsch_and_copy.sch` — startup dialogs closed: none; process terminated=True
