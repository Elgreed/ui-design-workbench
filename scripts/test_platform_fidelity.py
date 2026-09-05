"""Cross-platform regressions for source boundaries and native layout semantics."""
from pathlib import Path
import tempfile
import unittest

from fidelity_adapters import SourceContext, WebAdapter
from fidelity_platform_adapters import FlutterAdapter, SwiftUIAdapter, XamlAdapter, ProjectedMarkupAdapter
from fidelity_core import seal_baseline, validate_strict_ir
from source_syntax import mask_literals, closing, substitute_identifiers

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures/golden/platform-fidelity"


def translate(adapter, text, suffix, platforms, root=ROOT):
    source = "Screen" + suffix
    context = SourceContext(root, root/source, source, text, platforms, "screen")
    if hasattr(adapter, "prepare"):
        adapter.prepare([context])
    return adapter.translate(context)


class PlatformFidelityTests(unittest.TestCase):
    def test_comments_nested_comments_and_triple_strings_preserve_offsets(self):
        text = 'Text("(A)") /* outer /* ) */ } */\n' + "Text('''not a Column()''')"
        masked = mask_literals(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count("\n"), text.count("\n"))
        self.assertNotIn("Column", masked)
        self.assertEqual(closing(text, 4), 10)

    def test_substitution_preserves_literals_and_named_argument_keys(self):
        self.assertEqual(substitute_identifiers('Text(label, label: label, note: "label")', {"label": "'Value'"}),
                         'Text(\'Value\', label: \'Value\', note: "label")')

    def test_flutter_parent_cannot_steal_child_text_dimensions_or_styles(self):
        result = translate(FlutterAdapter(), """class Screen extends StatelessWidget {
          Widget build(BuildContext context) => Container(child: Text('Title', style: TextStyle(fontSize: 20, height: 1.4, color: Color(0x80336699))));
        }""", ".dart", ("flutter",))
        parent = next(n for n in result.nodes.values() if n.get("component") == "Container")
        text = next(n for n in result.nodes.values() if n.get("component") == "Text")
        self.assertNotIn("height", parent["layout"])
        self.assertFalse(parent["style"])
        self.assertNotIn("height", text["layout"])
        self.assertEqual(text["style"]["lineHeight"], 28)
        self.assertEqual(text["style"]["color"], "#33669980")

    def test_flutter_named_constructor_and_tight_child_constraints(self):
        result = translate(FlutterAdapter(), """class Screen extends StatelessWidget {
          Widget build(BuildContext context) => SizedBox(width: 80, height: 40, child: Image.asset('asset.png'));
        }""", ".dart", ("flutter",))
        box = next(n for n in result.nodes.values() if n.get("component") == "SizedBox")
        image = next(n for n in result.nodes.values() if n.get("component") == "Image")
        self.assertEqual(box["type"], "container")
        self.assertEqual(image["asset"], "asset.png")
        self.assertEqual(image["layout"], {"width": "fill", "height": "fill"})

    def test_flutter_local_defaults_do_not_rewrite_string_literals(self):
        result = translate(FlutterAdapter(), """class Label extends StatelessWidget {
          const Label({this.label = 'Default'});
          final String label;
          Widget build(BuildContext context) => Column(children: [Text(label), Text('label')]);
        }
        class Screen extends StatelessWidget {
          Widget build(BuildContext context) => Label();
        }""", ".dart", ("flutter",))
        self.assertEqual([n["text"] for n in result.nodes.values() if n.get("component") == "Text"], ["Default", "label"])

    def test_swiftui_child_frames_do_not_resize_stack_on_either_apple_platform(self):
        for platform in ("swiftui-ios", "swiftui-macos"):
            with self.subTest(platform=platform):
                result = translate(SwiftUIAdapter(), '''struct Screen: View { var body: some View {
                  VStack { Text("Title").frame(width: 80, height: 28) }.padding(.leading, 24).padding(.top, 16).padding(.trailing, 40).padding(.bottom, 32)
                } }''', ".swift", (platform,))
                stack = next(n for n in result.nodes.values() if n.get("component") == "VStack")
                self.assertNotIn("width", stack["layout"])
                self.assertNotIn("height", stack["layout"])
                self.assertEqual({key: value for key, value in stack["layout"].items() if key.startswith("padding")},
                                 {"paddingLeft": 24, "paddingTop": 16, "paddingRight": 40, "paddingBottom": 32})

    def test_swiftui_frame_padding_order_changes_outer_wrapper(self):
        for modifiers, outer, inner in ((".frame(width: 80).padding(8)", "padding", "frame"),
                                        (".padding(8).frame(width: 80)", "frame", "padding")):
            result = translate(SwiftUIAdapter(), f'struct Screen: View {{ var body: some View {{ Text("Title"){modifiers} }} }}', ".swift", ("swiftui-ios",))
            root = result.nodes[result.screens[0]["root"]]
            wrapper = result.nodes[root["children"][0]]
            self.assertEqual(wrapper["component"], "SwiftUI." + outer)
            self.assertEqual(result.nodes[wrapper["children"][0]]["component"], "SwiftUI." + inner)
            ir = {"version": 1, "fidelity": {"schemaVersion": "0.3", "sourceDerived": True}, "screens": result.screens, "nodes": result.nodes, "tokens": result.tokens}
            seal_baseline(ir)
            self.assertEqual(validate_strict_ir(ir), [])

    def test_swiftui_unique_local_view_expands_literal_arguments(self):
        result = translate(SwiftUIAdapter(), '''struct Badge: View {
          let title: String
          var body: some View { Text(title).font(.system(size: 14)) }
        }
        struct Screen: View { var body: some View { VStack { Badge(title: "Inbox") } } }
        ''', ".swift", ("swiftui-ios",))
        root = next(s["root"] for s in result.screens if s["name"] == "Screen")
        pending, labels = [root], []
        while pending:
            node = result.nodes[pending.pop()]
            if node.get("text"):
                labels.append(node["text"])
            pending.extend(node.get("children", []))
        self.assertEqual(labels, ["Inbox"])

    def test_swiftui_background_order_and_overlapping_padding(self):
        result = translate(SwiftUIAdapter(), 'struct Screen: View { var body: some View { Text("Title").background(.blue).padding(8) } }', '.swift', ('swiftui-ios',))
        text = next(n for n in result.nodes.values() if n.get('component') == 'Text')
        root = result.nodes[result.screens[0]['root']]
        wrapper = result.nodes[root['children'][0]]
        self.assertIn('backgroundColor', text['style'])
        self.assertNotIn('backgroundColor', wrapper['style'])
        result = translate(SwiftUIAdapter(), 'struct Screen: View { var body: some View { Text("Title").padding(8).padding(.horizontal,16) } }', '.swift', ('swiftui-ios',))
        text = next(n for n in result.nodes.values() if n.get('component') == 'Text')
        self.assertEqual(text['layout']['paddingLeft'],24)
        self.assertEqual(text['layout']['paddingTop'],8)

    def test_recursive_views_and_runtime_branches_remain_gaps(self):
        result = translate(SwiftUIAdapter(), 'struct Screen: View { var body: some View { if ready { Screen() } } }', ".swift", ("swiftui-macos",))
        reasons = {gap["reason"] for gap in result.unsupported}
        self.assertIn("recursive-or-deep-swiftui-component", reasons)
        self.assertIn("unevaluated-declarative-control-flow", reasons)
        self.assertLess(len(result.nodes), 10)

    def test_xaml_grid_thickness_argb_and_state(self):
        result = translate(XamlAdapter(), '''<Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
          <Grid.ColumnDefinitions><ColumnDefinition Width="80"/><ColumnDefinition Width="2*"/></Grid.ColumnDefinitions>
          <Grid.RowDefinitions><RowDefinition Height="28"/><RowDefinition Height="*"/></Grid.RowDefinitions>
          <Button Grid.Row="1" Grid.Column="1" Margin="1,2,3,4" Padding="5,6" Background="#80336699" IsEnabled="False" Content="Save"/>
        </Grid>''', ".xaml", ("windows-wpf",))
        button = next(n for n in result.nodes.values() if n.get("component") == "Button")
        grid = next(n for n in result.nodes.values() if n.get("component") == "Grid")
        self.assertEqual(grid["layout"]["columns"], "80px 2fr")
        self.assertEqual(grid["layout"]["rows"], "28px 1fr")
        self.assertEqual(button["layout"]["gridArea"], "2 / 2 / span 1 / span 1")
        self.assertEqual([button["layout"]["margin" + side] for side in ("Left", "Top", "Right", "Bottom")], [1, 2, 3, 4])
        self.assertEqual(button["layout"]["paddingTop"], 6)
        self.assertEqual(button["style"]["background"], "#33669980")
        self.assertTrue(button["disabled"])

    def test_web_specificity_source_order_and_important(self):
        result = translate(WebAdapter(), '''<style>#title {color:blue}.a {color:red}.b {background:red}.a {background:blue}
          .a {font-size:20px !important}</style><p id="title" class="a b" style="font-size:14px">Title</p>''', ".html", ("web",))
        text = next(n for n in result.nodes.values() if n.get("text") == "Title")
        self.assertEqual(text["style"]["color"], "blue")
        self.assertEqual(text["style"]["background"], "blue")
        self.assertEqual(text["style"]["fontSize"], "20px")

    def test_unlinked_css_and_media_rules_do_not_apply_unconditionally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'unrelated.css').write_text('p { color: red; }', encoding='utf-8')
            result = translate(WebAdapter(), '<style>@media(max-width:100px){p{color:red}}</style><p>Title</p>', ".html", ("web",), root)
            text = next(n for n in result.nodes.values() if n.get("text") == "Title")
            self.assertNotIn("color", text["style"])
            self.assertIn("unsupported-css-at-rule", {gap["reason"] for gap in result.unsupported})

    def test_stylesheet_order_and_vue_svelte_embedded_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'style.css').write_text('p{color:red}', encoding='utf-8')
            result=translate(WebAdapter(), '<link rel="stylesheet" href="style.css"><style>p{color:blue}</style><p>Title</p>', '.html', ('web',), root)
            self.assertEqual(next(n for n in result.nodes.values() if n.get('text') == 'Title')['style']['color'], 'blue')
        for kind in ('vue','svelte'):
            text='<p>Title</p><style>p{font-size:22px}</style>'
            if kind == 'vue':
                text='<template><p>Title</p></template><style>p{font-size:22px}</style>'
            result=translate(ProjectedMarkupAdapter(WebAdapter(),kind),text,'.'+kind,('web',))
            self.assertEqual(next(n for n in result.nodes.values() if n.get('text') == 'Title')['style']['fontSize'],'22px')

    def test_control_fixtures_pass_source_provenance_validation(self):
        for adapter, path, platform in ((FlutterAdapter(),'flutter/lib/calibration_page.dart','flutter'),
                                        (XamlAdapter(),'windows/Calibration.xaml','windows-wpf'),
                                        (SwiftUIAdapter(),'apple/CalibrationView.swift','swiftui-ios'),
                                        (WebAdapter(),'web/index.html','web')):
            with self.subTest(platform=platform):
                source=FIXTURES/path
                result=translate(adapter,source.read_text(encoding='utf-8'),source.suffix,(platform,))
                ir={'version':1,'fidelity':{'schemaVersion':'0.3','sourceDerived':True},'screens':result.screens,'nodes':result.nodes,'tokens':result.tokens}
                seal_baseline(ir)
                self.assertEqual(validate_strict_ir(ir),[])


if __name__ == '__main__':
    unittest.main()
