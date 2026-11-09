"""Real MCP STDIO handshake: the server must initialize and list its tools."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Stdio:
    def __init__(self, args: list[str]):
        self.proc = subprocess.Popen(
            args, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )
        self.q: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.stderr: list[str] = []
        threading.Thread(target=self._pump_err, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.q.put(line)
        self.q.put(None)

    def _pump_err(self):
        for line in self.proc.stderr:
            self.stderr.append(line)

    def send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, msg_id: int, timeout: float = 30.0) -> dict:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.q.get(timeout=deadline - time.time())
            except queue.Empty:
                break
            if line is None:
                break
            payload = json.loads(line)          # a non-JSON line would raise here
            if payload.get("id") == msg_id:
                return payload
        raise AssertionError(f"no response with id {msg_id}; stderr={''.join(self.stderr)[:400]}")

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        finally:
            self.proc.wait(timeout=10)


def test_stdio_handshake_and_tool_list() -> None:
    client = Stdio([sys.executable, "server.py"])
    try:
        client.send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        init = client.wait_for(1)
        server_info = init["result"]["serverInfo"]
        assert server_info["name"] == "microwind-mcp"

        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = client.wait_for(2)
        tools = {t["name"]: t for t in listed["result"]["tools"]}
        assert len(tools) >= 20, f"expected 20+ tools, got {len(tools)}"

        expected = {
            "microwind_detect_installation", "dsch_detect_installation",
            "microwind_open", "microwind_close", "microwind_screenshot",
            "microwind_read_layout", "microwind_parse_layout", "microwind_validate_file",
            "microwind_create_layout", "microwind_add_rectangle", "microwind_add_label",
            "microwind_modify_layout", "microwind_get_layers", "microwind_get_technology",
            "microwind_generate_power_grid", "microwind_generate_power_rails",
            "microwind_analyze_power_grid", "microwind_generate_cmos_gate",
            "microwind_run_checks", "dsch_read_schematic", "dsch_validate_schematic",
        }
        missing = expected - set(tools)
        assert not missing, f"missing tools: {sorted(missing)}"

        for name, tool in tools.items():
            assert tool.get("description"), f"{name} has no description"
            assert "inputSchema" in tool, f"{name} has no input schema"

        # stdout must contain only JSON-RPC; diagnostics belong on stderr
        while not client.q.empty():
            line = client.q.get()
            if line:
                json.loads(line)
    finally:
        client.close()
