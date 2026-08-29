#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from pathlib import Path

from android_resource_resolver import AndroidResourceCatalog, android_layout_role, material_icon_asset
from fidelity_adapters import SourceContext, translate_sources
from render_preview import render_html, resolve_assets
from scan_ui import scan, starter_ir


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "golden" / "android-resources"


def contexts() -> list[SourceContext]:
    result: list[SourceContext] = []
    for path in sorted(FIXTURE.rglob("*")):
        if path.suffix.lower() not in {".xml", ".kt"}:
            continue
        platform = ("android-compose",) if path.suffix.lower() == ".kt" else ("android-views",)
        result.append(SourceContext(FIXTURE, path, path.relative_to(FIXTURE).as_posix(), path.read_text(encoding="utf-8"), platform, "screen" if "/layout/" in path.as_posix() or path.suffix.lower() == ".kt" else "theme"))
    return result


class AndroidResourceResolverTests(unittest.TestCase):
    def test_catalog_resolves_values_styles_shapes_vectors_and_layouts(self) -> None:
        expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
        catalog = AndroidResourceCatalog.discover(FIXTURE)

        self.assertEqual(catalog.resolve("@string/screen_title", "string").value, expected["screenText"])
        self.assertEqual(catalog.resolve("@color/primary", "color").value, expected["primary"])
        self.assertEqual(catalog.resolve("@dimen/content_padding", "dimen").value, expected["contentPadding"])
        style, entry = catalog.style("@style/TitleText")
        self.assertIsNotNone(entry)
        self.assertEqual(catalog.resolve(style["android:textColor"], "color", style).value, expected["primary"])
        shape = catalog.drawable("@drawable/panel_background")
        self.assertEqual(shape.style["backgroundColor"], expected["surface"])
        self.assertEqual(shape.style["radius"], expected["shapeRadius"])
        vector = catalog.drawable("@drawable/ic_add")
        self.assertTrue(vector.asset.startswith("data:image/svg+xml;base64,"))
        self.assertTrue(catalog.layout("@layout/content_panel").is_file())
        self.assertTrue(material_icon_asset("Add").startswith("data:image/svg+xml;base64,"))

    def test_android_layout_roles_do_not_promote_partials_to_screens(self) -> None:
        activity = FIXTURE / "app/src/main/res/layout/activity_main.xml"
        partial = FIXTURE / "app/src/main/res/layout/content_panel.xml"
        self.assertEqual(android_layout_role(activity, activity.read_text(encoding="utf-8")), "screen")
        self.assertEqual(android_layout_role(partial, partial.read_text(encoding="utf-8")), "component")

        scan_result = scan(FIXTURE)
        self.assertEqual(
            [item["path"] for item in scan_result["uiFiles"] if item["role"] == "component"],
            ["app/src/main/res/layout/content_panel.xml"],
        )
        self.assertNotIn("ContentPanel", {item["name"] for item in scan_result["screens"]})
        ir = starter_ir(scan_result)
        self.assertNotIn("content_panel", {item["name"] for item in ir["screens"]})
        self.assertIn(
            "app/src/main/res/layout/content_panel.xml#content_panel",
            {item["id"] for item in ir["componentCatalog"]["components"]},
        )

    def test_adapters_resolve_android_resources_and_layout_semantics(self) -> None:
        expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
        result = translate_sources(contexts())
        nodes = list(result.nodes.values())

        title_nodes = [node for node in nodes if node.get("text") == expected["screenText"]]
        self.assertGreaterEqual(len(title_nodes), 2)
        self.assertTrue(any(node.get("style", {}).get("color") == expected["primary"] for node in title_nodes))
        self.assertTrue(any(node.get("layout", {}).get("padding") == expected["contentPadding"] for node in nodes))
        self.assertTrue(any(node.get("style", {}).get("backgroundColor") == expected["surface"] and node.get("style", {}).get("radius") == expected["shapeRadius"] for node in nodes))
        self.assertTrue(any(node.get("component") == "include" and node.get("children") for node in nodes))
        self.assertTrue(any(node.get("component") == "ImageButton.drawable" and str(node.get("asset", "")).startswith("data:image/svg+xml;base64,") for node in nodes))
        image_button = next(node for node in nodes if node.get("component") == "ImageButton")
        self.assertEqual(image_button["layout"]["justifySelf"], "center")
        self.assertEqual(image_button["layout"]["alignSelf"], "center")
        self.assertEqual(image_button["semantics"]["label"], "Add project")
        compose_column = next(node for node in nodes if node.get("component") == "Column" and node.get("source", {}).get("symbol") == "ResourceScreen")
        self.assertEqual(compose_column["layout"]["paddingHorizontal"], expected["composeHorizontalPadding"])
        self.assertEqual(compose_column["layout"]["paddingVertical"], expected["composeVerticalPadding"])
        self.assertEqual(compose_column["layout"]["align"], "center")
        self.assertEqual(compose_column["layout"]["justify"], "center")
        compose_icon = next(node for node in nodes if node.get("component") == "Icon" and node.get("source", {}).get("symbol") == "ResourceScreen")
        self.assertEqual(compose_icon["layout"]["width"], expected["iconSize"])
        self.assertEqual(compose_icon["layout"]["height"], expected["iconSize"])
        self.assertTrue(compose_icon["asset"].startswith("data:image/svg+xml;base64,"))
        compose_text = next(node for node in nodes if node.get("component") == "Text" and node.get("source", {}).get("symbol") == "ResourceScreen")
        self.assertEqual(compose_text["text"], expected["screenText"])
        self.assertEqual(compose_text["style"]["fontSize"], "20px")
        self.assertEqual(compose_text["style"]["color"], expected["primary"])

    def test_projection_embeds_resolved_icons_and_overlay_alignment(self) -> None:
        translated = translate_sources(contexts())
        ir = {
            "project": {"name": "Android resources", "root": str(FIXTURE)},
            "screens": translated.screens,
            "nodes": translated.nodes,
            "tokens": translated.tokens,
            "fidelityAudit": {"designMode": "reconstruct", "nativeEvidenceRequired": True, "visualFidelityTier": "structural", "nativeExecutionStarted": False},
        }
        preview = render_html(resolve_assets(ir))

        self.assertIn("data:image/svg+xml;base64,", preview)
        self.assertIn("direction==='overlay'){out.position='relative';out.display='grid'", preview)
        self.assertIn("if(l.justifySelf)out.justifySelf", preview)
        self.assertIn("Нативный снимок:</span> не проверен", preview)


if __name__ == "__main__":
    unittest.main()
