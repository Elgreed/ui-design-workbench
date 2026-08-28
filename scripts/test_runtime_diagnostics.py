#!/usr/bin/env python3
"""Regression coverage for runtime interactivity and navigation diagnostics."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from render_preview import render_html, validate


ROOT = Path(__file__).resolve().parent.parent


def regression_ir() -> dict:
    """Small reproduction derived from the ppr-admin review's two-route graph."""

    def source(line: int) -> dict:
        return {"file": "internal/httpserver/review.html", "line": line, "symbol": f"Node{line}"}

    nodes: dict[str, dict] = {}

    def add_screen(prefix: str, target: str, *, real_issues: bool = False) -> str:
        root = f"{prefix}-root"
        children = [f"{prefix}-nav", f"{prefix}-title", f"{prefix}-status"]
        if real_issues:
            children += [f"{prefix}-small-button", f"{prefix}-custom-action"]
        nodes[root] = {
            "type": "container",
            "children": children,
            "layout": {"direction": "column", "gap": 8, "width": "fill", "height": "fill", "padding": 16},
            "style": {"background": "#ffffff", "color": "#111827"},
            "action": {},
            "source": source(1),
        }
        nodes[f"{prefix}-nav"] = {
            "type": "button",
            "text": "Открыть раздел",
            "action": {"type": "navigate", "target": target},
            "layout": {"width": 160, "height": 40},
            "style": {"background": "#111827", "color": "#ffffff"},
            "source": source(2),
        }
        nodes[f"{prefix}-title"] = {
            "type": "text",
            "text": "Статический заголовок",
            "layout": {"height": 18},
            "style": {"color": "#111827", "fontSize": 14},
            "action": {},
            "source": source(3),
        }
        nodes[f"{prefix}-status"] = {
            "type": "text",
            "text": "Статический статус",
            "layout": {"height": 18},
            "style": {"color": "#111827", "fontSize": 14},
            "source": source(4),
        }
        if real_issues:
            nodes[f"{prefix}-small-button"] = {
                "type": "button",
                "text": "X",
                "layout": {"width": 20, "height": 20},
                "style": {"background": "#111827", "color": "#ffffff"},
                "source": source(5),
            }
            nodes[f"{prefix}-custom-action"] = {
                "type": "container",
                "text": "Кастомное действие",
                "action": {"type": "navigate", "target": target},
                "semantics": {"role": "button", "label": "Кастомное действие"},
                "layout": {"width": 180, "height": 40},
                "style": {"background": "#e5e7eb", "color": "#111827"},
                "source": source(6),
            }
        return root

    screens = [
        {"id": "cabinet-home", "name": "Кабинет", "route": "/cabinet", "root": add_screen("cabinet-home", "cabinet-settings"), "scenarios": [{"id": "populated", "label": "Данные"}]},
        {"id": "cabinet-settings", "name": "Настройки", "route": "/cabinet", "root": add_screen("cabinet-settings", "cabinet-home")},
        {"id": "admin-home", "name": "Админка", "route": "/admin", "root": add_screen("admin-home", "admin-jobs", real_issues=True), "scenarios": [{"id": "populated", "label": "Данные"}]},
        {"id": "admin-jobs", "name": "Задачи", "route": "/admin", "root": add_screen("admin-jobs", "admin-home")},
    ]
    return {
        "version": 1,
        "project": {"name": "ppr-admin-runtime-regression"},
        "platforms": ["web"],
        "design": {"mode": "reconstruct", "targetPlatforms": ["web"]},
        "themes": {
            "defaultThemeId": "light",
            "items": [
                {"id": "light", "label": "Light", "kind": "light", "sourceRefs": [], "tokenOverrides": {}, "nodeOverrides": {}},
                {"id": "dark", "label": "Dark", "kind": "dark", "sourceRefs": [{"file": "theme.css", "line": 2, "evidence": "dark"}], "tokenOverrides": {}, "nodeOverrides": {}},
            ],
        },
        "viewport": {"width": 720, "height": 520, "device": "desktop"},
        "screens": screens,
        "nodes": nodes,
        "review": {
            "revision": "ppr-admin-runtime-regression-v1",
            "versions": [{"id": "baseline", "label": "Before", "kind": "baseline", "status": "approved", "nodeOverrides": {}}],
            "baselineVersion": "baseline",
            "activeVersion": "baseline",
            "diagnostics": {
                "profiles": [
                    {"id": "desktop", "label": "Desktop", "viewport": {"width": 1000, "height": 760}, "zoomLevels": [1]},
                    {"id": "compact", "label": "Compact", "viewport": {"width": 760, "height": 700}, "zoomLevels": [1]},
                ],
                "scenarios": [
                    {"id": "layout-integrity", "label": "Layout integrity", "kind": "layout-integrity"},
                    {"id": "accessibility-basics", "label": "Accessibility basics", "kind": "accessibility-basics"},
                    {"id": "state-matrix", "label": "Component states", "kind": "state-matrix"},
                    {"id": "navigation-flow", "label": "Navigation flow", "kind": "navigation-flow"},
                    {"id": "contrast-focus", "label": "Contrast and keyboard", "kind": "contrast-focus"},
                ],
            },
        },
    }


class RuntimeDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def _run_runtime(ir: dict, mode: str = "review") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            preview = artifact_dir / "ui-preview.html"
            report_path = artifact_dir / "diagnostics.json"
            preview.write_text(render_html(ir, artifact_dir), encoding="utf-8")
            completed = subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts" / "smoke_preview.js"),
                    str(preview),
                    "--mode",
                    mode,
                    "--output",
                    str(report_path),
                    "--viewport-width",
                    "1000",
                    "--viewport-height",
                    "760",
                ],
                check=False,
                timeout=120,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if completed.returncode != 0:
                raise AssertionError(f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
            return json.loads(report_path.read_text(encoding="utf-8"))

    def test_renderer_omits_empty_action_provenance(self) -> None:
        html = render_html(regression_ir())
        self.assertNotIn('data-action="${esc(action.type||\'\')}"', html)
        self.assertIn("actionAttrs=actionType?", html)
        self.assertIn('data-interactive="${interaction.interactive}"', html)
        self.assertIn("nodeInteraction(node)", html)

    def test_renderer_exposes_source_evidenced_theme_and_variant_axes(self) -> None:
        ir = regression_ir()
        ir["themes"] = {
            "defaultThemeId": "light",
            "items": [
                {"id": "light", "label": "Light", "kind": "light", "sourceRefs": [], "tokenOverrides": {}, "nodeOverrides": {}},
                {"id": "dark", "label": "Dark", "kind": "dark", "sourceRefs": [{"file": "theme.css", "line": 2, "evidence": "dark"}], "tokenOverrides": {"colors": {"surface": "#111111"}}, "nodeOverrides": {}},
            ],
        }
        html = render_html(ir)
        self.assertIn("data-screen-theme", html)
        self.assertIn("data-gallery-theme", html)
        self.assertIn("data-gallery-scenario", html)
        self.assertIn("screen-state-select", html)
        self.assertIn("data-variant-axis", html)
        self.assertIn("axisFromLocation", html)
        self.assertIn("data-theme-id", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_ppr_static_nodes_are_filtered_but_real_controls_still_fail(self) -> None:
        report = self._run_runtime(regression_ir())

        navigation = next(item for item in report["checks"] if item["scenarioId"] == "navigation-flow")
        self.assertEqual(navigation["result"], "pass")
        self.assertEqual({flow["flowId"] for flow in navigation["metrics"]["flows"]}, {"/cabinet", "/admin"})

        encoded_metrics = json.dumps([item.get("metrics", {}) for item in report["checks"]], ensure_ascii=False)
        for static_id in ("cabinet-home-root", "cabinet-home-title", "cabinet-home-status"):
            self.assertNotIn(static_id, encoded_metrics)

        layout_targets = [
            node_id
            for item in report["checks"]
            if item["scenarioId"] in {"layout-integrity", "state-matrix"}
            for node_id in item.get("metrics", {}).get("smallTargets", [])
        ]
        self.assertIn("admin-home-small-button", layout_targets)

        untabbable = [
            node_id
            for item in report["checks"]
            if item["scenarioId"] == "contrast-focus"
            for node_id in item.get("metrics", {}).get("untabbable", [])
        ]
        self.assertEqual(set(untabbable), {"admin-home-custom-action"})
        self.assertEqual(len(untabbable), 4)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_navigation_reachability_uses_compiled_graph_entries(self) -> None:
        ir = regression_ir()
        ir["navigationGraph"] = {
            "version": 1,
            "source": "scan-evidence",
            "nodes": [
                {"screenId": screen["id"], "flowId": screen["route"], "entry": screen["id"].endswith("home")}
                for screen in ir["screens"]
            ],
            "edges": [
                {"from": "cabinet-home", "to": "cabinet-settings", "kind": "open-logical-view"},
                {"from": "cabinet-settings", "to": "cabinet-home", "kind": "return-to-parent"},
                {"from": "admin-home", "to": "admin-jobs", "kind": "open-logical-view"},
                {"from": "admin-jobs", "to": "admin-home", "kind": "return-to-parent"},
            ],
            "flows": [
                {"id": "/cabinet", "screenIds": ["cabinet-home", "cabinet-settings"], "entryScreenIds": ["cabinet-home"]},
                {"id": "/admin", "screenIds": ["admin-home", "admin-jobs"], "entryScreenIds": ["admin-home"]},
            ],
            "navigationTargets": [],
            "unresolvedTargets": [],
        }

        report = self._run_runtime(ir)
        navigation = next(item for item in report["checks"] if item["scenarioId"] == "navigation-flow")

        self.assertEqual(navigation["result"], "pass")
        self.assertEqual(navigation["metrics"]["graphSource"], "navigationGraph")
        self.assertEqual(navigation["metrics"]["assessedFlows"], 2)
        self.assertEqual(navigation["metrics"]["unreachable"], [])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_zero_runtime_findings_is_a_successful_smoke_result(self) -> None:
        ir = regression_ir()
        root_children = ir["nodes"]["admin-home-root"]["children"]
        root_children.remove("admin-home-small-button")
        root_children.remove("admin-home-custom-action")
        del ir["nodes"]["admin-home-small-button"]
        del ir["nodes"]["admin-home-custom-action"]
        for node_id, node in ir["nodes"].items():
            if node_id.endswith("-nav"):
                node["layout"].update({"width": 260, "height": 44})

        report = self._run_runtime(ir)

        self.assertEqual(report["summary"]["productFail"], 0)
        self.assertEqual(report["summary"]["productWarning"], 0)
        self.assertEqual(report["summary"]["toolFail"], 1)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_projection_mode_checks_transfer_without_ui_audit(self) -> None:
        ir = regression_ir()
        ir["themes"] = {
            "defaultThemeId": "light",
            "items": [
                {"id": "light", "label": "Light", "kind": "light", "sourceRefs": [], "tokenOverrides": {}, "nodeOverrides": {}},
                {"id": "dark", "label": "Dark", "kind": "dark", "sourceRefs": [{"file": "theme.css", "line": 2, "evidence": "dark"}], "tokenOverrides": {"colors": {"surface": "#111111"}}, "nodeOverrides": {}},
            ],
        }
        report = self._run_runtime(ir, "projection")
        self.assertEqual(report["mode"], "projection")
        scenario_ids = {item["scenarioId"] for item in report["checks"]}
        self.assertIn("screen-render", scenario_ids)
        self.assertIn("navigation-flow", scenario_ids)
        self.assertNotIn("layout-integrity", scenario_ids)
        self.assertNotIn("accessibility-basics", scenario_ids)
        self.assertNotIn("contrast-focus", scenario_ids)
        self.assertFalse(any("smallTargets" in item.get("metrics", {}) for item in report["checks"]))
        self.assertFalse(any("lowContrast" in item.get("metrics", {}) for item in report["checks"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_navigation_warns_only_when_an_explicit_entry_cannot_reach_a_screen(self) -> None:
        ir = regression_ir()
        navigation = next(item for item in ir["review"]["diagnostics"]["scenarios"] if item["id"] == "navigation-flow")
        navigation["entryScreenIds"] = ["cabinet-home"]
        ir["nodes"]["cabinet-home-nav"]["action"]["target"] = "cabinet-home"

        report = self._run_runtime(ir)
        check = next(item for item in report["checks"] if item["scenarioId"] == "navigation-flow")
        self.assertEqual(check["result"], "warning")
        self.assertIn("cabinet-settings", check["metrics"]["unreachable"])
        cabinet_flow = next(item for item in check["metrics"]["flows"] if item["flowId"] == "/cabinet")
        self.assertTrue(cabinet_flow["reachabilityAssessed"])
        self.assertEqual(cabinet_flow["entryScreenIds"], ["cabinet-home"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_navigation_keeps_explicit_flows_independent_even_on_one_route(self) -> None:
        ir = regression_ir()
        for screen in ir["screens"]:
            screen["route"] = "/shared"
            screen["navigationFlowId"] = "cabinet" if screen["id"].startswith("cabinet-") else "admin"
        ir["screens"][0]["navigationEntry"] = True
        ir["screens"][2]["navigationEntry"] = True
        ir["nodes"]["admin-home-nav"]["action"]["target"] = "admin-home"
        ir["nodes"]["admin-home-custom-action"]["action"]["target"] = "admin-home"

        report = self._run_runtime(ir)
        check = next(item for item in report["checks"] if item["scenarioId"] == "navigation-flow")
        self.assertEqual(check["result"], "warning")
        self.assertEqual(check["metrics"]["unreachable"], ["admin-jobs"])
        self.assertEqual({flow["flowId"] for flow in check["metrics"]["flows"]}, {"cabinet", "admin"})
        cabinet = next(flow for flow in check["metrics"]["flows"] if flow["flowId"] == "cabinet")
        self.assertEqual(cabinet["unreachable"], [])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_multiple_entries_make_independent_subflows_reachable(self) -> None:
        ir = regression_ir()
        navigation = next(item for item in ir["review"]["diagnostics"]["scenarios"] if item["id"] == "navigation-flow")
        navigation["entryScreenIds"] = ["cabinet-home", "cabinet-settings", "admin-home", "admin-jobs"]
        for node_id in ("cabinet-home-nav", "cabinet-settings-nav", "admin-home-nav", "admin-jobs-nav"):
            ir["nodes"][node_id]["action"]["target"] = node_id.removesuffix("-nav")

        report = self._run_runtime(ir)
        check = next(item for item in report["checks"] if item["scenarioId"] == "navigation-flow")
        self.assertEqual(check["result"], "pass")
        self.assertEqual(check["metrics"]["unreachable"], [])
        self.assertEqual(check["metrics"]["assessedFlows"], 2)

    def test_navigation_and_state_contracts_are_validated_before_render(self) -> None:
        ir = regression_ir()
        navigation = next(item for item in ir["review"]["diagnostics"]["scenarios"] if item["id"] == "navigation-flow")
        navigation["entryScreenIds"] = ["missing-screen", "missing-screen"]
        ir["screens"][0]["navigationFlowId"] = "   "
        ir["nodes"]["cabinet-home-title"]["action"] = {"type": "toggle", "target": "cabinet-home-status"}
        errors = validate(ir)
        self.assertTrue(any("entryScreenIds must be a unique array" in error for error in errors))
        self.assertTrue(any("navigationFlowId must be a non-empty string" in error for error in errors))
        self.assertTrue(any("requires state" in error for error in errors))

    def test_screen_tree_rejects_flattened_source_hierarchy(self) -> None:
        ir = regression_ir()
        for screen in ir["screens"]:
            screen["source"] = {"file": "review.html", "line": 1, "symbol": screen["id"]}
            screen["fragment"] = f"#{screen['id']}"
        ir["discoveredScreens"] = [
            {"name": "admin-home", "file": "review.html", "fragment": "#admin-home", "groupPath": ["Admin"]},
            {"name": "admin-jobs", "file": "review.html", "fragment": "#admin-jobs", "groupPath": ["Admin", "Jobs"], "parentFragment": "#admin-home"},
            {"name": "cabinet-home", "file": "review.html", "fragment": "#cabinet-home", "groupPath": ["Cabinet"]},
            {"name": "cabinet-settings", "file": "review.html", "fragment": "#cabinet-settings", "groupPath": ["Cabinet"]},
        ]
        ir["navigationGraph"] = {
            "version": 1,
            "source": "scan-evidence",
            "nodes": [{"screenId": screen["id"]} for screen in ir["screens"]],
            "edges": [{"from": "admin-home", "to": "admin-jobs", "kind": "open-logical-view"}],
            "flows": [], "navigationTargets": [], "unresolvedTargets": [],
        }
        ir["screenTree"] = [{
            "id": "all",
            "label": "All",
            "children": [{"screenId": screen["id"], "label": screen["name"]} for screen in ir["screens"]],
        }]

        errors = validate(ir)

        self.assertTrue(any("does not preserve source groups" in error for error in errors))
        self.assertTrue(any("flattens nested screen admin-jobs" in error for error in errors))

    def test_screen_tree_accepts_compiled_nested_hierarchy(self) -> None:
        ir = regression_ir()
        for screen in ir["screens"]:
            screen["source"] = {"file": "review.html", "line": 1, "symbol": screen["id"]}
            screen["fragment"] = f"#{screen['id']}"
        ir["discoveredScreens"] = [
            {"name": "admin-home", "file": "review.html", "fragment": "#admin-home", "groupPath": ["Admin"]},
            {"name": "admin-jobs", "file": "review.html", "fragment": "#admin-jobs", "groupPath": ["Admin", "Jobs"], "parentFragment": "#admin-home"},
            {"name": "cabinet-home", "file": "review.html", "fragment": "#cabinet-home", "groupPath": ["Cabinet"]},
            {"name": "cabinet-settings", "file": "review.html", "fragment": "#cabinet-settings", "groupPath": ["Cabinet"]},
        ]
        ir["navigationGraph"] = {
            "version": 1,
            "source": "scan-evidence",
            "nodes": [{"screenId": screen["id"]} for screen in ir["screens"]],
            "edges": [{"from": "admin-home", "to": "admin-jobs", "kind": "open-logical-view"}],
            "flows": [], "navigationTargets": [], "unresolvedTargets": [],
        }
        ir["screenTree"] = [
            {"id": "cabinet", "label": "Cabinet", "children": [
                {"screenId": "cabinet-home"}, {"screenId": "cabinet-settings"},
            ]},
            {"id": "admin", "label": "Admin", "children": [
                {"screenId": "admin-home"},
                {"id": "jobs", "label": "Jobs", "children": [{"screenId": "admin-jobs"}]},
            ]},
        ]

        errors = validate(ir)

        self.assertFalse(any("screenTree path" in error or "flattens nested screen" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
