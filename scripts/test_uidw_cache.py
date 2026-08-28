#!/usr/bin/env python3
"""Regression tests for the incremental project UI cache and source graph."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uidw


APP_ONE = """import React from 'react';
export function HomeScreen() { return <main><button onClick={() => navigate('/settings')}>Settings</button></main>; }
"""
APP_TWO = """import React from 'react';
export function SettingsScreen() { return <section><h1>Settings</h1></section>; }
"""


class IncrementalCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "sample-project"
        self.repo.mkdir()
        (self.repo / "HomeScreen.tsx").write_text(APP_ONE, encoding="utf-8")
        (self.repo / "SettingsScreen.tsx").write_text(APP_TWO, encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"UIDW_CACHE_HOME": str(self.base / "user-cache")})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_default_init_uses_user_cache_and_builds_graph(self) -> None:
        report = uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        self.assertEqual(report["status"], "synced")
        self.assertFalse(report["uiMode"]["enabled"])
        self.assertEqual(report["mockData"]["mode"], "minimal")
        self.assertTrue(report["mockData"]["enabled"])
        self.assertTrue(report["configuration"]["setupRequired"])
        self.assertFalse((self.repo / uidw.STATE_DIR_NAME).exists())
        self.assertTrue(paths["config"].is_file())
        self.assertTrue(paths["cache"].is_file())
        self.assertTrue(paths["graph"].is_file())
        graph = uidw.read_json(paths["graph"], {})
        self.assertEqual(graph["graphType"], "ui-source-map")
        self.assertGreaterEqual(graph["summary"]["screens"], 2)
        self.assertTrue(any(node["kind"] == "screen" for node in graph["nodes"]))
        self.assertEqual(uidw.inspect_cache(self.repo)[0]["status"], "clean")
        self.assertEqual(report["initialization"]["status"], "created")

    def test_lazy_initialization_creates_then_reuses_the_same_cache(self) -> None:
        created, paths, config = uidw.ensure_initialized(self.repo)

        self.assertEqual(created["status"], "synced")
        self.assertEqual(created["initialization"]["status"], "created")
        self.assertTrue(created["initialization"]["firstRun"])
        self.assertTrue(created["initialization"]["configCreated"])
        self.assertTrue(paths["config"].is_file())
        self.assertTrue(config["autoSync"])
        first_cache = uidw.read_json(paths["cache"], {})
        first_context = uidw.read_json(paths["context"], {})
        self.assertEqual(first_context["initialization"]["status"], "created")

        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            reused, reused_paths, _ = uidw.ensure_initialized(self.repo)

        analyze.assert_not_called()
        self.assertEqual(reused["status"], "clean")
        self.assertEqual(reused["initialization"]["status"], "reused")
        self.assertFalse(reused["initialization"]["firstRun"])
        self.assertTrue(reused["initialization"]["cacheReused"])
        self.assertTrue(reused["initialization"]["synchronizationChecked"])
        self.assertFalse(reused["initialization"]["sourceAnalysisRun"])
        self.assertEqual(uidw.read_json(reused_paths["cache"], {})["syncedAt"], first_cache["syncedAt"])
        self.assertEqual(uidw.read_json(reused_paths["context"], {})["initialization"]["status"], "reused")

    def test_lazy_initialization_respects_explicit_no_sync(self) -> None:
        result, paths, _ = uidw.ensure_initialized(self.repo, synchronize=False)

        self.assertEqual(result["initialization"]["status"], "stale")
        self.assertTrue(paths["config"].is_file())
        self.assertFalse(paths["cache"].exists())

    def test_lazy_initialization_reports_updated_after_a_ui_change(self) -> None:
        uidw.ensure_initialized(self.repo)
        (self.repo / "SettingsScreen.tsx").write_text(APP_TWO + "\nexport const revision = 2;\n", encoding="utf-8")

        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            updated, _, _ = uidw.ensure_initialized(self.repo)

        self.assertEqual(updated["initialization"]["status"], "updated")
        self.assertEqual(updated["changedUiFiles"], ["SettingsScreen.tsx"])
        self.assertEqual(analyze.call_count, 1)

    def test_cache_merge_prunes_only_missing_authored_token_values(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        generated = uidw.read_json(paths["ir"], {})
        root_id = generated["screens"][0]["root"]
        generated["tokens"] = {"colors": {"surface": {"value": "#ffffff"}}}
        generated["nodes"][root_id]["style"] = {"background": "$colors.surface"}
        design_model = uidw.extract_design_model(generated)
        design_model["tokens"] = {"colors": {}}
        design_model["nodes"][root_id]["style"] = {
            "background": "$colors.missing",
            "color": "$colors.surface",
        }

        merged = uidw.merge_authored_state(generated, design_model, uidw.extract_review_state(generated), [])

        self.assertEqual(merged["nodes"][root_id]["style"]["background"], "$colors.surface")
        self.assertEqual(merged["nodes"][root_id]["style"]["color"], "$colors.surface")
        self.assertIn("surface", merged["tokens"]["colors"])
        self.assertNotIn("$colors.missing", json.dumps(merged))

    def test_config_setup_is_persistent_agent_readable_and_does_not_rescan(self) -> None:
        uidw.initialize(self.repo)
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            uidw.configure_project(self.repo, "set", "detail", "high")
            result = uidw.configure_project(self.repo, "set", "ui-mode", "on")
        analyze.assert_not_called()
        self.assertEqual(result["status"], "configured")
        self.assertFalse(result["configuration"]["setupRequired"])
        self.assertEqual(result["configuration"]["detailLevel"], "high")
        self.assertTrue(result["configuration"]["uiMode"]["enabled"])
        self.assertEqual(result["configuration"]["mockData"]["mode"], "exhaustive")
        self.assertEqual(result["configuration"]["review"]["effective"]["validation"], "full")
        self.assertEqual(result["configuration"]["preview"]["effective"]["themeLayout"], "matrix")
        context = uidw.read_json(uidw.state_paths(self.repo)["context"], {})
        self.assertEqual(context["configuration"]["status"], "configured")

    def test_scanner_adds_only_source_evidenced_alternate_themes(self) -> None:
        plain = uidw.initialize(self.repo)
        plain_ir = uidw.read_json(uidw.state_paths(self.repo)["ir"], {})
        self.assertEqual([item["id"] for item in plain_ir["themes"]["items"]], ["light"])
        (self.repo / "theme.css").write_text(
            ":root { --surface: #fff; }\n@media (prefers-color-scheme: dark) { :root { --surface: #111; } }\n",
            encoding="utf-8",
        )
        uidw.sync_project(self.repo)
        themed_ir = uidw.read_json(uidw.state_paths(self.repo)["ir"], {})
        themes = {item["id"]: item for item in themed_ir["themes"]["items"]}
        self.assertEqual(set(themes), {"light", "dark"})
        self.assertTrue(themes["dark"]["sourceRefs"])

    def test_ui_mode_is_opt_in_and_does_not_rescan_clean_sources(self) -> None:
        uidw.initialize(self.repo)
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            enabled = uidw.configure_ui_mode(self.repo, True)
        self.assertEqual(enabled["status"], "enabled")
        self.assertTrue(enabled["uiMode"]["enabled"])
        analyze.assert_not_called()
        context = uidw.read_json(uidw.state_paths(self.repo)["context"], {})
        self.assertTrue(context["uiMode"]["enabled"])
        self.assertEqual(context["uiMode"]["scope"], "ui-related tasks only")

        disabled = uidw.configure_ui_mode(self.repo, False)
        self.assertEqual(disabled["status"], "disabled")
        context = uidw.read_json(uidw.state_paths(self.repo)["context"], {})
        self.assertEqual(context["uiMode"], {"enabled": False, "default": "off"})

    def test_setup_asks_only_for_detail_without_a_recommendation(self) -> None:
        context = uidw.configuration_context(uidw.default_config())
        self.assertEqual([item["key"] for item in context["questionsForUser"]], ["detail"])
        self.assertNotIn("recommended", context["questionsForUser"][0])
        self.assertIn("Low", context["questionsForUser"][0]["question"])
        self.assertIn("Medium", context["questionsForUser"][0]["question"])
        self.assertIn("High", context["questionsForUser"][0]["question"])

    def test_detail_prompt_has_no_default_choice(self) -> None:
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        with mock.patch.object(uidw.sys, "stdin", fake_stdin), mock.patch("builtins.input", return_value=""):
            self.assertIsNone(uidw.resolve_init_detail(None, False))
        with mock.patch.object(uidw.sys, "stdin", fake_stdin), mock.patch("builtins.input", return_value="m"):
            self.assertEqual(uidw.resolve_init_detail(None, False), "medium")

    def test_high_detail_derives_exhaustive_screen_specific_mock_data_without_rescan(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            uidw.configure_project(self.repo, "set", "detail", "high")
        analyze.assert_not_called()
        context = uidw.read_json(paths["context"], {})
        self.assertEqual(context["mockData"]["mode"], "exhaustive")
        self.assertEqual(context["mockData"]["source"], "detailLevel")
        self.assertIn("boundary states", context["mockData"]["instruction"])
        self.assertIn("repeated synthetic item nodes", context["mockData"]["instruction"])

    def test_mock_data_depth_follows_detail_level(self) -> None:
        for detail, expected in (("low", "minimal"), ("medium", "representative"), ("high", "exhaustive")):
            config = uidw.normalized_config({"detailLevel": detail})
            self.assertEqual(uidw.mock_data_context(config)["mode"], expected)
            self.assertTrue(uidw.mock_data_context(config)["enabled"])

    def test_clean_sync_reuses_every_per_file_record(self) -> None:
        uidw.initialize(self.repo)
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            report = uidw.sync_project(self.repo)
        self.assertEqual(report["status"], "clean")
        analyze.assert_not_called()

    def test_only_content_modified_file_is_analyzed_again(self) -> None:
        uidw.initialize(self.repo)
        changed = self.repo / "SettingsScreen.tsx"
        changed.write_text(APP_TWO + "\nexport const version = 2;\n", encoding="utf-8")
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            report = uidw.sync_project(self.repo)
        self.assertEqual(report["status"], "synced")
        self.assertEqual(report["changedUiFiles"], ["SettingsScreen.tsx"])
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(Path(analyze.call_args.args[1]).name, "SettingsScreen.tsx")

    def test_non_ui_source_change_does_not_invalidate_ui_cache(self) -> None:
        backend = self.repo / "worker.go"
        backend.write_text("package worker\nfunc Run() {}\n", encoding="utf-8")
        uidw.initialize(self.repo)
        backend.write_text("package worker\nfunc Run() { println(\"changed\") }\n", encoding="utf-8")

        status, _, _, _ = uidw.inspect_cache(self.repo)

        self.assertEqual(status["status"], "clean")
        self.assertEqual(status["changedUiFiles"], [])
        self.assertEqual(status["sourceChanges"]["modified"], ["worker.go"])
        synced = uidw.sync_project(self.repo)
        self.assertEqual(synced["status"], "clean")
        self.assertEqual(uidw.inspect_cache(self.repo)[0]["status"], "clean")

    def test_screen_context_is_bounded(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        ir = uidw.read_json(paths["ir"], {})
        screen_id = ir["screens"][0]["id"]
        output = uidw.write_screen_context(paths, screen_id)
        context = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(context["screen"]["id"], screen_id)
        self.assertIn(context["screen"]["root"], context["nodes"])
        self.assertEqual(context["uiGraphFile"], str(paths["graph"]))

    def test_new_screen_refreshes_derived_ir_and_graph(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        before = len(uidw.read_json(paths["ir"], {})["screens"])
        (self.repo / "BillingScreen.tsx").write_text(
            "import React from 'react'; export function BillingScreen(){ return <main>Billing</main>; }",
            encoding="utf-8",
        )
        report = uidw.sync_project(self.repo)
        after = len(uidw.read_json(paths["ir"], {})["screens"])
        graph = uidw.read_json(paths["graph"], {})
        self.assertEqual(report["status"], "synced")
        self.assertGreater(after, before)
        self.assertEqual(graph["summary"]["screens"], after)

    def test_project_cache_is_explicit_and_ignored(self) -> None:
        uidw.initialize(self.repo, project_cache=True)
        state_dir = self.repo / uidw.STATE_DIR_NAME
        config = uidw.read_json(state_dir / uidw.CONFIG_NAME, {})
        self.assertEqual(config["cacheMode"], "project")
        self.assertTrue((state_dir / ".gitignore").is_file())
        self.assertTrue((state_dir / uidw.GRAPH_NAME).is_file())

    def test_sync_preserves_authored_scenarios_and_marks_changed_binding_stale(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        ir = uidw.read_json(paths["ir"], {})
        screen = next(item for item in ir["screens"] if item.get("source", {}).get("file") == "SettingsScreen.tsx")
        screen["scenarios"] = [{"id": "populated", "label": "Populated", "fixtureRef": "settings-populated"}]
        screen["defaultScenarioId"] = "populated"
        ir["scenarioFixtures"] = {"settings-populated": {"synthetic": True, "seed": "stable", "nodeOverrides": {}}}
        uidw.write_json(paths["ir"], ir)
        (self.repo / "SettingsScreen.tsx").write_text(APP_TWO + "\nexport const changed = true;\n", encoding="utf-8")

        uidw.sync_project(self.repo)

        updated = uidw.read_json(paths["ir"], {})
        preserved = next(item for item in updated["screens"] if item["id"] == screen["id"])
        self.assertEqual(preserved["defaultScenarioId"], "populated")
        self.assertEqual(preserved["scenarios"][0]["fixtureRef"], "settings-populated")
        self.assertEqual(preserved["sourceState"], "stale")
        self.assertIn("settings-populated", updated["scenarioFixtures"])
        self.assertTrue(paths["design"].is_file())
        self.assertTrue(paths["review"].is_file())

    def test_context_budget_and_changed_only_are_materialized(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        output = uidw.write_context_variant(paths, token_budget=256, changed_only=True, output_format="markdown")
        self.assertTrue(output.is_file())
        text = output.read_text(encoding="utf-8")
        self.assertIn("UI Design Workbench context", text)
        self.assertIn("Estimated tokens", text)

    def test_detail_change_updates_mock_data_without_source_rescan(self) -> None:
        uidw.initialize(self.repo)
        with mock.patch.object(uidw, "analyze_file", wraps=uidw.analyze_file) as analyze:
            high = uidw.configure_project(self.repo, "set", "detail", "high")
            medium = uidw.configure_project(self.repo, "set", "detail", "medium")
        analyze.assert_not_called()
        self.assertEqual(high["configuration"]["mockData"]["mode"], "exhaustive")
        self.assertEqual(medium["configuration"]["mockData"]["mode"], "representative")

    def test_config_migration_is_atomic_and_keeps_a_backup(self) -> None:
        path = self.base / "legacy" / "config.json"
        uidw.write_json(path, {"version": 1, "autoSync": False})
        migrated = uidw.load_config(path)
        self.assertEqual(migrated["version"], uidw.CONFIG_VERSION)
        self.assertEqual(uidw.read_json(path, {})["version"], uidw.CONFIG_VERSION)
        self.assertEqual(uidw.read_json(path.with_name("config.v1.backup.json"), {})["version"], 1)

    def test_legacy_mock_preference_migrates_to_detail_derived_mode(self) -> None:
        path = self.base / "legacy-derived" / "config.json"
        uidw.write_json(path, {
            "version": 3,
            "detailLevel": "medium",
            "setup": {"completed": True, "answered": ["detail", "ui-mode", "mock-data"]},
            "mockData": {"mode": "exhaustive", "seed": "custom", "explicit": True},
        })
        migrated = uidw.load_config(path)
        self.assertEqual(migrated["mockData"], {"mode": "representative", "seed": "stable", "explicit": False})
        self.assertEqual(migrated["setup"], {"completed": True, "answered": ["detail"]})
        self.assertTrue(path.with_name("config.v3.backup.json").is_file())

    def test_findings_decisions_and_agent_jobs_use_stable_numbers(self) -> None:
        uidw.initialize(self.repo)
        paths = uidw.state_paths(self.repo)
        ir = uidw.read_json(paths["ir"], {})
        screen = ir["screens"][0]
        source_file = screen["source"]["file"]
        ir["review"]["audit"] = {
            "findings": [{
                "id": "finding-a",
                "title": "Example",
                "severity": "high",
                "screenId": screen["id"],
                "status": "open",
                "sourceTarget": source_file,
            }]
        }
        update = uidw.update_finding_decisions(ir, ["1"], "accepted")
        self.assertEqual(update["findingIds"], ["finding-a"])
        ir_path = self.base / "review" / "ui-ir.json"
        uidw.write_json(ir_path, ir)
        proposal = uidw.prepare_agent_job(self.repo, ir_path, ir, "proposal", ir_path.parent / "proposal.json")
        implementation = uidw.prepare_agent_job(
            self.repo,
            ir_path,
            ir,
            "implementation",
            ir_path.parent / "implementation.json",
            direct=True,
        )
        self.assertEqual(proposal["findingIds"], ["finding-a"])
        self.assertEqual(implementation["sourceTargets"], [source_file])
        self.assertFalse(uidw.read_json(ir_path.parent / "proposal.json", {})["sourceChangeAllowed"])
        self.assertTrue(uidw.read_json(ir_path.parent / "implementation.json", {})["sourceChangeAllowed"])
        self.assertTrue(uidw.read_json(ir_path.parent / "implementation.json", {})["directSourceAuthorization"])

    def test_mock_scenario_requires_repeated_collection_items(self) -> None:
        ir = {
            "nodes": {
                "root": {"type": "container", "children": ["results"]},
                "results": {
                    "type": "list",
                    "dataDriven": True,
                    "collection": {"minMockItems": 2},
                    "children": ["empty"],
                },
                "empty": {"type": "text", "text": "No results", "emptyState": True},
                "item-1": {"type": "container", "children": [], "mockOnly": True},
                "item-2": {"type": "container", "children": [], "mockOnly": True},
            },
            "screens": [{
                "id": "results-screen",
                "name": "Results",
                "root": "root",
                "defaultScenarioId": "mock-data",
                "scenarios": [{"id": "mock-data", "label": "Mock data", "nodeOverrides": {}}],
            }],
        }

        empty_report = uidw.scenario_report(ir)
        self.assertEqual(empty_report["status"], "fail")
        self.assertEqual(empty_report["issues"][0]["code"], "mock-collection-empty")

        ir["screens"][0]["scenarios"][0]["nodeOverrides"] = {
            "results": {"children": ["item-1", "item-2"]}
        }
        populated_report = uidw.scenario_report(ir)
        self.assertEqual(populated_report["status"], "pass")
        self.assertEqual(
            populated_report["screens"][0]["scenarios"][0]["collectionCounts"]["results"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
