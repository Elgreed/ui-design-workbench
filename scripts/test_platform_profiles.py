#!/usr/bin/env python3
"""Regression tests for platform discovery and standards-profile resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quality_common import framework_adapters, platform_family, profile_catalog
from scan_ui import detect_platforms, scan, starter_ir
from validate_platform_profiles import validate_profiles


PLATFORM_CASES = (
    {
        "family": "windows",
        "adapter": "windows-winui",
        "profile": "windows-fluent",
        "standardRef": "windows.NavigationView",
        "path": Path("MainWindow.xaml"),
        "source": '<Window x:Class="Sample.MainWindow" xmlns:muxc="using:Microsoft.UI.Xaml.Controls"><muxc:NavigationView /></Window>',
    },
    {
        "family": "macos",
        "adapter": "swiftui-macos",
        "profile": "macos-hig",
        "standardRef": "macos.WindowToolbar",
        "path": Path("WorkspaceView.swift"),
        "source": "import SwiftUI\nimport AppKit\nstruct WorkspaceView: View { var body: some View { Text(\"Workspace\") } }",
    },
    {
        "family": "android-tv",
        "adapter": "android-tv-compose",
        "profile": "android-tv",
        "standardRef": "androidtv.Card",
        "path": Path("TvHomeScreen.kt"),
        "source": "import androidx.compose.runtime.Composable\nimport androidx.tv.material3.Card\n@Composable fun TvHomeScreen() { Card(onClick = {}) {} }",
    },
)


def minimal_ir(case: dict[str, object]) -> dict[str, object]:
    family = str(case["family"])
    return {
        "version": 1,
        "platforms": [case["adapter"]],
        "design": {
            "mode": "generate",
            "targetPlatforms": [family],
            "standardProfiles": {family: {"id": case["profile"], "source": "official"}},
        },
        "screens": [{"id": "main", "name": "Main", "platform": family, "root": "main-root"}],
        "nodes": {"main-root": {"type": "container", "standardRef": case["standardRef"], "children": []}},
    }


class PlatformProfileTests(unittest.TestCase):
    def test_new_profiles_are_complete(self) -> None:
        profiles = profile_catalog()["profiles"]
        for profile_id in ("windows-fluent", "macos-hig", "android-tv"):
            with self.subTest(profile=profile_id):
                profile = profiles[profile_id]
                self.assertTrue(profile["requirements"])
                self.assertTrue(profile["requiredInteractionStates"])
                self.assertTrue(profile["referenceUrls"])

    def test_platform_family_aliases(self) -> None:
        self.assertEqual(platform_family("winui3"), "windows")
        self.assertEqual(platform_family("appkit"), "macos")
        self.assertEqual(platform_family("compose-tv"), "android-tv")
        self.assertEqual(platform_family("react-native-windows"), "windows")
        self.assertEqual(platform_family("react-native-macos"), "macos")

    def test_platform_detection(self) -> None:
        for case in PLATFORM_CASES:
            with self.subTest(adapter=case["adapter"]):
                self.assertIn(case["adapter"], detect_platforms(case["path"], str(case["source"])))

    def test_winui_window_is_not_misclassified_as_wpf(self) -> None:
        detected = detect_platforms(PLATFORM_CASES[0]["path"], str(PLATFORM_CASES[0]["source"]))
        self.assertIn("windows-winui", detected)
        self.assertNotIn("windows-wpf", detected)

    def test_leanback_and_react_native_desktop_adapters(self) -> None:
        leanback = "import androidx.leanback.app.BrowseSupportFragment\nclass BrowseScreen : BrowseSupportFragment()"
        self.assertIn("android-tv-leanback", detect_platforms(Path("BrowseScreen.kt"), leanback))
        self.assertIn("react-native-windows", detect_platforms(Path("App.tsx"), "import { View } from 'react-native-windows';"))
        self.assertIn("react-native-macos", detect_platforms(Path("App.tsx"), "import { View } from 'react-native-macos';"))

    def test_adapter_and_profile_resolution(self) -> None:
        for case in PLATFORM_CASES:
            with self.subTest(adapter=case["adapter"]):
                ir = minimal_ir(case)
                self.assertEqual(framework_adapters(ir), {case["adapter"]})
                report = validate_profiles(ir)
                self.assertEqual(report["status"], "pass", report["issues"])
                self.assertEqual(report["resolvedProfiles"][case["family"]]["id"], case["profile"])

    def test_mobile_material_is_rejected_for_android_tv(self) -> None:
        case = dict(PLATFORM_CASES[2])
        case["profile"] = "material3"
        report = validate_profiles(minimal_ir(case))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("profile-invalid", {issue["code"] for issue in report["issues"]})

    def test_scanner_builds_tv_starter_profile_and_viewport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "TvHomeScreen.kt"
            source.write_text(str(PLATFORM_CASES[2]["source"]), encoding="utf-8")
            result = scan(root)
            ir = starter_ir(result)
        self.assertIn("android-tv-compose", result["detectedPlatforms"])
        self.assertEqual(ir["design"]["targetPlatforms"], ["android-tv"])
        self.assertEqual(ir["design"]["standardProfiles"]["android-tv"]["id"], "android-tv")
        self.assertEqual(ir["viewport"], {"width": 960, "height": 540, "device": "tv"})


if __name__ == "__main__":
    unittest.main()
