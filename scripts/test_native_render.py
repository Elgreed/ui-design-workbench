#!/usr/bin/env python3
"""Regression tests for opt-in native-render discovery and state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fidelity_adapters import adapter_capabilities
from native_render_android import discover_android
from native_render_apple import discover_apple
from native_render_contracts import NativeRenderRequest, validate_native_state, write_native_state
from native_render_registry import native_render_status
from render_preview import fidelity_audit, render_html


ROOT = Path(__file__).resolve().parent.parent


def android_fixture(root: Path) -> Path:
    (root / "settings.gradle.kts").write_text('include(":app", ":feature:home")\n', encoding="utf-8")
    (root / "gradlew.bat").write_text("@echo off\n", encoding="utf-8")
    app = root / "app"
    (app / "src" / "main" / "java" / "sample").mkdir(parents=True)
    (app / "src" / "main" / "res" / "layout").mkdir(parents=True)
    (app / "src" / "main" / "AndroidManifest.xml").write_text("<manifest />\n", encoding="utf-8")
    (app / "src" / "main" / "res" / "layout" / "home.xml").write_text("<LinearLayout />\n", encoding="utf-8")
    (app / "build.gradle.kts").write_text(
        'plugins { id("com.android.application"); id("com.android.compose.screenshot") }\n'
        'dependencies { testImplementation("app.cash.paparazzi:paparazzi:1.3.5") }\n',
        encoding="utf-8",
    )
    source = app / "src" / "main" / "java" / "sample" / "Home.kt"
    source.write_text(
        "@Composable fun Home() = Text(\"Home\")\n@Preview @Composable fun HomePreview() = Home()\n",
        encoding="utf-8",
    )
    return source


class NativeRenderTests(unittest.TestCase):
    def test_android_discovery_finds_modules_entrypoints_and_existing_providers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            android_fixture(root)
            result = discover_android(root)

        providers = {item["id"]: item for item in result["providers"]}
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["project"]["modules"], [":app", ":feature:home"])
        self.assertEqual(result["project"]["previewEntryCount"], 1)
        self.assertEqual(result["project"]["layoutResourceCount"], 1)
        self.assertEqual(providers["android-compose-screenshot"]["status"], "configured")
        self.assertEqual(providers["paparazzi"]["status"], "configured")
        self.assertFalse(result["nativeExecutionStarted"])
        self.assertEqual(result["currentFidelityTier"], "structural")

    def test_apple_discovery_requires_a_macos_worker_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.xcodeproj").mkdir()
            (root / "Home.swift").write_text(
                "import SwiftUI\nstruct Home: View { var body: some View { Text(\"Home\") } }\n#Preview { Home() }\n",
                encoding="utf-8",
            )
            result = discover_apple(root, host_platform="win32")

        self.assertEqual(result["status"], "detected")
        self.assertTrue(result["project"]["requiresMacOSWorker"])
        self.assertEqual(result["project"]["previewEntryCount"], 1)
        self.assertTrue(all(item["status"] == "host-required" for item in result["providers"]))
        self.assertFalse(result["nativeExecutionStarted"])

    def test_native_status_is_cached_and_invalidates_capture_on_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = android_fixture(root)
            state_file = root / "cache" / "native-render-state.json"
            first = native_render_status(root, state_file, "android")
            second = native_render_status(root, state_file, "android")
            self.assertEqual(first["cache"]["status"], "created")
            self.assertEqual(second["cache"]["status"], "reused")
            state = json.loads(state_file.read_text(encoding="utf-8"))
            fingerprint = next(item["sourceFingerprint"] for item in state["platforms"] if item["platform"] == "android")
            state["captures"] = [{
                "id": "home-default",
                "providerId": "paparazzi",
                "platform": "android",
                "screenId": "home",
                "stateId": "default",
                "sourceFingerprint": fingerprint,
                "status": "ready",
                "fidelityTier": "native-preview",
                "artifacts": {"image": "captures/home.png"},
            }]
            write_native_state(state_file, state)
            source.write_text(source.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
            changed = native_render_status(root, state_file, "android")

        self.assertEqual(changed["captures"][0]["status"], "stale")
        self.assertEqual(changed["summary"]["staleCaptureCount"], 1)

    def test_contract_rejects_absolute_artifacts_and_cache_key_is_deterministic(self) -> None:
        request = NativeRenderRequest("paparazzi", "android", "home", viewport={"width": 360, "height": 800})
        self.assertEqual(request.cache_key("source-1", "1"), request.cache_key("source-1", "1"))
        state = {
            "schemaVersion": 1,
            "type": "ui-design-workbench-native-render-state",
            "repository": {"root": "repo"},
            "status": "pass",
            "currentFidelityTier": "native-preview",
            "nativeExecutionStarted": True,
            "platforms": [],
            "providers": [],
            "captures": [{
                "id": "home", "providerId": "paparazzi", "platform": "android", "screenId": "home",
                "sourceFingerprint": "source-1", "status": "ready", "fidelityTier": "native-preview",
                "artifacts": {"image": "C:/private/home.png"},
            }],
        }
        self.assertTrue(any("must be relative" in error for error in validate_native_state(state)))

    def test_source_adapters_require_native_evidence_for_visual_verification(self) -> None:
        capabilities = {item["id"]: item for item in adapter_capabilities()}
        for adapter_id in ("compose", "android-xml", "swiftui", "apple-interface-xml", "flutter"):
            self.assertEqual(capabilities[adapter_id]["maturity"], "structural")
            self.assertEqual(capabilities[adapter_id]["visualTier"], "deterministic-projection")
            self.assertTrue(capabilities[adapter_id]["nativeEvidenceRequired"])
            self.assertTrue(capabilities[adapter_id]["nativeProviders"])

    def test_mobile_html_marks_runtime_free_projection_as_not_native_verified(self) -> None:
        ir = {
            "project": {"name": "Mobile"},
            "platforms": ["android"],
            "design": {"mode": "reconstruct", "targetPlatforms": ["android"]},
            "fidelity": {"status": "translated", "sourceDerived": True},
            "screens": [{"id": "home", "name": "Home", "root": "root", "platform": "android"}],
            "nodes": {"root": {"type": "container", "children": []}},
        }
        audit = fidelity_audit(ir)
        ir["fidelityAudit"] = audit
        preview = render_html(ir)

        self.assertTrue(audit["nativeEvidenceRequired"])
        self.assertEqual(audit["visualFidelityTier"], "structural-projection")
        self.assertTrue(audit["runtimeFree"])
        self.assertFalse(audit["nativeExecutionStarted"])
        self.assertIn("Нативный снимок:</span>", preview)
        self.assertIn("визуальная точность не подтверждена", preview)
        self.assertIn("deterministic-box-v2", preview)

    def test_partial_projection_remains_explicit_fidelity_gap(self) -> None:
        ir = {
            "project": {"name": "Partial mobile"},
            "platforms": ["android"],
            "design": {"mode": "reconstruct", "targetPlatforms": ["android"]},
            "fidelity": {"status": "translated", "sourceDerived": True},
            "screens": [{"id": "home", "name": "Home", "root": "root", "platform": "android"}],
            "nodes": {
                "root": {"type": "container", "children": ["title"], "layout": {"direction": "grid"}},
                "title": {"type": "text", "text": "Home", "layout": {"width": 100, "height": 24}},
            },
        }

        audit = fidelity_audit(ir)
        ir["fidelityAudit"] = audit
        preview = render_html(ir)

        self.assertTrue(audit["nativeEvidenceRequired"])
        self.assertEqual(audit["nativeEvidenceCoverage"], 0)
        self.assertEqual(audit["visualFidelityTier"], "structural-projection")
        self.assertEqual(audit["projectionCoverage"], 0)
        self.assertTrue(audit["projectionGaps"])
        self.assertIn('"status":"partial"', preview)
        self.assertIn("context?.status==='solved'?context:null", preview)

    def test_web_partial_projection_cannot_claim_deterministic_fidelity(self) -> None:
        ir = {
            "project": {"name": "Partial web"},
            "platforms": ["web"],
            "design": {"mode": "reconstruct", "targetPlatforms": ["web"]},
            "fidelity": {"status": "translated", "sourceDerived": True},
            "screens": [{"id": "home", "name": "Home", "root": "root", "platform": "web"}],
            "nodes": {
                "root": {"type": "container", "children": ["title"], "layout": {"direction": "grid"}},
                "title": {"type": "text", "text": "Home", "layout": {"width": 100, "height": 24}},
            },
        }

        audit = fidelity_audit(ir)

        self.assertFalse(audit["nativeEvidenceRequired"])
        self.assertEqual(audit["visualFidelityTier"], "structural-projection")
        self.assertEqual(audit["projectionCoverage"], 0)
        self.assertTrue(any("projection is incomplete" in reason for reason in audit["reasons"]))

    def test_cli_native_status_does_not_initialize_or_execute_a_native_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample"
            root.mkdir()
            android_fixture(root)
            env = {**os.environ, "UIDW_CACHE_HOME": str(Path(directory) / "cache")}
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "uidw.py"), "--repo", str(root), "--json", "native", "status", "--platform", "android"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["nativeExecutionStarted"])
        self.assertEqual(result["summary"]["detectedPlatforms"], ["android"])


if __name__ == "__main__":
    unittest.main()
