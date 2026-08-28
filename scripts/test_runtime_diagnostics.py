#!/usr/bin/env python3
"""Regression coverage for runtime interactivity and navigation diagnostics."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from render_preview import render_html


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
    def test_renderer_omits_empty_action_provenance(self) -> None:
        html = render_html(regression_ir())
        self.assertNotIn('data-action="${esc(action.type||\'\')}"', html)
        self.assertIn("actionAttrs=actionType?", html)
        self.assertIn("semanticRole", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the headless runtime regression")
    def test_ppr_static_nodes_are_filtered_but_real_controls_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            preview = artifact_dir / "ui-preview.html"
            report_path = artifact_dir / "diagnostics.json"
            preview.write_text(render_html(regression_ir(), artifact_dir), encoding="utf-8")
            completed = subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts" / "smoke_preview.js"),
                    str(preview),
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
            self.assertEqual(completed.returncode, 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
            report = json.loads(report_path.read_text(encoding="utf-8"))

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
        self.assertEqual(len(untabbable), 2)


if __name__ == "__main__":
    unittest.main()
