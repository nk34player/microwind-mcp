"""Native gate compiler: one-line boolean expression -> transistor netlist -> `.MSK`.

This is the programmatic equivalent of Microwind's *Compile one line* box
(``Compile -> Compile One Line``, syntax listed in ``system/compiler.ini``)::

    F=~((A&B&C)|D)

Two synthesis paths are used:

* **complex gate** - when ``~F`` is monotone (only ``&`` and ``|`` over input
  literals), the pull-down network is built from ``~F`` and the pull-up is its
  dual, so the whole function is one static CMOS stage.
* **inverting decomposition** - otherwise the expression is decomposed into
  NAND / NOR / INV gates (the same primitives the complex path uses) and every
  stage is sized to be equivalent to the unit inverter.

Sizing rule (per stage): a transistor that sits in a series chain of ``k``
devices is ``k`` times the unit device, so the worst-case path matches the unit
inverter ``Wn/L = 4/2``, ``Wp/L = 8/2`` (lambda units, ``L = r302``).

The layout is generated from the same `.RUL` numbers as :mod:`microwind.cmos`
and keeps every net on its own metal1 track, with metal2 stubs from every
terminal - the stub layer is never the track layer, so crossings are not
shorts.  Body ties follow the vendor idiom measured in ``nor3.MSK``: a p+
diffusion (DP) to VSS for the substrate and an n+ diffusion (DN) inside every
nwell connected to VDD, so no nwell island is left floating.  Inputs get `$c`
clock labels (periods 1, 2, 4, 8 ns in input order, last input slowest) and the
output gets a `$v` probe label, so Microwind's simulator plots A,B,C,D and F.  Correctness is structural, not electrical: see
:func:`microwind.cmos.verify_cell`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cmos import PAD, VIA, _rules
from .msk import MskFile
from .rul import Technology

DEVICE_W = 28          # diffusion length along the row (lambda)
DEVICE_GAP = 18
TRACK_PITCH = 10
TRACK_H = 3
STUB_W = 3
NW_BORDER = 6
NW_TOP = 8

UNIT_N = 4             # 4/2 unit inverter
UNIT_P = 8
MAX_W = 64             # clamp, keeps a device inside one slot


class LogicError(ValueError):
    pass


# --------------------------------------------------------------------------- AST
@dataclass(frozen=True)
class Node:
    op: str                      # "var", "not", "and", "or", "xor"
    args: tuple = ()
    name: str = ""

    def __str__(self) -> str:
        if self.op == "var":
            return self.name
        if self.op == "not":
            return f"~{self.args[0]}"
        if self.op == "xor":
            return f"({self.args[0]}^{self.args[1]})"
        sign = "&" if self.op == "and" else "|"
        return "(" + sign.join(str(a) for a in self.args) + ")"


_TOKEN_RE = re.compile(r"\s*(~?\^|~|\^|&|\||\(|\)|[A-Za-z_][A-Za-z0-9_]*)")


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise LogicError(f"cannot tokenize {text[pos:pos+12]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens: list[str]):
        self.t = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise LogicError("unexpected end of expression")
        self.i += 1
        return tok

    def parse(self) -> Node:
        node = self.or_expr()
        if self.peek() is not None:
            raise LogicError(f"trailing {self.peek()!r}")
        return node

    def or_expr(self) -> Node:
        items = [self.xor_expr()]
        while self.peek() == "|":
            self.take()
            items.append(self.xor_expr())
        return items[0] if len(items) == 1 else Node("or", tuple(items))

    def xor_expr(self) -> Node:
        left = self.and_expr()
        while self.peek() in ("^", "~^"):
            op = self.take()
            right = self.and_expr()
            left = Node("xor", (left, right))
            if op == "~^":
                left = Node("not", (left,))
        return left

    def and_expr(self) -> Node:
        items = [self.unary()]
        while self.peek() == "&":
            self.take()
            items.append(self.unary())
        return items[0] if len(items) == 1 else Node("and", tuple(items))

    def unary(self) -> Node:
        tok = self.peek()
        if tok == "~":
            self.take()
            return Node("not", (self.unary(),))
        return self.atom()

    def atom(self) -> Node:
        tok = self.take()
        if tok == "(":
            node = self.or_expr()
            if self.take() != ")":
                raise LogicError("missing ')'")
            return node
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
            return Node("var", name=tok)
        raise LogicError(f"unexpected token {tok!r}")


def parse_expression(text: str) -> tuple[str, Node]:
    """Parse ``out=expr`` (the compiler.ini syntax)."""
    if "=" not in text:
        raise LogicError("expected '<name>=<expression>'")
    name, expr = text.split("=", 1)
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,7}", name):
        raise LogicError(f"bad output name {name!r} (1-8 alphanumeric chars)")
    if not expr.strip():
        raise LogicError("empty expression")
    return name, _Parser(_tokens(expr)).parse()


def variables(node: Node) -> list[str]:
    seen: list[str] = []

    def walk(n: Node) -> None:
        if n.op == "var" and n.name not in seen:
            seen.append(n.name)
        for a in n.args:
            walk(a)

    walk(node)
    return seen


def negate(node: Node) -> Node:
    """Push negation inwards (De Morgan), no double negation."""
    if node.op == "not":
        return node.args[0]
    if node.op == "and":
        return Node("or", tuple(negate(a) for a in node.args))
    if node.op == "or":
        return Node("and", tuple(negate(a) for a in node.args))
    return Node("not", (node,))


def _monotone(node: Node) -> bool:
    if node.op in ("not", "xor"):
        return False
    return all(_monotone(a) for a in node.args)


# --------------------------------------------------------- series/parallel tree
# ("var", name) | ("series", [...]) | ("parallel", [...])
def _sp(node: Node) -> tuple:
    if node.op == "var":
        return ("var", node.name)
    if node.op in ("and", "or"):
        kind = "series" if node.op == "and" else "parallel"
        kids: list[tuple] = []
        for a in node.args:
            sub = _sp(a)
            if sub[0] == kind:
                kids.extend(sub[1])
            else:
                kids.append(sub)
        return (kind, kids)
    raise LogicError(f"not series/parallel: {node}")


def _json(tree: tuple):
    """Nested list form of a series/parallel tree (for reports and drawings)."""
    if tree[0] == "var":
        return ["var", tree[1]]
    return [tree[0], [_json(c) for c in tree[1]]]


def _dual(tree: tuple) -> tuple:
    if tree[0] == "var":
        return tree
    kind = "parallel" if tree[0] == "series" else "series"
    return (kind, [_dual(t) for t in tree[1]])


# --------------------------------------------------------------- device netlist
@dataclass
class Transistor:
    name: str
    kind: str          # "n" | "p"
    source: str
    drain: str
    gate: str
    width: int         # lambda
    stage: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Circuit:
    name: str
    expression: str
    inputs: list[str]
    devices: list[Transistor]
    stages: list[dict] = field(default_factory=list)   # per-stage sizing evidence
    msk: MskFile | None = None
    nets: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "expression": self.expression,
            "inputs": self.inputs,
            "stages": self.stages,
            "devices": [d.to_dict() for d in self.devices],
            "layout": {
                "rectangles": len(self.msk.rects) if self.msk else 0,
                "sheets": None,
            },
        }


def _path_depth(tree: tuple) -> int:
    if tree[0] == "var":
        return 1
    if tree[0] == "series":
        return sum(_path_depth(c) for c in tree[1])
    return max(_path_depth(c) for c in tree[1])


def _size(tree: tuple, unit: int) -> dict[str, int]:
    """Per-variable multiplier: series devices on the worst path through it."""
    depth: dict[str, int] = {}

    def walk(t: tuple) -> dict[str, int]:
        if t[0] == "var":
            return {t[1]: 1}
        if t[0] == "series":
            out: dict[str, int] = {}
            total = sum(_path_depth(c) for c in t[1])
            for c in t[1]:
                for name, d in walk(c).items():
                    out[name] = max(out.get(name, 0), d + total - _path_depth(c))
            return out
        out = {}
        for c in t[1]:
            for name, d in walk(c).items():
                out[name] = max(out.get(name, 0), d)
        return out

    for name, d in walk(tree).items():
        depth[name] = min(unit * d, MAX_W)
    return {k: depth[k] for k in depth}


def _network_devices(tree: tuple, kind: str, top: str, bottom: str,
                     stage: str) -> tuple[list[Transistor], dict[str, int]]:
    """Transistors for one series/parallel network; returns (devices, widths)."""
    unit = UNIT_N if kind == "n" else UNIT_P
    widths = _size(tree, unit)
    out: list[Transistor] = []
    counter = [0]

    def new_node() -> str:
        counter[0] += 1
        return f"{stage}{kind}{counter[0]}"

    def wire(t: tuple, upper: str, lower: str) -> None:
        if t[0] == "var":
            out.append(Transistor(
                f"{kind}{len(out) + 1}", kind, upper, lower, t[1], widths[t[1]], stage))
        elif t[0] == "series":
            nodes = [upper] + [new_node() for _ in t[1][:-1]] + [lower]
            for i, child in enumerate(t[1]):
                wire(child, nodes[i], nodes[i + 1])
        else:  # parallel
            for child in t[1]:
                wire(child, upper, lower)

    wire(tree, top, bottom)
    return out, widths


def synthesize(expression: str) -> Circuit:
    name, ast = parse_expression(expression)
    inputs = variables(ast)
    devices: list[Transistor] = []
    stages: list[dict] = []
    nf = negate(ast)

    if _monotone(nf):
        pdn = _sp(nf)
        pun = _dual(pdn)
        dn, nw = _network_devices(pdn, "n", name, "VSS", "complex")
        up, pw = _network_devices(pun, "p", "VDD", name, "complex")
        devices += dn + up
        stages.append({
            "stage": "complex",
            "output": name,
            "function": f"F = {ast}",
            "pdn": str(nf),
            "sizing": {"n": nw, "p": pw},
            "pdn_tree": _json(pdn),
            "pun_tree": _json(pun),
        })
    else:
        memo: dict[str, str] = {}
        counter = [0]

        def new_net() -> str:
            counter[0] += 1
            return f"X{counter[0]}"

        def gate(kind: str, kids: list[str], out: str) -> None:
            stage = f"{kind}{len(stages) + 1}"
            if kind == "inv":
                devices.append(Transistor(f"n{len(devices)}", "n", "VSS", out, kids[0], UNIT_N, stage))
                devices.append(Transistor(f"p{len(devices)}", "p", "VDD", out, kids[0], UNIT_P, stage))
                stages.append({"stage": stage, "gate": "INV", "inputs": kids, "output": out,
                               "sizing": {"n": {kids[0]: UNIT_N}, "p": {kids[0]: UNIT_P}},
                               "pdn_tree": ["var", kids[0]],
                               "pun_tree": ["var", kids[0]]})
                return
            n_series = len(kids) if kind == "nand" else 1
            p_series = 1 if kind == "nand" else len(kids)
            if kind == "nand":
                nodes = ["VSS"] + [new_net() for _ in kids[:-1]] + [out]
                for i, kid in enumerate(kids):
                    devices.append(Transistor(f"n{len(devices)}", "n", nodes[i], nodes[i + 1], kid,
                                              min(UNIT_N * n_series, MAX_W), stage))
                for kid in kids:
                    devices.append(Transistor(f"p{len(devices)}", "p", "VDD", out, kid, UNIT_P, stage))
            else:
                for kid in kids:
                    devices.append(Transistor(f"n{len(devices)}", "n", "VSS", out, kid, UNIT_N, stage))
                nodes = ["VDD"] + [new_net() for _ in kids[:-1]] + [out]
                for i, kid in enumerate(kids):
                    devices.append(Transistor(f"p{len(devices)}", "p", nodes[i], nodes[i + 1], kid,
                                              min(UNIT_P * p_series, MAX_W), stage))
            if kind == "nand":
                pdn_t = ["series", [["var", k] for k in kids]]
                pun_t = ["parallel", [["var", k] for k in kids]]
            else:
                pdn_t = ["parallel", [["var", k] for k in kids]]
                pun_t = ["series", [["var", k] for k in kids]]
            stages.append({"stage": stage, "gate": kind.upper(), "inputs": kids, "output": out,
                           "sizing": {"n_series": n_series, "p_series": p_series},
                           "pdn_tree": pdn_t, "pun_tree": pun_t})

        def emit(node: Node) -> str:
            key = str(node)
            if key in memo:
                return memo[key]
            if node.op == "var":
                memo[key] = node.name
                return node.name
            if node.op == "not":
                inner = emit(node.args[0])
                out = new_net()
                gate("inv", [inner], out)
                memo[key] = out
                return out
            if node.op == "xor":
                a, b = emit(node.args[0]), emit(node.args[1])
                t1, t2, t3 = new_net(), new_net(), new_net()
                gate("nand", [a, b], t1)
                gate("nand", [a, t1], t2)
                gate("nand", [b, t1], t3)
                out = new_net()
                gate("nand", [t2, t3], out)
                memo[key] = out
                return out
            kids = [emit(a) for a in node.args]
            out = new_net()
            gate("nand" if node.op == "and" else "nor", kids, out)
            if node.op == "and" or node.op == "or":
                # NAND/NOR gives the inverted function: add the inverter so the
                # emitted net carries exactly the requested node value.
                final = new_net() if node is not ast else name
                gate("inv", [out], final)
                memo[key] = final
                return final
            memo[key] = out
            return out

        emit(ast)

    # keep n devices together, then p devices: body ties and well drawing expect it
    devices.sort(key=lambda d: (d.kind != "n",))

    circuit = Circuit(name, expression, inputs, devices, stages)
    circuit.msk, circuit.nets = _layout(circuit)
    return circuit


# -------------------------------------------------------------------- layout
def _device_geom(x0: int, kind: str, width: int, r: dict) -> dict:
    diff = "DN" if kind == "n" else "DP"
    gate = r["gate"]
    over = r["poly_over"]
    gx = x0 + DEVICE_W // 2 - gate // 2
    src_x = x0 + DEVICE_W // 6
    drn_x = x0 + DEVICE_W - DEVICE_W // 6 - r["contact"]
    co_y = r["co_diff"]

    rects = [
        (x0, 0, DEVICE_W, width, diff),
        (gx, -over - 6, gate, width + 2 * over + 6, "PO"),
        (src_x, co_y, r["contact"], r["contact"], "CO"),
        (drn_x, co_y, r["contact"], r["contact"], "CO"),
        (src_x - r["co_metal"], 0, PAD, PAD, "ME"),
        (drn_x - r["co_metal"], 0, PAD, PAD, "ME"),
        (src_x, co_y, VIA, VIA, "VI"),
        (drn_x, co_y, VIA, VIA, "VI"),
        # gate contact on the lower arm of the same polygon
        (gx, -over - 4, r["contact"], r["contact"], "CO"),
        (gx - r["co_metal"], -over - 5, PAD, PAD, "ME"),
        (gx, -over - 4, VIA, VIA, "VI"),
    ]
    return {
        "x0": x0,
        "rects": rects,
        "source_x": src_x,
        "drain_x": drn_x,
        "gate_x": gx,
        "source_point": (src_x, co_y),
        "drain_point": (drn_x, co_y),
        "gate_point": (gx, -over - 4),
        "width": width,
    }


def _body_tie(x0: int, kind: str, r: dict) -> dict:
    """Substrate tie (nMOS: p+ DP to VSS) or nwell tap (pMOS: n+ DN to VDD)."""
    if kind == "n":
        w, h, diff = 8, max(4, r["active_h"]), "DP"
        rects = [
            (x0, 0, w, h, diff),
            (x0 + 2, r["co_diff"], r["contact"], r["contact"], "CO"),
            (x0 + 2 - r["co_metal"], 0, PAD, PAD, "ME"),
            (x0 + 2, r["co_diff"], VIA, VIA, "VI"),
        ]
        return {"rects": rects, "point": (x0 + 2, r["co_diff"]), "x": x0, "w": w, "tap": False}
    w, h = 8, 4
    rects = [
        (x0 - NW_BORDER, -NW_BORDER, w + 2 * NW_BORDER, h + NW_BORDER + NW_TOP, "NW"),
        (x0, 0, w, h, "DN"),
        (x0 + 2, 1, r["contact"], r["contact"], "CO"),
        (x0 + 1, 0, PAD, PAD, "ME"),
        (x0 + 2, 1, VIA, VIA, "VI"),
    ]
    return {"rects": rects, "point": (x0 + 2, 1), "x": x0, "w": w, "tap": True}


def _layout(circuit: Circuit) -> tuple[MskFile, dict]:
    r = _rules(None)
    n_dev = [d for d in circuit.devices if d.kind == "n"]
    p_dev = [d for d in circuit.devices if d.kind == "p"]
    ties: list[tuple[str, dict]] = []
    slots = len(n_dev) + len(p_dev) + (1 if n_dev else 0) + (1 if p_dev else 0)

    x0 = 20
    geo: list[dict] = []
    for dev in n_dev + p_dev:
        g = _device_geom(x0, dev.kind, dev.width, r)
        geo.append({"dev": dev, "geom": g})
        x0 += DEVICE_W + DEVICE_GAP

    tie_geo: list[tuple[str, dict]] = []
    for kind in ("n", "p"):
        if (kind == "n" and n_dev) or (kind == "p" and p_dev):
            t = _body_tie(x0, kind, r)
            tie_geo.append((kind, t))
            x0 += t["w"] + DEVICE_GAP

    max_h = max(d.width for d in circuit.devices) if circuit.devices else 4
    top = max(max_h + NW_BORDER + 8, 40)
    width_units = x0 + 20
    # simulation window: the clocks double per input, so the slowest one only rises at
    # half its period; 1.25 periods plus 1 ns leaves room to see it switch and settle
    slowest = 1.0 * (2 ** max(0, len(circuit.inputs) - 1))
    simu = f"{slowest * 1.25 + 1.0:.2f}"
    msk = MskFile.new(width_units, top + 40, path=f"{circuit.name}.MSK", simu=simu)

    nets: dict[str, list[tuple[int, int]]] = {}
    for item in geo:
        dev, g = item["dev"], item["geom"]
        for rect in g["rects"]:
            msk.add_rect(*rect)
        if dev.kind == "p":
            # nwell encloses the p diffusion; the top margin holds the well tap
            msk.add_rect(
                g["x0"] - NW_BORDER, -NW_BORDER,
                DEVICE_W + 18, dev.width + NW_BORDER + NW_TOP, "NW",
            )
            # well tap: n+ diffusion INSIDE the nwell connected to VDD (the pattern in
            # nor3.MSK).  A contact straight on NW is not a tap, and Microwind then warns
            # "N-well region(s) floating".
            tap_x = g["x0"] + DEVICE_W + 5
            tap_y = dev.width + 2
            msk.add_rect(tap_x, tap_y, 4, 4, "DN")
            msk.add_rect(tap_x + 1, tap_y + 1, r["contact"], r["contact"], "CO")
            msk.add_rect(tap_x, tap_y, PAD, PAD, "ME")
            msk.add_rect(tap_x + 1, tap_y + 1, VIA, VIA, "VI")
            nets.setdefault("VDD", []).append((tap_x + 1, tap_y + 1))
        nets.setdefault(dev.source, []).append(g["source_point"])
        nets.setdefault(dev.drain, []).append(g["drain_point"])
        nets.setdefault(dev.gate, []).append(g["gate_point"])

    for kind, t in tie_geo:
        for rect in t["rects"]:
            msk.add_rect(*rect)
        nets.setdefault("VSS" if kind == "n" else "VDD", []).append(t["point"])

    # one metal1 track per net, metal2 stubs from every terminal
    order = sorted(nets, key=lambda n: ({"VDD": 0, "VSS": 1}.get(n, 2), n))
    track_info: dict[str, dict] = {}
    for k, net in enumerate(order):
        track_y = (max_h + NW_BORDER + 10) + k * TRACK_PITCH
        xs = [x for x, _ in nets[net]]
        lo, hi = min(xs) - 3, max(xs) + 3
        msk.add_rect(lo, track_y, hi - lo, TRACK_H, "ME")
        if net == "VDD":
            code, args = "$1", ("1000", "0")
        elif net == "VSS":
            code, args = "$0", ("1000", "0")
        elif net in circuit.inputs:
            # binary-weighted clocks in input order: the last input is the slowest,
            # which is what Simulate -> Clocks assumes when you add A,B,C,D in order
            period = 1.0 * (2 ** circuit.inputs.index(net))
            code = "$c"
            args = ("1000", "0",
                    f"{period / 2 - 0.02:.4f}", f"{period / 2:.4f}",
                    f"{period - 0.02:.4f}", f"{period:.4f}")
        elif net == circuit.name:
            code, args = "$v", ("1000", "0")
        else:
            code, args = "$-", ("1000", "0")
        msk.add_label(lo + 1, track_y + 1, net, code, args)
        stubs = []
        for (tx, ty) in nets[net]:
            y0 = ty - 1 if ty > 0 else ty
            msk.add_rect(tx, y0, STUB_W, (track_y + VIA) - y0, "M2")
            msk.add_rect(tx, track_y, VIA, VIA, "VI")
            stubs.append({"x": tx, "y0": y0, "y1": track_y + VIA})
        track_info[net] = {"track_y": track_y, "terminals": nets[net], "stubs": stubs}

    return msk, track_info


def to_spice(circuit: Circuit, vdd: float = 1.2, lib: str | None = None) -> str:
    """SPICE deck for the synthesized netlist (transistors from the netlist, not extracted)."""
    inputs = circuit.inputs
    nodes = {n: i + 10 for i, n in enumerate(inputs + [circuit.name])}
    nodes["VDD"] = 1
    nodes["VSS"] = 0
    for d in circuit.devices:
        for net in (d.source, d.drain):
            if net not in nodes:
                nodes[net] = len(nodes) + 12
    lines = [f"* {circuit.name}: {circuit.expression}", "* generated by microwind-mcp logic compiler",
             f"VDD 1 0 DC {vdd}"]
    for i, name in enumerate(inputs):
        p = 2.0e-9
        delay = i * 0.5e-9
        lines.append(
            f"V{name} {nodes[name]} 0 PULSE(0 {vdd} {delay:.4g} 20p 20p "
            f"{p - 40e-12:.4g} {2 * p:.4g})")
    lines.append("* transistors: MN/MP <d> <g> <s> <b> <model> W= L=")
    lam = 0.06
    for d in circuit.devices:
        model = "TN" if d.kind == "n" else "TP"
        bulk = 0 if d.kind == "n" else 1
        lines.append(
            f"M{d.name} {nodes[d.drain]} {nodes[d.gate]} {nodes[d.source]} {bulk} {model} "
            f"W={d.width * lam:.3f}U L={0.12:.2f}U")
    lines.append(f".options temp=27.0")
    lines.append(f".tran 1p 16n")
    lines.append(f"* measure: 50% crossing of output vs each input")
    for name in inputs:
        lines.append(f".meas tran t_{name} TRIG v({nodes[name]}) VAL={vdd/2:.3f} RISE=1 "
                     f"TARG v({nodes[circuit.name]}) VAL={vdd/2:.3f} FALL=1")
    if lib:
        lines.append(f".include {lib}")
    lines.append(".end")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- structural
def verify_circuit(circuit: Circuit) -> dict:
    """Every net's terminals in one geometric component; distinct nets never merge."""
    from .checks import _node_edges

    rects = circuit.msk.rects
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in _node_edges(circuit.msk):
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    def component_at(x: int, y: int) -> int | None:
        for i, r in enumerate(rects):
            if r.layer == "ME" and r.x <= x < r.x2 and r.y <= y < r.y2:
                return find(i)
        return None

    failures: list[str] = []
    comp_by_net: dict[str, set[int]] = {}
    for net, info in circuit.nets.items():
        comps = set()
        for (x, y) in info["terminals"]:
            idx = component_at(x, y)
            if idx is None:
                failures.append(f"net {net}: terminal ({x},{y}) is not on metal")
            else:
                comps.add(idx)
        comp_by_net[net] = comps
        if len(comps) > 1:
            failures.append(f"net {net}: spans {len(comps)} components (open)")

    seen: dict[int, str] = {}
    for net, comps in comp_by_net.items():
        for idx in comps:
            if idx in seen and seen[idx] != net:
                failures.append(f"nets {seen[idx]} and {net} share a component (short)")
            seen.setdefault(idx, net)

    return {
        "nets": {k: sorted(v) for k, v in comp_by_net.items()},
        "shorts_or_opens": failures,
        "ok": not failures,
    }


def check_circuit(circuit: Circuit, tech: Technology | None = None) -> dict:
    from .checks import check_width, check_spacing, check_overlaps

    width = check_width(circuit.msk, tech)
    spacing = check_spacing(circuit.msk, tech)
    overlaps = check_overlaps(circuit.msk)
    structural = verify_circuit(circuit)
    return {
        "name": circuit.name,
        "expression": circuit.expression,
        "rectangles": len(circuit.msk.rects),
        "structural": structural,
        "min_width_violations": width[:20],
        "min_spacing_violations": spacing[:20],
        "overlaps": overlaps[:20],
        "engine": "independent-geometry-checks (not Microwind native DRC)",
        "ok": structural["ok"] and not (width or spacing or overlaps),
    }
