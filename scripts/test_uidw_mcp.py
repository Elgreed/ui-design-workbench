#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

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

    @unittest.skipIf(importlib.util.find_spec("mcp") is not None, "MCP dependency is installed")
    def test_missing_optional_dependency_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "optional.*Install"):
                uidw_mcp.create_server(Path(directory))


if __name__ == "__main__":
    unittest.main()
