"""Safety boundaries for tools that write outside the JSON layout writers."""

from __future__ import annotations

import pytest

from microwind.safety import SafetyError
from microwind_tools.app_tools import screenshot


def test_screenshot_refuses_outside_project(tmp_path, monkeypatch):
    monkeypatch.setenv("MICROWIND_MCP_PROJECTS", str(tmp_path))
    with pytest.raises(SafetyError):
        screenshot(str(tmp_path.parent / "outside.png"))


def test_screenshot_refuses_readonly(tmp_path, monkeypatch):
    monkeypatch.setenv("MICROWIND_MCP_PROJECTS", str(tmp_path))
    monkeypatch.setenv("MICROWIND_MCP_READONLY", "1")
    with pytest.raises(SafetyError):
        screenshot(str(tmp_path / "shot.png"))


def test_config_readonly_is_enforced(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text('{"readonly": true}', encoding="utf-8")
    monkeypatch.setenv("MICROWIND_MCP_CONFIG", str(config))
    monkeypatch.setenv("MICROWIND_MCP_PROJECTS", str(tmp_path))
    monkeypatch.delenv("MICROWIND_MCP_READONLY", raising=False)
    with pytest.raises(SafetyError):
        screenshot(str(tmp_path / "shot.png"))
