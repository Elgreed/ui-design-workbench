from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compose_resources import ComposeResources
from compose_syntax import composable_functions, named_argument
from fidelity_adapters import ComposeAdapter, SourceContext
from fidelity_core import seal_baseline, validate_strict_ir
from platform_component_catalog import apply_component_defaults


ROOT = Path(__file__).resolve().parent.parent


def context(text, source="Screen.kt", root=ROOT, role="screen"):
    return SourceContext(root, root / source, source, text, ("android-compose",), role)


class ComposeProjectionTests(unittest.TestCase):
    def test_callbacks_comments_and_strings_preserve_function_boundaries(self):
        text = '''
@Composable
internal fun Screen(state: State, onClick: (String) -> Unit = { value -> log(value) }) {
    // Text("not a node") }
    Column { Text("A } comma, and (parenthesis)") }
}
@Composable
private fun ScreenPreview() { Text("Preview") }
'''
        result = ComposeAdapter().translate(context(text))
        self.assertEqual([s["name"] for s in result.screens], ["Screen", "ScreenPreview"])
        self.assertEqual([n["text"] for n in result.nodes.values() if "text" in n], ["A } comma, and (parenthesis)", "Preview"])
        self.assertEqual(result.screens[1]["source"]["line"], 7)

    def test_nested_arguments_rectangular_size_and_callback_modifiers(self):
        text = '''@Composable fun Screen(onClick: () -> Unit) {
    Box(contentAlignment = Alignment.TopCenter) {
        Image(painter = painterResource(R.drawable.logo), contentDescription = null,
              modifier = Modifier.size(width = 96.dp, height = 44.dp).widthIn(max = 200.dp))
        Button(onClick = { log(Modifier.padding(99.dp)) }, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) { Text("Continue") }
    }
}'''
        result = ComposeAdapter().translate(context(text))
        nodes = {n.get("component"): n for n in result.nodes.values()}
        self.assertEqual(nodes["Image"]["layout"]["width"], "96px")
        self.assertEqual(nodes["Image"]["layout"]["height"], "44px")
        self.assertEqual(nodes["Image"]["layout"]["maxWidth"], "200px")
        self.assertEqual(nodes["Box"]["layout"]["align"], "start")
        self.assertEqual(nodes["Box"]["layout"]["justify"], "center")
        self.assertNotIn("padding", nodes["Button"]["layout"])
        self.assertEqual(nodes["Button"]["layout"]["paddingHorizontal"], "16px")
        self.assertIn("layout.gridArea", nodes["Image"]["provenance"])

    def test_theme_indirection_typography_and_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            font = root / "app/src/main/res/font/brand.ttf"
            font.parent.mkdir(parents=True)
            font.write_bytes(b"font fixture")
            theme = context('''
val BrandFont = FontFamily(Font(R.font.brand, weight = FontWeight.SemiBold))
val BrandTypography = Typography(titleLarge = TextStyle(fontFamily = BrandFont, fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 28.sp))
val DefaultSpacing = Spacing(small = 8.dp, medium = 16.dp)
val DefaultLayout = Layout(screenPadding = DefaultSpacing.medium)
val LocalLayout = staticCompositionLocalOf { DefaultLayout }
val LightInk = Color(0xFF131415)
val DarkInk = Color(0xFFF4F5F6)
val LightScheme = lightColorScheme(onBackground = LightInk)
val DarkScheme = darkColorScheme(onBackground = DarkInk)
object BrandTheme { val layout: Layout @Composable get() = LocalLayout.current }
@Composable fun BrandTheme(content: @Composable () -> Unit) {
    MaterialTheme(typography = BrandTypography, colorScheme = if (darkTheme) DarkScheme else LightScheme) { content() }
}
''', "ui/theme/Theme.kt", root, "theme")
            screen = context('''@Composable fun Screen(onClick: () -> Unit) {
    Column(modifier = Modifier.padding(BrandTheme.layout.screenPadding)) {
        Text("Title", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onBackground)
    }
}''', root=root)
            adapter = ComposeAdapter()
            adapter.prepare([theme, screen])
            result = adapter.translate(screen)
            title = next(n for n in result.nodes.values() if n.get("text") == "Title")
            column = next(n for n in result.nodes.values() if n.get("component") == "Column")
            self.assertEqual(column["layout"]["padding"], "16px")
            self.assertEqual(title["style"], {"fontSize": "22px", "fontFamily": "BrandFont", "fontWeight": 600, "lineHeight": "28px", "color": "#131415"})
            self.assertEqual(result.fonts[0]["asset"], "app/src/main/res/font/brand.ttf")
            title_id = next(key for key, node in result.nodes.items() if node is title)
            self.assertEqual(result.themes[0]["nodeOverrides"][title_id]["style"]["color"], "#f4f5f6")
            self.assertEqual(ComposeResources([theme]).resolve("MaterialTheme.colorScheme.onBackground", dark=True), "#f4f5f6")
            ir = {"version": 1, "fidelity": {"schemaVersion": "0.3", "sourceDerived": True}, "screens": result.screens, "nodes": result.nodes, "tokens": result.tokens}
            seal_baseline(ir)
            self.assertEqual(validate_strict_ir(ir), [])

    def test_ambiguous_and_cyclic_theme_values_stay_unresolved(self):
        resources = ComposeResources([context("val A = B\nval B = A\nval Pad = 8.dp\nval Pad = 16.dp", "ui/theme/Tokens.kt", role="theme")])
        self.assertIsNone(resources.resolve("A"))
        self.assertIsNone(resources.resolve("Pad"))
        self.assertIsNone(resources.resolve("unknown.runtimeValue"))

    def test_named_argument_does_not_capture_nested_parameter(self):
        self.assertIsNone(named_argument('onClick = { draw(width = 20.dp) }, modifier = Modifier', "width"))
        self.assertEqual(named_argument('shape = Round(12.dp, 4.dp), text = "A,B"', "shape"), "Round(12.dp, 4.dp)")

    def test_local_component_defaults_enum_fixture_and_source_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "domain/src/main/kotlin/sample/Choice.kt"
            source.parent.mkdir(parents=True)
            source.write_text("package sample\nenum class Choice { ONE, TWO }", encoding="utf-8")
            screen = context('''import sample.Choice
@Composable fun Item(selected: Boolean, modifier: Modifier = Modifier) {
    Surface(modifier = modifier.heightIn(min = 56.dp)) {
        Row { RadioButton(selected = selected, onClick = null) }
    }
}
@Composable fun Screen(state: State) {
    Column {
        Choice.entries.forEach { choice ->
            Item(selected = state.selected == choice, modifier = Modifier.fillMaxWidth())
            Text("after")
        }
    }
}
@Composable fun Preview() { Screen(state = State(selected = Choice.ONE)) }
''', root=root)
            adapter = ComposeAdapter()
            adapter.prepare([screen])
            result = adapter.translate(screen, _only="Preview")
            radios = [n for n in result.nodes.values() if n.get("component") == "RadioButton"]
            self.assertEqual([n["checked"] for n in radios], [True, False])
            self.assertTrue(all(n["interactionMode"] == "passive" for n in radios))
            column = next(n for n in result.nodes.values() if n.get("component") == "Column")
            self.assertEqual([result.nodes[key]["component"] for key in column["children"]], ["Item", "Text", "Item", "Text"])
            ir = {"version": 1, "fidelity": {"schemaVersion": "0.3", "sourceDerived": True}, "screens": result.screens, "nodes": result.nodes, "tokens": result.tokens}
            seal_baseline(ir)
            self.assertEqual(validate_strict_ir(ir), [])
            rendered = apply_component_defaults(ir)
            for node in rendered["nodes"].values():
                if node.get("component") == "RadioButton":
                    self.assertEqual(node["layout"]["width"], 24)
                    self.assertNotIn("role", node.get("semantics", {}))
                if node.get("component") == "Surface":
                    self.assertEqual(node["layout"]["padding"], 0)
                    self.assertEqual(node["layout"]["width"], "fill")
                    self.assertEqual(node["layout"]["minHeight"], "56px")

    def test_recursive_components_and_expansion_budget_are_reported(self):
        source = context('''@Composable fun Loop() { Column { Loop() } }
@Composable fun Screen() { Loop() }
''')
        adapter = ComposeAdapter()
        adapter.prepare([source])
        result = adapter.translate(source, _only="Screen")
        self.assertLess(len(result.nodes), 12)
        self.assertIn("recursive-or-deep-compose-component", [item["reason"] for item in result.unsupported])
        result = adapter.translate(source, _only="Screen", _budget=[1])
        self.assertIn("compose-expansion-budget-exceeded", [item["reason"] for item in result.unsupported])


if __name__ == "__main__":
    unittest.main()
