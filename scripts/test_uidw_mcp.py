#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uidw_mcp


class UidwMcpTests(unittest.TestCase):
    def test_argument_parser_keeps_repo_and_server_name(self) -> None:
        args = uidw_mcp.parse_args(["--repo", ".", "--name", "Local UI"])

        self.assertEqual(args.repo, Path("."))
        self.assertEqual(args.name, "Local UI")

    def test_workbench_result_is_bounded(self) -> None:
        result = uidw_mcp.compact_workbench_result({
            "version": 1,
            "status": "ready",
            "previewFile": "ui-preview.html",
            "workflow": "review",
            "largeInternalPayload": {"nodes": list(range(100))},
        })

        self.assertEqual(set(result), {"version", "status", "previewFile", "workflow"})

    def test_server_instructions_define_the_bounded_primary_route(self) -> None:
        self.assertIn("ui_project", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("ui_scope", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("sparse ui-ir.patch.json", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("explicit implementation request", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("ui_configure", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("ui_native_status", uidw_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("never describe source projection as a native render", uidw_mcp.SERVER_INSTRUCTIONS)

    def test_project_summary_exposes_required_setup_instead_of_routing_to_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "ir": root / "ui-ir.json",
                "context": root / "ui-context.json",
            }
            initialization = {"status": "clean", "initialization": {"status": "reused"}}
            config = uidw_mcp.uidw.default_config()
            with (
                mock.patch.object(uidw_mcp.uidw, "ensure_initialized", return_value=(initialization, paths, config)),
                mock.patch.object(uidw_mcp.uidw, "load_project_ir", return_value={"screens": []}),
            ):
                result = uidw_mcp.project_summary(str(root), root)

        self.assertTrue(result["setupRequired"])
        self.assertEqual(result["detailChoices"], ["low", "medium", "high"])
        self.assertIn("ui_configure", result["next"])

    def test_build_preview_returns_needs_setup_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {"config": root / "config.json", "ir": root / "ui-ir.json"}
            with (
                mock.patch.object(uidw_mcp.uidw, "state_paths", return_value=paths),
                mock.patch.object(uidw_mcp.uidw, "load_config", return_value=uidw_mcp.uidw.default_config()),
                mock.patch.object(uidw_mcp.uidw, "build_workbench") as renderer,
            ):
                result = uidw_mcp.build_preview(str(root), root, None, None, "quick")

        self.assertEqual(result["status"], "needs-setup")
        self.assertTrue(result["setupRequired"])
        renderer.assert_not_called()

    def test_build_preview_returns_actionable_fidelity_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ir_path = root / "ui-ir.json"
            paths = {"config": root / "config.json", "ir": ir_path}
            configured = uidw_mcp.uidw.default_config()
            configured[uidw_mcp.uidw.DETAIL_KEY] = "medium"
            with (
                mock.patch.object(uidw_mcp.uidw, "state_paths", return_value=paths),
                mock.patch.object(uidw_mcp.uidw, "load_config", return_value=configured),
                mock.patch.object(uidw_mcp, "_ir", return_value=(ir_path, {})),
                mock.patch.object(
                    uidw_mcp.uidw,
                    "build_workbench",
                    side_effect=ValueError("Preview blocked by fidelity audit: missing screen"),
                ) as renderer,
            ):
                result = uidw_mcp.build_preview(str(root), root, str(ir_path), None, "quick")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing screen", result["error"])
        self.assertTrue(renderer.call_args.args[4])

    @unittest.skipIf(importlib.util.find_spec("mcp") is not None, "MCP dependency is installed")
    def test_missing_optional_dependency_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "optional.*Install"):
                uidw_mcp.create_server(Path(directory))


if __name__ == "__main__":
    unittest.main()
