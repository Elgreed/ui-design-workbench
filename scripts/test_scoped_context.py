#!/usr/bin/env python3
"""Tests for bounded agent context and sparse IR patches."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scoped_context import apply_patch, apply_patch_file, build_scoped_context, patch_template, validate_patch, write_json


def sample_ir() -> dict:
    return {
        "version": 1,
        "project": {"name": "Sample", "root": "/sample"},
        "platforms": ["web"],
        "screens": [
            {"id": "home", "name": "Home", "root": "home-root", "source": {"file": "Home.tsx"}},
            {"id": "settings", "name": "Settings", "root": "settings-root", "source": {"file": "Settings.tsx"}},
        ],
        "nodes": {
            "home-root": {"type": "container", "children": ["home-title"], "style": {"background": "$colors.surface"}},
            "home-title": {"type": "text", "text": "Home", "source": {"file": "Home.tsx"}},
            "settings-root": {"type": "container", "children": ["settings-title"]},
            "settings-title": {"type": "text", "text": "Settings", "source": {"file": "Settings.tsx"}},
        },
        "tokens": {"colors": {"surface": {"value": "$colors.base"}, "base": {"value": "#fff"}, "unused": {"value": "#f00"}}},
        "themes": {"defaultThemeId": "light", "items": [{"id": "light", "label": "Light", "kind": "light"}]},
        "review": {
            "revision": "review-1",
            "baselineHash": "sealed",
            "baselineVersion": "baseline",
            "audit": {"findings": [{"id": "finding-home", "title": "Issue", "screenId": "home", "nodeId": "home-title", "severity": "medium"}]},
            "versions": [],
        },
    }


class ScopedContextTests(unittest.TestCase):
    def test_screen_scope_keeps_complete_subtree_and_only_referenced_tokens(self) -> None:
        context = build_scoped_context(sample_ir(), screen_ids=["home"], token_budget=2000, ui_ir_file="ui-ir.json")
        self.assertEqual(set(context["nodes"]), {"home-root", "home-title"})
        self.assertNotIn("settings-root", context["nodes"])
        self.assertIn("surface", context["tokens"]["colors"])
        self.assertIn("base", context["tokens"]["colors"])
        self.assertNotIn("unused", context["tokens"]["colors"])
        self.assertFalse(context["contextBudget"]["structuralTruncation"])

    def test_empty_scope_returns_catalog_without_nodes(self) -> None:
        context = build_scoped_context(sample_ir(), token_budget=1000)
        self.assertEqual(context["nodes"], {})
        self.assertEqual([item["id"] for item in context["catalog"]["screens"]], ["home", "settings"])

    def test_sparse_patch_preserves_baseline_and_upserts_review_data(self) -> None:
        source = sample_ir()
        patch = patch_template(source, "ui-ir.json", "ui-agent-context.json")
        patch["operations"] = [
            {"op": "upsert-findings", "value": [{"id": "finding-new", "title": "New", "screenId": "home"}]},
            {"op": "upsert-versions", "value": [{"id": "proposal-a", "kind": "proposal", "nodeOverrides": {"home-title": {"text": "Improved"}}}]},
        ]
        result = apply_patch(source, patch)
        self.assertEqual(result["nodes"], source["nodes"])
        self.assertEqual(result["screens"], source["screens"])
        self.assertIn("finding-new", {item["id"] for item in result["review"]["audit"]["findings"]})
        self.assertEqual(result["review"]["versions"][0]["id"], "proposal-a")

    def test_patch_rejects_wrong_baseline_and_baseline_replacement(self) -> None:
        source = sample_ir()
        patch = patch_template(source, "ui-ir.json")
        patch["target"]["baselineHash"] = "other"
        patch["operations"] = [{"op": "upsert-versions", "value": [{"id": "bad", "kind": "proposal", "nodes": {}}]}]
        errors = validate_patch(source, patch)
        self.assertTrue(any("baselineHash" in item for item in errors))
        self.assertTrue(any("baseline" in item.lower() for item in errors))

    def test_apply_patch_file_reports_immutable_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ir_path, patch_path, output = root / "ui-ir.json", root / "ui-ir.patch.json", root / "ui-ir.patched.json"
            source = sample_ir()
            patch = patch_template(source, str(ir_path))
            patch["operations"] = [{"op": "merge-annotations", "value": [{"id": "a-1", "text": "Note"}]}]
            write_json(ir_path, source)
            write_json(patch_path, patch)
            report = apply_patch_file(ir_path, patch_path, output)
            self.assertTrue(report["baselineUnchanged"])
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
