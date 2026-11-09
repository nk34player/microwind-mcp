"""Drive the real MCP server over STDIO and call the tools end to end.

    python scripts/mcp_smoke.py            # full run, writes into examples/generated/mcp_smoke/
    python scripts/mcp_smoke.py --list     # just print the tool list

Evidence produced: the `tools/list` payload and the JSON result of every tool call.

Ponytail note: the project dir must contain the files we create. The script points
MICROWIND_MCP_PROJECTS at the output directory so the safety layer accepts the writes —
that is the same switch a user configures.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microwind.install import find_dsch, find_microwind  # noqa: E402

OUT_REL = Path("examples") / "generated" / "mcp_smoke"
OUT = ROOT / OUT_REL


def _portable(value):
    """Replace machine-specific prefixes so the evidence file stays reproducible."""
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_portable(v) for v in value]
    if not isinstance(value, str):
        return value
    replacements = [(str(ROOT), "<repo>"), (str(Path.home()), "~")]
    for label, finder in (("<microwind-home>", find_microwind), ("<dsch-home>", find_dsch)):
        found = finder()
        if found:
            replacements.append((str(found.root), label))
    text = value
    for old, new in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        for variant in {old, old.replace("\\", "/"), old.replace("/", "\\")}:
            text = text.replace(variant, new)
    return text


class Client:
    def __init__(self, env: dict | None = None):
        e = dict(os.environ)
        e.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, "server.py"], cwd=ROOT, env=e,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.next_id = 0

    def _read(self, want_id: int, timeout: float = 180.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            payload = json.loads(line)
            if payload.get("id") == want_id:
                return payload
        raise RuntimeError(f"no reply for id {want_id} (stderr below)\n{self.proc.stderr.read()[:800]}")

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        return self._read(self.next_id)

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call(self, tool: str, **arguments) -> dict:
        reply = self.request("tools/call", {"name": tool, "arguments": arguments})
        if "error" in reply:
            return {"ok": False, "error": reply["error"]}
        content = reply["result"].get("content") or []
        for block in content:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError:
                    return {"ok": False, "raw": block["text"]}
        return {"ok": False, "error": "no content"}

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        finally:
            self.proc.wait(timeout=10)


def main() -> int:
    list_only = "--list" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    client = Client({"MICROWIND_MCP_PROJECTS": str(OUT_REL)})
    evidence: list[dict] = []
    try:
        client.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "mcp_smoke", "version": "1"},
        })
        client.notify("notifications/initialized")
        tools = client.request("tools/list")["result"]["tools"]
        print(f"tools/list -> {len(tools)} tools")
        for tool in tools:
            required = (tool.get("inputSchema") or {}).get("required", [])
            print(f"  {tool['name']:34} args={len((tool.get('inputSchema') or {}).get('properties', {}))} "
                  f"required={required}")
        evidence.append({"tools_list": tools})
        if list_only:
            return 0

        target = OUT_REL / "smoke_inverter.MSK"
        grid = OUT_REL / "smoke_grid.MSK"
        calls = [
            ("microwind_detect_installation", {}),
            ("microwind_get_technology", {}),
            ("microwind_get_layers", {}),
            ("microwind_create_layout", {"path": str(grid), "width": 260, "height": 200}),
            ("microwind_generate_power_grid", {"path": str(grid), "layers": ["ME", "M2"],
                                               "width": 200, "height": 160, "columns": 4, "rows": 3,
                                               "margin": 10}),
            ("microwind_read_layout", {"path": str(grid)}),
            ("microwind_run_checks", {"path": str(grid)}),
            ("microwind_generate_cmos_gate", {"gate": "inverter", "path": str(target)}),
            ("microwind_validate_file", {"path": str(target)}),
            ("microwind_parse_layout", {"path": str(target), "limit": 5, "kind": "TITLE"}),
            ("microwind_add_label", {"path": str(target), "x": 2, "y": 2, "text": "PROBE", "code": "$v"}),
            ("microwind_modify_layout", {"path": str(target), "move": [{"x": 20, "y": 0, "dx": 0, "dy": 2}]}),
            ("microwind_list_projects", {"directory": str(OUT_REL)}),
            ("microwind_analyze_power_grid", {"path": str(grid)}),
            ("microwind_screenshot", {"output": str(OUT_REL / "desktop.png")}),
        ]
        for name, args in calls:
            result = client.call(name, **args)
            status = "ok" if result.get("ok", True) else f"ERROR {result.get('error')}"
            print(f"{name:34} {status}")
            evidence.append({"tool": name, "arguments": args, "result": result})

        (ROOT / "docs" / "MCP_SMOKE_OUTPUT.json").write_text(
            json.dumps(_portable(evidence), indent=1)[:400000], encoding="utf-8"
        )
        print("\nwrote docs/MCP_SMOKE_OUTPUT.json")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
