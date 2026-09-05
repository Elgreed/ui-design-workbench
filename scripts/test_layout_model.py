from __future__ import annotations

import copy
import unittest

from layout_model import LayoutSolver, build_projection_geometry, context_key, validate_projection_geometry
from render_preview import render_html


class LayoutModelTests(unittest.TestCase):
    def test_column_uses_parent_constraints_padding_gap_and_fill(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "column", "padding": 10, "gap": 5}, "children": ["first", "second"]},
            "first": {"type": "spacer", "layout": {"width": 50, "height": 20}},
            "second": {"type": "spacer", "layout": {"width": "fill", "height": 30}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 200, 160)

        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["nodes"]["root"], {"x": 0.0, "y": 0.0, "width": 200, "height": 160})
        self.assertEqual(result["nodes"]["first"], {"x": 10.0, "y": 10.0, "width": 50.0, "height": 20.0})
        self.assertEqual(result["nodes"]["second"], {"x": 10.0, "y": 35.0, "width": 180.0, "height": 30.0})

    def test_column_stretches_auto_cross_size_but_preserves_explicit_width(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "column", "padding": 10}, "children": ["auto", "fixed"]},
            "auto": {"type": "text", "text": "Auto width", "layout": {"height": 20}},
            "fixed": {"type": "spacer", "layout": {"width": 50, "height": 20}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 200, 100)

        self.assertEqual(result["nodes"]["auto"]["width"], 180.0)
        self.assertEqual(result["nodes"]["fixed"]["width"], 50.0)

    def test_row_distributes_remaining_space_by_grow_weight(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "row", "padding": 10, "gap": 10}, "children": ["fixed", "one", "two"]},
            "fixed": {"type": "spacer", "layout": {"width": 50, "height": "fill"}},
            "one": {"type": "spacer", "layout": {"grow": 1, "height": "fill"}},
            "two": {"type": "spacer", "layout": {"grow": 2, "height": "fill"}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 300, 100)

        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["nodes"]["fixed"]["width"], 50.0)
        self.assertEqual(result["nodes"]["one"], {"x": 70.0, "y": 10.0, "width": 70.0, "height": 80.0})
        self.assertEqual(result["nodes"]["two"], {"x": 150.0, "y": 10.0, "width": 140.0, "height": 80.0})

    def test_text_metrics_are_deterministic_and_wrap_to_parent_width(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "column", "padding": 10}, "children": ["label"]},
            "label": {"type": "text", "text": "12345678901234567890", "style": {"fontSize": 10, "lineHeight": 12}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 100, 100)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["textMeasurement"], "browser")
        self.assertIn("browser-text-metrics:label", result["diagnostics"])

    def test_overlay_honors_authored_parent_edge_constraints(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "overlay", "padding": 10}, "children": ["frame"]},
            "frame": {"type": "spacer", "layout": {"position": "absolute", "left": 15, "right": 25, "top": 20, "bottom": 30}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 200, 160)

        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["nodes"]["frame"], {"x": 25.0, "y": 30.0, "width": 140.0, "height": 90.0})

    def test_projection_contexts_include_render_variants_without_mutating_ir(self) -> None:
        ir = {
            "version": 1,
            "viewport": {"width": 200, "height": 100},
            "screens": [{"id": "home", "name": "Home", "root": "root", "scenarios": [{"id": "large", "nodeOverrides": {"label": {"layout": {"height": 40}}}}]}],
            "nodes": {
                "root": {"type": "container", "layout": {"direction": "column", "width": "fill", "height": "fill"}, "children": ["label"]},
                "label": {"type": "text", "text": "Hello", "layout": {"height": 20}},
            },
            "tokens": {},
            "themes": {"defaultThemeId": "light", "items": [{"id": "light", "nodeOverrides": {}, "tokenOverrides": {}}]},
            "scenarioFixtures": {},
            "review": {"versions": [{"id": "baseline", "nodeOverrides": {}}, {"id": "proposal", "parent": "baseline", "nodeOverrides": {"label": {"layout": {"height": 30}}}}]},
        }
        original = copy.deepcopy(ir)

        projection = build_projection_geometry(ir)

        self.assertEqual(ir, original)
        self.assertEqual(validate_projection_geometry(projection), [])
        baseline = projection["contexts"][context_key("home", "baseline", "light", "default")]
        proposal = projection["contexts"][context_key("home", "proposal", "light", "default")]
        scenario = projection["contexts"][context_key("home", "proposal", "light", "large")]
        self.assertEqual(baseline["nodes"]["label"]["height"], 20.0)
        self.assertEqual(proposal["nodes"]["label"]["height"], 30.0)
        self.assertEqual(scenario["nodes"]["label"]["height"], 40.0)

    def test_unsupported_layout_is_partial_instead_of_claiming_geometry(self) -> None:
        nodes = {
            "root": {"type": "container", "layout": {"direction": "grid"}, "children": ["child"]},
            "child": {"type": "spacer", "layout": {"width": 10, "height": 10}},
        }

        result = LayoutSolver(nodes, {}).solve("root", 100, 100)

        self.assertEqual(result["status"], "partial")
        self.assertTrue(any(item.startswith("unsupported-direction:root:grid") for item in result["diagnostics"]))

    def test_preview_embeds_projection_geometry_without_writing_it_to_source_ir(self) -> None:
        ir = {
            "version": 1,
            "project": {"name": "Geometry"},
            "viewport": {"width": 120, "height": 80},
            "screens": [{"id": "home", "name": "Home", "root": "root"}],
            "nodes": {"root": {"type": "container", "layout": {"width": "fill", "height": "fill"}, "children": []}},
            "tokens": {},
        }

        preview = render_html(ir)

        self.assertNotIn("projectionGeometry", ir)
        self.assertIn('"projectionGeometry":{"version":1,"model":"deterministic-box-v2"', preview)
        self.assertIn("data-layout-model=", preview)
        self.assertIn("geometryContext?.nodes?.[id]", preview)


if __name__ == "__main__":
    unittest.main()
