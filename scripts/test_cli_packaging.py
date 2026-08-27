#!/usr/bin/env python3
"""Regression tests for CLI-first packaging and provider-neutral handoff."""

from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from render_preview import render_html


ROOT = Path(__file__).resolve().parent.parent


class CliPackagingTests(unittest.TestCase):
    def test_console_entry_and_public_schemas_exist(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["scripts"]["uidw"], "uidw:main")
        for name in ("ui-graph.schema.json", "ui-agent-job.schema.json"):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertIn("$schema", schema)

    def test_skill_is_thin_and_cli_first(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(skill.splitlines()), 120)
        self.assertIn("uidw --repo <repo> context --json", skill)
        self.assertIn("The CLI, not the skill prompt, owns scanning", skill)
        self.assertIn("metadata:", skill)
        self.assertIn("compatibility:", skill)

    def test_installers_cover_supported_agents(self) -> None:
        combined = (ROOT / "install.ps1").read_text(encoding="utf-8") + (ROOT / "install.sh").read_text(encoding="utf-8")
        for agent in ("codex", "claude", "cursor", "gemini", "copilot", "opencode", "agents"):
            self.assertIn(agent, combined)

    def test_generic_handoff_is_default_and_codex_is_optional(self) -> None:
        ir = {"project": {"name": "Sample"}, "screens": [], "nodes": {}, "versions": []}
        with tempfile.TemporaryDirectory() as directory:
            generic = render_html(ir, Path(directory))
            codex = render_html(ir, Path(directory), "codex")
        self.assertIn('"handoffProvider":"generic"', generic)
        self.assertIn('"handoffProvider":"codex"', codex)
        self.assertIn("open-agent-review", generic)
        self.assertIn("agent-handoff-panel", generic)
        self.assertIn('data-canvas-layer="findings"', generic)
        self.assertIn('data-view="compare"', generic)
        self.assertIn("compare-base-select", generic)
        self.assertIn("compare-target-select", generic)
        self.assertIn("resolvedFindingIdsForVersion", generic)
        self.assertNotIn('data-version-visibility="before"', generic)
        self.assertIn("finding-pin-card", generic)
        self.assertIn("data-collapse-finding", generic)
        self.assertIn("finding-list-index", generic)
        self.assertIn("bindCanvasPan", generic)
        self.assertIn("data-workbench-locale", generic)
        self.assertNotIn("open-codex-review", generic)
        self.assertNotIn("codex-handoff-panel", generic)


if __name__ == "__main__":
    unittest.main()
