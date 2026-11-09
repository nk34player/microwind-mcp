"""SPICE side of the compiler: netlist -> ngspice -> delays + truth table.

The netlist is the synthesized transistor list (same devices as the layout), the
models are the vendor cards shipped with the install (``dsch35/rules/spice.lib``,
LEVEL=3) and the simulator is ngspice.  Nothing here claims to be Microwind's own
extractor: every result is labelled ``simulator: ngspice`` and the deck is written
next to the waveform so the run can be repeated by hand.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .logic import Circuit

LAM = 0.06          # cmos012 lambda in um
VDD = 1.2


class SpiceError(RuntimeError):
    pass


def ngspice_exe() -> str:
    exe = shutil.which("ngspice")
    if not exe:
        raise SpiceError("ngspice not found on PATH")
    return exe


def models_from_lib(path: str | Path) -> str:
    """Pull the complete .MODEL cards (TN/TP, with '+' continuations) from spice.lib."""
    lines = Path(path).read_text(encoding="latin-1").splitlines()
    cards: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip().upper().startswith(".MODEL"):
            cards.append(lines[i])
            i += 1
            while i < len(lines) and lines[i].strip().startswith("+"):
                cards.append(lines[i])
                i += 1
            continue
        i += 1
    if not cards:
        raise SpiceError(f"no .MODEL cards in {path}")
    return "\n".join(cards) + "\n"


def _periods(n: int) -> list[float]:
    """Clock periods, binary weighted: the last input is the slowest."""
    # same binary weighting as the clock labels written into the layout (1,2,4,8 ns)
    return [1.0e-9 * (2 ** i) for i in range(n)]


def build_deck(circuit: Circuit, models: str, vdd: float = VDD,
               cload: float = 1e-15) -> tuple[str, dict[str, int]]:
    inputs = circuit.inputs
    nodes: dict[str, str] = {"VDD": "VDD", "VSS": "0"}
    for name in inputs + [circuit.name]:
        nodes[name] = name
    for d in circuit.devices:
        for net in (d.source, d.drain):
            nodes.setdefault(net, net)
    out = nodes[circuit.name]

    lines = [
        f"* {circuit.name} = {circuit.expression}",
        "* synthesized transistor netlist (not Microwind extraction)",
        f".param vdd={vdd}",
        "VDD VDD 0 DC {vdd}",
    ]
    periods = _periods(len(inputs))
    for i, (name, p) in enumerate(zip(inputs, periods)):
        # staggered starts: coincident edges make ngspice choke on the LEVEL=3 cards
        delay_ns = 0.05 + 0.1 * i
        lines.append(
            f"V{name} {nodes[name]} 0 PULSE(0 {{vdd}} {delay_ns:.3f}n 20p 20p "
            f"{(p / 2 - 40e-12) * 1e9:.5f}n {p * 1e9:.5f}n)")
    for d in circuit.devices:
        model = "TN" if d.kind == "n" else "TP"
        bulk = 0 if d.kind == "n" else 1
        lines.append(
            f"M{d.name} {nodes[d.drain]} {nodes[d.gate]} {nodes[d.source]} {bulk} {model} "
            f"W={d.width * LAM:.2f}U L=0.12U")
    lines.append(f"C{out} {out} 0 {cload * 1e15:.3f}f")
    lines.append(".options reltol=0.01 abstol=1e-10 vntol=1e-6 gmin=1e-12 itl1=500")
    lines.append("*")
    lines.append(models.rstrip())
    lines.append("*")
    lines.append(".control")
    # 8 fast-clock periods visit all 2**n input combinations (binary weighted clocks)
    end_ns = 8 * periods[0] * 1e9 + 1.0     # one extra period so the last combo settles
    lines.append(f"tran 1p {end_ns:.3f}n")
    lines.append("set wr_singlescale")
    lines.append("set wr_vecnames")
    vecs = " ".join(f"v({nodes[n]})" for n in inputs + [circuit.name])
    lines.append(f"wrdata waves.txt {vecs}")
    lines.append("quit")
    lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n", nodes


def run(circuit: Circuit, workdir: str | Path, models_path: str | Path) -> dict:
    """Run ngspice in ``workdir``; returns waveform data and measured delays."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    models = models_from_lib(models_path)
    deck, nodes = build_deck(circuit, models)
    (workdir / "circuit.cir").write_text(deck, encoding="ascii", errors="ignore")
    exe = ngspice_exe()
    proc = subprocess.run(
        [exe, "-b", "circuit.cir"], cwd=workdir, capture_output=True, text=True, timeout=180)
    waves = workdir / "waves.txt"
    if proc.returncode != 0 or not waves.exists():
        raise SpiceError(f"ngspice failed: {proc.stderr[-800:]} {proc.stdout[-800:]}")
    samples = _parse_waves(waves)
    names = circuit.inputs + [circuit.name]
    table = _sample_truth(samples, names, circuit)
    delays = _delays(samples, names, circuit)
    return {
        "ok": True,
        "simulator": "ngspice",
        "deck": str(workdir / "circuit.cir"),
        "waves": str(waves),
        "truth_table": table,
        "delays": delays,
        "log_tail": proc.stdout.strip().splitlines()[-3:],
    }


def _parse_waves(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as fh:
        header = fh.readline().split()
        names = [h for h in header if h.lower().startswith("v(")]
        for line in fh:
            parts = line.split()
            if len(parts) < len(names) + 1:
                continue
            rec = {"t": float(parts[0])}
            for i, name in enumerate(names):
                rec[name] = float(parts[1 + i])
            rows.append(rec)
    if not rows:
        raise SpiceError("no samples in waves.txt")
    return rows


def _levels(samples: list[dict], name: str) -> list[float]:
    return [s[name] for s in samples]


def _crossings(times: list[float], values: list[float], level: float, rising: bool):
    out = []
    for i in range(1, len(values)):
        a, b = values[i - 1], values[i]
        if rising and a < level <= b:
            frac = (level - a) / (b - a) if b != a else 0
            out.append((times[i - 1] + frac * (times[i] - times[i - 1]), "rise"))
        elif not rising and a > level >= b:
            frac = (level - a) / (b - a) if b != a else 0
            out.append((times[i - 1] + frac * (times[i] - times[i - 1]), "fall"))
    return out


def _delays(samples: list[dict], names: list[str], circuit: Circuit) -> dict:
    times = [s["t"] for s in samples]
    out_key = next(k for k in samples[0] if k != "t" and k.endswith(f"({circuit.name})"))
    out_vals = [s[out_key] for s in samples]
    out_edges = _crossings(times, out_vals, VDD / 2, True) + _crossings(times, out_vals, VDD / 2, False)
    per_input = {}
    for name in circuit.inputs:
        key = next(k for k in samples[0] if k != "t" and k.endswith(f"({name})"))
        vals = [s[key] for s in samples]
        in_edges = _crossings(times, vals, VDD / 2, True) + _crossings(times, vals, VDD / 2, False)
        found = []
        for t_in, direction in in_edges:
            after = [(t_out, d) for t_out, d in out_edges if t_out > t_in + 1e-15]
            if not after:
                continue
            t_out, d = min(after)
            dt = (t_out - t_in) * 1e12
            if dt < 500:             # causal window: 500 ps
                found.append({"in": round(t_in * 1e12, 1), "edge": direction,
                              "out": direction == "rise" and "fall" or "rise",
                              "delay_ps": round(dt, 1)})
        if found:
            vals_ps = [f["delay_ps"] for f in found]
            per_input[name] = {
                "min_ps": min(vals_ps),
                "max_ps": max(vals_ps),
                "avg_ps": round(sum(vals_ps) / len(vals_ps), 1),
                "samples": found[:6],
            }
    return per_input


def _sample_truth(samples: list[dict], names: list[str], circuit: Circuit) -> list[dict]:
    """Every input combination the clocks visit, sampled after it has settled."""
    keys = {n: next(k for k in samples[0] if k != "t" and k.endswith(f"({n})")) for n in names}
    seen: dict[tuple, dict] = {}
    run_bits: tuple | None = None
    run_start = 0.0
    for idx, s in enumerate(samples):
        bits = tuple(int(s[keys[n]] > VDD / 2) for n in names[:-1])
        if bits != run_bits:
            run_bits, run_start = bits, s["t"]
        if s["t"] - run_start < 1e-10:          # require 100 ps of quiet inputs
            continue
        if bits in seen:
            continue
        seen[bits] = {
            "inputs": dict(zip(names[:-1], bits)),
            "output": int(s[keys[names[-1]]] > VDD / 2),
            "sampled_at_ns": round(s["t"] * 1e9, 3),
        }
    return [seen[b] for b in sorted(seen)]


def _conducts(circuit: Circuit, stage: dict, kind: str, state: dict[str, int]) -> bool:
    """Is there a conducting path from the stage output to VSS (n) / VDD (p)?"""
    out = stage["output"]
    src = "VSS" if kind == "n" else "VDD"
    edges = []
    for d in circuit.devices:
        if d.stage != stage["stage"] or d.kind != kind:
            continue
        gate_on = state.get(d.gate, 0) == (1 if kind == "n" else 0)
        if gate_on:
            edges.append((d.source, d.drain))
    seen, stack = {out}, [out]
    while stack:
        node = stack.pop()
        for a, b in edges:
            for u, v in ((a, b), (b, a)):
                if u == node and v not in seen:
                    seen.add(v)
                    stack.append(v)
    return src in seen


def switch_level(circuit: Circuit, values: dict[str, int]) -> int | None:
    """Independent switch-level evaluation of the generated transistor list."""
    state = {n: values.get(n, 0) for n in circuit.inputs}
    for stage in circuit.stages:
        pulled_down = _conducts(circuit, stage, "n", state)
        pulled_up = _conducts(circuit, stage, "p", state)
        if pulled_down and pulled_up:
            return None                      # contention: neither 0 nor 1
        if pulled_down:
            state[stage["output"]] = 0
        elif pulled_up:
            state[stage["output"]] = 1
    return state.get(circuit.name)


def truth_table_switch(circuit: Circuit) -> list[dict]:
    rows = []
    names = circuit.inputs
    for i in range(2 ** len(names)):
        vals = {n: (i >> (len(names) - 1 - k)) & 1 for k, n in enumerate(names)}
        rows.append({"inputs": vals, "output": switch_level(circuit, vals)})
    return rows


def _step_deck(circuit: Circuit, models: str, target: str, fixed: dict[str, int],
               start: int, vdd: float, cload: float) -> str:
    def nm(net: str) -> str:
        return "0" if net == "VSS" else net

    lines = [
        f"* {circuit.name}: step response of {target}",
        ".param vdd=1.2",
        "VDD VDD 0 DC {vdd}",
    ]
    for name in circuit.inputs:
        if name == target:
            lines.append(f"V{name} {nm(name)} 0 PULSE({start} {1 - start} 10p 5p 5p 200p 400p)")
        else:
            lines.append(f"V{name} {nm(name)} 0 DC {fixed[name]}")
    for d in circuit.devices:
        model = "TN" if d.kind == "n" else "TP"
        bulk = 0 if d.kind == "n" else 1
        lines.append(
            f"M{d.name} {nm(d.drain)} {nm(d.gate)} {nm(d.source)} {bulk} {model} "
            f"W={d.width * LAM:.2f}U L=0.12U")
    out = circuit.name
    lines.append(f"C{out} {out} 0 {cload * 1e15:.3f}f")
    lines.append(".options reltol=0.01 abstol=1e-10 vntol=1e-6 gmin=1e-12 itl1=500")
    lines.append(".options reltol=0.01 abstol=1e-10 vntol=1e-6 gmin=1e-12 itl1=500")
    lines.append("*")
    lines.append(models.rstrip())
    lines.append("*")
    lines.append(".control")
    lines.append("tran 0.2p 400p")
    lines.append("set wr_singlescale")
    lines.append("set wr_vecnames")
    lines.append(f"wrdata step.txt v({target}) v({out})")
    lines.append("quit")
    lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def _run_step(circuit: Circuit, workdir: Path, models: str, target: str,
              fixed: dict[str, int], start: int, vdd: float, cload: float) -> dict | None:
    deck = _step_deck(circuit, models, target, fixed, start, vdd, cload)
    (workdir / "step.cir").write_text(deck, encoding="ascii", errors="ignore")
    proc = subprocess.run([ngspice_exe(), "-b", "step.cir"], cwd=workdir,
                          capture_output=True, text=True, timeout=120)
    path = workdir / "step.txt"
    if proc.returncode != 0 or not path.exists():
        return None
    samples = _parse_waves(path)
    tkey, okey = f"v({target})", f"v({circuit.name})"
    times = [s["t"] for s in samples]
    tin = _crossings(times, [s[tkey] for s in samples], vdd / 2, True)
    tin += _crossings(times, [s[tkey] for s in samples], vdd / 2, False)
    tout = _crossings(times, [s[okey] for s in samples], vdd / 2, True)
    tout += _crossings(times, [s[okey] for s in samples], vdd / 2, False)
    if not tin or not tout:
        return None
    t_in, in_edge = min(tin)
    after = [(t, d) for t, d in tout if t > t_in]
    if not after:
        return None
    t_out, out_edge = min(after)
    return {"input_edge": in_edge, "output_edge": out_edge,
            "delay_ps": round((t_out - t_in) * 1e12, 1)}


def measure_delays(circuit: Circuit, workdir: str | Path, models_path: str | Path,
                   vdd: float = VDD, cload: float = 1e-15) -> dict:
    """Pulse one input at a time (others held) and measure tpLH / tpHL."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    models = models_from_lib(models_path)
    table = truth_table_switch(circuit)
    out: dict[str, dict] = {}
    for name in circuit.inputs:
        want = {(0, 1): None, (1, 0): None}      # output 0->1 / 1->0
        for row in table:
            other = dict(row["inputs"])
            other[name] = 1 - other[name]
            partner = next((r for r in table if r["inputs"] == other), None)
            if partner is None:
                continue
            key = (row["output"], partner["output"])
            if key not in want or want[key] is not None:
                continue
            fixed = {k: v for k, v in row["inputs"].items() if k != name}
            want[key] = _run_step(circuit, workdir, models, name, fixed,
                                  row["inputs"][name], vdd, cload)
            if all(v is not None for v in want.values()):
                break
        rise, fall = want[(0, 1)], want[(1, 0)]
        rec = {}
        if rise:
            rec["tpLH_ps"] = rise["delay_ps"]
        if fall:
            rec["tpHL_ps"] = fall["delay_ps"]
        vals = [v for v in (rec.get("tpLH_ps"), rec.get("tpHL_ps")) if v is not None]
        if vals:
            rec["avg_ps"] = round(sum(vals) / len(vals), 1)
            out[name] = rec
    return out
