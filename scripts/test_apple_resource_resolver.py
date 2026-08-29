#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from pathlib import Path

from apple_resource_resolver import AppleResourceCatalog, sf_symbol_asset
from fidelity_adapters import SourceContext, translate_sources
from quality_common import platform_family, profile_catalog
from render_preview import render_html, resolve_assets
from scan_ui import detect_platforms, scan, starter_ir


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "golden" / "apple-resources"


class AppleResourceResolverTests(unittest.TestCase):
    def test_catalog_resolves_asset_colors_localization_and_symbols(self) -> None:
        expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
        catalog = AppleResourceCatalog.discover(FIXTURE)
        self.assertEqual(catalog.localized("screen_title").value, expected["title"])
        self.assertEqual(catalog.color("Accent").value, expected["accent"])
        self.assertEqual(catalog.color("Surface").value, expected["surface"])
        self.assertEqual(catalog.image("Hero").value, expected["image"])
        self.assertTrue(sf_symbol_asset("plus").startswith("data:image/svg+xml;base64,"))

    def test_swiftui_and_storyboard_use_resolved_resources_and_layout(self) -> None:
        expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
        paths = [FIXTURE / "Sample/ResourceView.swift", FIXTURE / "Sample/Resource.storyboard"]
        contexts = [
            SourceContext(FIXTURE, path, path.relative_to(FIXTURE).as_posix(), path.read_text(encoding="utf-8"), ("swiftui",) if path.suffix == ".swift" else ("uikit",), "screen")
            for path in paths
        ]
        result = translate_sources(contexts)
        nodes = list(result.nodes.values())
        localized = next(node for node in nodes if node.get("text") == expected["title"] and node.get("component") == "Text")
        self.assertEqual(localized["style"]["fontSize"], 20)
        self.assertEqual(localized["style"]["fontWeight"], 600)
        self.assertEqual(localized["style"]["color"], expected["accent"])
        stack = next(node for node in nodes if node.get("component") == "VStack")
        self.assertEqual(stack["layout"]["align"], "start")
        self.assertEqual(stack["layout"]["gap"], expected["spacing"])
        self.assertEqual(stack["layout"]["paddingHorizontal"], expected["horizontalPadding"])
        self.assertEqual(stack["style"]["backgroundColor"], expected["surface"])
        self.assertEqual(stack["style"]["radius"], expected["radius"])
        self.assertTrue(any(node.get("type") == "icon" and str(node.get("asset", "")).startswith("data:image/svg+xml;base64,") for node in nodes))
        self.assertTrue(any(node.get("asset") == expected["image"] for node in nodes))
        storyboard_image = next(node for node in nodes if node.get("component") == "imageView")
        self.assertEqual(storyboard_image["layout"]["width"], 120)
        self.assertEqual(storyboard_image["layout"]["justifySelf"], "center")
        self.assertEqual(storyboard_image["layout"]["position"], "absolute")

        ir = {
            "project": {"name": "Apple resources", "root": str(FIXTURE)},
            "screens": result.screens,
            "nodes": result.nodes,
            "tokens": result.tokens,
            "design": {"targetPlatforms": ["ios"]},
            "fidelityAudit": {"designMode": "reconstruct", "nativeEvidenceRequired": True, "visualFidelityTier": "structural", "nativeExecutionStarted": False},
        }
        preview = render_html(resolve_assets(ir))
        self.assertIn("data:image/svg+xml;base64,", preview)
        self.assertIn("Нативный снимок:</span> не проверен", preview)

    def test_public_platform_contract_contains_only_supported_families(self) -> None:
        supported = {"android", "ios", "macos", "windows", "flutter", "web"}
        catalog = profile_catalog()
        self.assertEqual({item["family"] for item in catalog["profiles"].values()}, supported)
        self.assertEqual(platform_family("flutter"), "flutter")
        self.assertIsNone(platform_family("android-tv"))
        self.assertIsNone(platform_family("react-native"))
        self.assertEqual(detect_platforms(Path("TvScreen.kt"), "import androidx.compose.runtime.Composable\nimport androidx.tv.material3.Card\n@Composable fun TvScreen() {}"), [])
        self.assertEqual(detect_platforms(Path("App.tsx"), "import { View } from 'react-native';"), [])

        ir = starter_ir(scan(FIXTURE))
        self.assertEqual(ir["design"]["targetPlatforms"], ["ios"])

        flutter_root = ROOT / "fixtures" / "golden" / "platform-pack" / "flutter"
        flutter_ir = starter_ir(scan(flutter_root))
        self.assertEqual(flutter_ir["design"]["targetPlatforms"], ["flutter"])
        self.assertEqual(flutter_ir["design"]["standardProfiles"]["flutter"]["id"], "flutter-adaptive")


if __name__ == "__main__":
    unittest.main()
