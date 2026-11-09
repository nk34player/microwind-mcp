"""Server configuration: install locations and the directories writes are allowed in.

Resolution: explicit JSON file (``MICROWIND_MCP_CONFIG``) → environment variables →
no implicit machine-specific install paths. The project directories form the write
boundary enforced by ``microwind.safety.resolve_in_roots``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAMES = ("microwind-mcp.json", "config.json")


@dataclass
class Config:
    microwind_home: Path | None = None
    dsch_home: Path | None = None
    project_dirs: list[Path] = field(default_factory=list)
    default_tech: str | None = None
    log_file: Path | None = None
    readonly: bool = False

    def roots(self) -> list[Path]:
        return [p for p in self.project_dirs if p]


def _config_path() -> Path | None:
    env = os.environ.get("MICROWIND_MCP_CONFIG")
    if env:
        return Path(env).expanduser()
    for name in DEFAULT_CONFIG_NAMES:
        cand = Path.cwd() / name
        if cand.is_file():
            return cand
    return None


def _readonly_value(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def load_config() -> Config:
    cfg = Config()
    path = _config_path()
    if path is not None and path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if raw.get("microwind_home"):
            cfg.microwind_home = Path(raw["microwind_home"]).expanduser()
        if raw.get("dsch_home"):
            cfg.dsch_home = Path(raw["dsch_home"]).expanduser()
        cfg.project_dirs = [Path(p).expanduser() for p in raw.get("project_dirs", []) if p]
        cfg.default_tech = raw.get("default_tech")
        if raw.get("log_file"):
            cfg.log_file = Path(raw["log_file"]).expanduser()
        cfg.readonly = _readonly_value(raw.get("readonly"))

    if os.environ.get("MICROWIND_HOME"):
        cfg.microwind_home = Path(os.environ["MICROWIND_HOME"]).expanduser()
    if os.environ.get("DSCH_HOME"):
        cfg.dsch_home = Path(os.environ["DSCH_HOME"]).expanduser()
    if os.environ.get("MICROWIND_MCP_PROJECTS"):
        cfg.project_dirs = [
            Path(p).expanduser()
            for p in os.environ["MICROWIND_MCP_PROJECTS"].split(os.pathsep)
            if p
        ]
    if os.environ.get("MICROWIND_MCP_READONLY", "").strip() not in ("", "0", "false", "False"):
        cfg.readonly = True

    if not cfg.project_dirs:
        cfg.project_dirs = [Path.cwd() / "projects", Path.cwd() / "examples" / "generated"]
    return cfg
