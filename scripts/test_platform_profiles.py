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
        "family": "android", "adapter": "android-compose", "profile": "material3", "standardRef": "material3.Button",
        "path": Path("HomeScreen.kt"), "source": "import androidx.compose.runtime.Composable\n@Composable fun HomeScreen() {}",
    },
    {
        "family": "ios", "adapter": "swiftui", "profile": "apple-hig", "standardRef": "apple.Button",
        "path": Path("HomeView.swift"), "source": "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"Home\") } }",
    },
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
        "family": "flutter", "adapter": "flutter", "profile": "flutter-adaptive", "standardRef": "flutter.Text",
        "path": Path("home.dart"), "source": "import 'package:flutter/widgets.dart';\nclass Home extends StatelessWidget { Widget build(context) => Text('Home'); }",
    },
    {
        "family": "web", "adapter": "react-web", "profile": "web-platform", "standardRef": "html.button",
        "path": Path("Home.tsx"), "source": "import React from 'react'; export function Home() { return <button>Home</button>; }",
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
        for profile_id in ("material3", "apple-hig", "windows-fluent", "macos-hig", "flutter-adaptive", "web-platform"):
            with self.subTest(profile=profile_id):
                profile = profiles[profile_id]
                self.assertTrue(profile["requirements"])
                self.assertTrue(profile["requiredInteractionStates"])
                if profile_id in {"windows-fluent", "macos-hig", "flutter-adaptive"}:
                    self.assertTrue(profile["referenceUrls"])

    def test_platform_family_aliases(self) -> None:
        self.assertEqual(platform_family("winui3"), "windows")
        self.assertEqual(platform_family("appkit"), "macos")
        self.assertEqual(platform_family("flutter"), "flutter")
        self.assertIsNone(platform_family("compose-tv"))
        self.assertIsNone(platform_family("react-native-windows"))

    def test_platform_detection(self) -> None:
        for case in PLATFORM_CASES:
            with self.subTest(adapter=case["adapter"]):
                self.assertIn(case["adapter"], detect_platforms(case["path"], str(case["source"])))

    def test_winui_window_is_not_misclassified_as_wpf(self) -> None:
        case = next(item for item in PLATFORM_CASES if item["family"] == "windows")
        detected = detect_platforms(case["path"], str(case["source"]))
        self.assertIn("windows-winui", detected)
        self.assertNotIn("windows-wpf", detected)

    def test_removed_specific_platforms_are_not_detected(self) -> None:
        leanback = "import androidx.leanback.app.BrowseSupportFragment\nclass BrowseScreen : BrowseSupportFragment()"
        self.assertEqual(detect_platforms(Path("BrowseScreen.kt"), leanback), [])
        self.assertEqual(detect_platforms(Path("App.tsx"), "import { View } from 'react-native-windows';"), [])
        self.assertEqual(detect_platforms(Path("App.tsx"), "import { View } from 'react-native-macos';"), [])

    def test_adapter_and_profile_resolution(self) -> None:
        for case in PLATFORM_CASES:
            with self.subTest(adapter=case["adapter"]):
                ir = minimal_ir(case)
                self.assertEqual(framework_adapters(ir), {case["adapter"]})
                report = validate_profiles(ir)
                self.assertEqual(report["status"], "pass", report["issues"])
                self.assertEqual(report["resolvedProfiles"][case["family"]]["id"], case["profile"])

    def test_scanner_builds_flutter_starter_profile_and_viewport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "HomePage.dart"
            source.write_text("import 'package:flutter/widgets.dart';\nclass HomePage extends StatelessWidget { Widget build(context) { return Text('Home'); } }", encoding="utf-8")
            result = scan(root)
            ir = starter_ir(result)
        self.assertIn("flutter", result["detectedPlatforms"])
        self.assertEqual(ir["design"]["targetPlatforms"], ["flutter"])
        self.assertEqual(ir["design"]["standardProfiles"]["flutter"]["id"], "flutter-adaptive")
        self.assertEqual(ir["viewport"], {"width": 390, "height": 844, "device": "phone"})


if __name__ == "__main__":
    unittest.main()
