from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fidelity_adapters import SourceContext, registered_adapters
from platform_component_catalog import (
    SUPPORTED_FAMILIES,
    adapter_type_map,
    apply_component_defaults,
    catalog_summary,
    component_inventory,
    inventory_summary,
    resolve_component_catalog,
    validate_component_catalog,
)


ROOT = Path(__file__).resolve().parent.parent


def translate(name: str, text: str, platforms: tuple[str, ...], suffix: str):
    source = ROOT / "fixtures" / "synthetic" / f"{name}{suffix}"
    context = SourceContext(ROOT, source, source.relative_to(ROOT).as_posix(), text, platforms, "screen")
    adapter = next(item for item in registered_adapters() if item.supports(context))
    return adapter.translate(context)


class PlatformComponentCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_and_has_official_sources(self):
        summary = catalog_summary()
        self.assertEqual(validate_component_catalog(), [])
        self.assertEqual(set(summary["families"]), set(SUPPORTED_FAMILIES))
        self.assertGreaterEqual(summary["recipeCount"], 55)
        self.assertGreaterEqual(summary["conceptCount"], 150)
        self.assertGreaterEqual(summary["bindingCount"], 500)
        self.assertEqual(summary["componentCount"], summary["bindingCount"])
        self.assertTrue(all(item["officialSourceCount"] for item in summary["families"].values()))

    def test_full_inventory_has_broad_platform_and_framework_coverage(self):
        summary = inventory_summary()
        self.assertEqual(set(summary["families"]), set(SUPPORTED_FAMILIES))
        self.assertTrue(all(item["conceptCount"] >= 17 for item in summary["families"].values()))
        expected_bindings = {
            ("android", "compose"): {"AssistChip", "DateRangePicker", "ModalBottomSheet", "PrimaryTabRow"},
            ("android", "android-xml"): {"Chip", "TabLayout", "SearchView", "MaterialCardView"},
            ("ios", "swiftui"): {"DisclosureGroup", "Stepper", "Gauge", "Map"},
            ("macos", "apple-interface-xml"): {"outlineView", "tokenField", "levelIndicator", "pathControl"},
            ("windows", "xaml"): {"ContentDialog", "InfoBar", "CalendarDatePicker", "BreadcrumbBar"},
            ("flutter", "flutter"): {"CupertinoAlertDialog", "ReorderableListView", "Badge", "FilledButton.tonal"},
            ("web", "web"): {"dialog", "details", "meter", "picture"},
        }
        for (family, adapter), expected in expected_bindings.items():
            with self.subTest(family=family, adapter=adapter):
                self.assertTrue(expected.issubset(adapter_type_map(family, adapter)))

    def test_inventory_recipes_resolve_to_calibrated_catalog(self):
        payload = component_inventory()
        for family, descriptor in payload["families"].items():
            for concept_id, concept in descriptor["inventory"].items():
                with self.subTest(family=family, concept=concept_id):
                    self.assertTrue(concept["recipe"])

    def test_nonvisual_containers_and_media_do_not_receive_control_geometry(self):
        self.assertEqual(adapter_type_map("android", "compose")["Image"], "image")
        self.assertEqual(adapter_type_map("android", "compose")["Icon"], "icon")
        self.assertEqual(adapter_type_map("flutter", "flutter")["Image"], "image")
        self.assertEqual(adapter_type_map("flutter", "flutter")["Icon"], "icon")
        ir = {
            "screens": [{"id": "home", "root": "root", "platform": "android"}],
            "nodes": {
                "root": {"type": "container", "layout": {}, "style": {}, "children": ["hero"]},
                "hero": {"type": "image", "component": "Image", "layout": {}, "style": {}, "children": []},
            },
        }
        rendered = apply_component_defaults(ir)
        hero = rendered["nodes"]["hero"]
        self.assertEqual(hero["rendererRecipeId"], "neutral")
        self.assertEqual(hero["layout"], {})
        self.assertEqual(hero["style"], {})
        self.assertNotIn("role", hero.get("semantics", {}))

    def test_web_landmarks_are_not_all_promoted_to_navigation(self):
        result = translate(
            "Landmarks",
            "<header>Header</header><nav>Menu</nav><footer>Footer</footer>",
            ("web",),
            ".html",
        )
        rendered = apply_component_defaults({"screens": result.screens, "nodes": result.nodes})
        by_component = {node.get("component"): node for node in rendered["nodes"].values() if node.get("component")}
        self.assertEqual(by_component["nav"].get("semantics", {}).get("role"), "navigation")
        self.assertNotIn("role", by_component["header"].get("semantics", {}))
        self.assertNotIn("role", by_component["footer"].get("semantics", {}))

    def test_catalog_resolution_supports_user_site_data_install(self):
        with patch("platform_component_catalog.site.USER_BASE", "/tmp/uidw-user"), patch(
            "platform_component_catalog.Path.is_file",
            autospec=True,
            side_effect=lambda path: path.as_posix().endswith("/tmp/uidw-user/share/ui-design-workbench/references/component-catalog.json"),
        ):
            resolved = resolve_component_catalog().as_posix()
        self.assertTrue(resolved.endswith("/tmp/uidw-user/share/ui-design-workbench/references/component-catalog.json"))

    def test_render_defaults_are_fallbacks_and_do_not_mutate_source_ir(self):
        ir = {
            "screens": [{"id": "home", "root": "root", "platform": "android"}],
            "nodes": {
                "root": {"type": "container", "layout": {}, "style": {}, "children": ["save"]},
                "save": {"type": "button", "component": "OutlinedButton", "layout": {"minHeight": 60}, "style": {"color": "#123456"}, "children": []},
            },
        }
        rendered = apply_component_defaults(ir)
        self.assertNotIn("rendererComponentId", ir["nodes"]["save"])
        self.assertEqual(rendered["nodes"]["save"]["rendererComponentId"], "android.outlined-button")
        self.assertEqual(rendered["nodes"]["save"]["layout"]["minHeight"], 60)
        self.assertEqual(rendered["nodes"]["save"]["style"]["color"], "#123456")
        self.assertEqual(rendered["nodes"]["save"]["style"]["borderWidth"], 1)

    def test_generic_project_node_is_not_styled_from_type_alone(self):
        ir = {
            "screens": [{"id": "home", "root": "root", "platform": "web"}],
            "nodes": {"root": {"type": "text", "text": "Project title", "layout": {}, "style": {}, "children": []}},
        }
        rendered = apply_component_defaults(ir)
        self.assertNotIn("rendererComponentId", rendered["nodes"]["root"])
        self.assertEqual(rendered["nodes"]["root"]["style"], {})

    def test_android_compose_catalog_components_are_translated(self):
        result = translate(
            "CatalogScreen",
            '@Composable fun CatalogScreen() { Column { OutlinedButton(onClick = {}) { Text("Save") }; Switch(checked = true, onCheckedChange = {}); LinearProgressIndicator() } }',
            ("android-compose",),
            ".kt",
        )
        components = {node.get("component") for node in result.nodes.values()}
        self.assertTrue({"OutlinedButton", "Switch", "LinearProgressIndicator"}.issubset(components))
        switch = next(node for node in result.nodes.values() if node.get("component") == "Switch")
        self.assertEqual(switch["type"], "container")
        self.assertEqual(switch["semantics"]["role"], "switch")
        rendered = apply_component_defaults({"screens": result.screens, "nodes": result.nodes})
        rendered_switch = next(node for node in rendered["nodes"].values() if node.get("component") == "Switch")
        self.assertEqual(rendered_switch["type"], "button")
        self.assertFalse(any(item["expression"] in components for item in result.unsupported))

    def test_disabled_conditional_control_is_not_inferred_as_interactive(self):
        result = translate(
            "DisabledControl",
            '@Composable fun DisabledControl() { Switch(checked = true, onCheckedChange = null) }',
            ("android-compose",),
            ".kt",
        )
        switch = next(node for node in result.nodes.values() if node.get("component") == "Switch")
        rendered = apply_component_defaults({"screens": result.screens, "nodes": result.nodes})
        self.assertEqual(switch["type"], "container")
        self.assertNotIn("role", rendered["nodes"][next(key for key, node in result.nodes.items() if node.get("component") == "Switch")].get("semantics", {}))

    def test_swiftui_flutter_xaml_and_android_xml_catalog_components_are_translated(self):
        cases = [
            ("Apple", 'struct Apple: View { var body: some View { NavigationSplitView { List { Toggle("Enabled", isOn: .constant(true)) } } detail: { ProgressView() } } }', ("swiftui-macos",), ".swift", {"NavigationSplitView", "Toggle", "ProgressView"}),
            ("Flutter", 'class Flutter extends StatelessWidget { Widget build(BuildContext context) { return Scaffold(appBar: AppBar(), body: Column(children: [FilledButton(onPressed: () {}, child: Text("Save")), Switch(value: true, onChanged: (_) {}), LinearProgressIndicator()])); } }', ("flutter",), ".dart", {"AppBar", "FilledButton", "Switch", "LinearProgressIndicator"}),
            ("Windows", '<Page xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"><StackPanel><ToggleSwitch/><AutoSuggestBox/><ProgressBar/></StackPanel></Page>', ("windows-winui",), ".xaml", {"ToggleSwitch", "AutoSuggestBox", "ProgressBar"}),
            ("Android", '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android" android:orientation="vertical"><Switch/><ProgressBar/></LinearLayout>', ("android-xml",), ".xml", {"Switch", "ProgressBar"}),
        ]
        for name, text, platforms, suffix, expected in cases:
            with self.subTest(name=name):
                result = translate(name, text, platforms, suffix)
                components = {node.get("component") for node in result.nodes.values()}
                self.assertTrue(expected.issubset(components), (expected, components, result.unsupported))

    def test_extended_inventory_components_are_translated_without_unsupported_noise(self):
        cases = [
            (
                "ComposeExtended",
                '@Composable fun ComposeExtended() { Column { AssistChip(onClick = {}, label = { Text("A") }); DatePicker(state = state); ModalBottomSheet(onDismissRequest = {}) {}; PrimaryTabRow(selectedTabIndex = 0) {} } }',
                ("android-compose",),
                ".kt",
                {"AssistChip", "DatePicker", "ModalBottomSheet", "PrimaryTabRow"},
            ),
            (
                "AppleExtended",
                'struct AppleExtended: View { var body: some View { Form { DisclosureGroup("More") { Text("Body") }; Stepper("Count", value: $count); Gauge(value: 0.5) {}; Map() } } }',
                ("swiftui-ios",),
                ".swift",
                {"DisclosureGroup", "Stepper", "Gauge", "Map"},
            ),
            (
                "FlutterExtended",
                'class FlutterExtended extends StatelessWidget { Widget build(BuildContext context) { return Column(children: [CupertinoAlertDialog(), ReorderableListView(children: [], onReorder: (_, __) {}), Badge(), FilledButton.tonal(onPressed: () {}, child: Text("Go"))]); } }',
                ("flutter",),
                ".dart",
                {"CupertinoAlertDialog", "ReorderableListView", "Badge", "FilledButton.tonal"},
            ),
            (
                "WindowsExtended",
                '<Page xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"><StackPanel><ContentDialog/><InfoBar/><CalendarDatePicker/><BreadcrumbBar/></StackPanel></Page>',
                ("windows-winui",),
                ".xaml",
                {"ContentDialog", "InfoBar", "CalendarDatePicker", "BreadcrumbBar"},
            ),
            (
                "AndroidXmlExtended",
                '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"><Chip/><TabLayout/><SearchView/></LinearLayout>',
                ("android-xml",),
                ".xml",
                {"Chip", "TabLayout", "SearchView"},
            ),
            (
                "WebExtended",
                '<main><dialog><details><summary>More</summary></details><meter value=".5"></meter></dialog></main>',
                ("web",),
                ".html",
                {"dialog", "details", "summary", "meter"},
            ),
        ]
        for name, text, platforms, suffix, expected in cases:
            with self.subTest(name=name):
                result = translate(name, text, platforms, suffix)
                components = {node.get("component") for node in result.nodes.values()}
                self.assertTrue(expected.issubset(components), (expected, components, result.unsupported))
                unsupported = {item["expression"] for item in result.unsupported}
                self.assertFalse(expected & unsupported, result.unsupported)


if __name__ == "__main__":
    unittest.main()
