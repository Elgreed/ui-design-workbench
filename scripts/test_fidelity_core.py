from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fidelity_adapters import SourceContext, registered_adapters
from fidelity_core import TokenResolver, baseline_hash, fidelity_report, property_evidence, seal_baseline, validate_strict_ir
from scan_ui import scan, starter_ir


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "fixtures" / "golden"


def adapter_result(name: str):
    fixture = GOLDEN / name
    source_dir = fixture / "source"
    source = next(source_dir.glob("*.html"), None) or next(source_dir.glob("*.kt"))
    text = source.read_text(encoding="utf-8")
    context = SourceContext(ROOT, source, source.relative_to(ROOT).as_posix(), text, ("web",) if source.suffix == ".html" else ("android-compose",), "screen")
    adapter = next(item for item in registered_adapters() if item.supports(context))
    return adapter.translate(context), json.loads((fixture / "expected.json").read_text(encoding="utf-8"))


class FidelityCoreTests(unittest.TestCase):
    def test_legacy_ir_is_not_reported_as_a_pass(self):
        report = fidelity_report({"version": 1, "nodes": {"root": {"type": "text", "text": "Legacy"}}})
        self.assertEqual(report["status"], "not-applicable")
        self.assertFalse(report["applicable"])
        self.assertIn("schema 0.3", report["applicabilityReason"])

    def test_web_golden(self):
        result, expected = adapter_result("web-basic")
        self.assertEqual(result.adapter, expected["adapter"])
        self.assertEqual([item["id"] for item in result.screens], expected["screens"])
        self.assertEqual(sorted(set(node["type"] for node in result.nodes.values())), expected["nodeTypes"])
        flattened = TokenResolver(result.tokens).resolved_tokens()
        for name, value in expected["tokens"].items():
            self.assertEqual(flattened[name], value)
        for target in expected["requiredProvenance"]:
            node_id, path = target.split(":", 1)
            self.assertIn(path, result.nodes[node_id]["provenance"])

    def test_compose_golden(self):
        result, expected = adapter_result("compose-basic")
        self.assertEqual(result.adapter, expected["adapter"])
        self.assertEqual([item["id"] for item in result.screens], expected["screens"])
        self.assertTrue(set(expected["nodeTypes"]).issubset(set(node["type"] for node in result.nodes.values())))
        self.assertGreaterEqual(len(result.nodes), expected["minimumNodes"])
        flattened = TokenResolver(result.tokens).resolved_tokens()
        for name, value in expected["tokens"].items():
            self.assertEqual(flattened[name], value)
        self.assertTrue(any(expected["requiredProperty"] in node.get("provenance", {}) for node in result.nodes.values()))

    def test_compose_preserves_solver_constraints(self):
        source = ROOT / "Sample.kt"
        text = '''
@Composable
fun Sample() {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Fixed", modifier = Modifier.width(40.dp))
        Text("Flexible", modifier = Modifier.fillMaxWidth().weight(2f), fontSize = 14.sp, lineHeight = 18.sp)
    }
}
'''
        context = SourceContext(ROOT, source, "Sample.kt", text, ("android-compose",), "screen")
        adapter = next(item for item in registered_adapters() if item.id == "compose")

        result = adapter.translate(context)

        row = next(node for node in result.nodes.values() if node.get("component") == "Row")
        flexible = next(node for node in result.nodes.values() if node.get("text") == "Flexible")
        self.assertEqual(row["layout"]["gap"], "12px")
        self.assertEqual(flexible["layout"]["width"], "fill")
        self.assertEqual(flexible["layout"]["grow"], 2)
        self.assertEqual(flexible["style"]["fontSize"], "14px")
        self.assertEqual(flexible["style"]["lineHeight"], "18px")

    def test_multiplatform_adapter_pack_golden(self):
        fixture = GOLDEN / "platform-pack"
        expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
        for case in expected["cases"]:
            with self.subTest(adapter=case["adapter"], source=case["source"]):
                source = fixture / case["source"]
                context = SourceContext(ROOT, source, source.relative_to(ROOT).as_posix(), source.read_text(encoding="utf-8"), tuple(case["platforms"]), "screen")
                adapter = next(item for item in registered_adapters() if item.supports(context))
                result = adapter.translate(context)
                self.assertEqual(adapter.id, case["adapter"])
                self.assertIn(case["screen"], [item["id"] for item in result.screens])
                screen = next(item for item in result.screens if item["id"] == case["screen"])
                self.assertEqual(screen["platform"], case["platform"])
                node_types = {node["type"] for node in result.nodes.values()}
                self.assertTrue(set(case["types"]).issubset(node_types), (case, node_types))
                for node in result.nodes.values():
                    for path, evidence in node.get("provenance", {}).items():
                        self.assertTrue(evidence.get("file"), (case["source"], path))
                        self.assertEqual(evidence.get("adapter"), adapter.id)
                ir = {
                    "version": 1, "fidelity": {"schemaVersion": "0.3"}, "screens": result.screens,
                    "screenTree": [{"screenId": item["id"], "label": item["name"]} for item in result.screens],
                    "nodes": result.nodes, "tokens": result.tokens,
                    "themes": {"defaultThemeId": "light", "items": [{"id": "light", "label": "Light", "kind": "light", "tokenOverrides": {}, "nodeOverrides": {}}]},
                    "scenarioFixtures": {}, "review": {"baselineVersion": "baseline", "versions": [{"id": "baseline", "kind": "baseline", "nodeOverrides": {}}]},
                }
                seal_baseline(ir)
                self.assertEqual(validate_strict_ir(ir), [])

    def test_multiplatform_pack_scans_into_one_strict_ir(self):
        root = GOLDEN / "platform-pack"
        ir = starter_ir(scan(root))
        report = fidelity_report(ir)
        self.assertEqual(report["status"], "pass", report["strictErrors"])
        platforms = {screen["platform"] for screen in ir["screens"]}
        self.assertTrue({"android", "ios", "windows", "flutter", "web"}.issubset(platforms))
        self.assertNotIn("android-tv", platforms)
        self.assertNotIn("react-native", platforms)
        dark = next(item for item in ir["themes"]["items"] if item["id"] == "dark")
        self.assertEqual(dark["tokenOverrides"]["colors"]["surface"]["value"], "#121212")
        self.assertEqual(ir["tokens"]["spacing"]["space_md"]["value"], "16px")

    def test_token_alias_and_cycle(self):
        resolver = TokenResolver({"colors": {"brand": "#123456", "button": "$colors.brand"}})
        self.assertEqual(resolver.resolve("$colors.button"), "#123456")
        cycle = TokenResolver({"colors": {"a": "$colors.b", "b": "$colors.a"}})
        self.assertEqual(cycle.resolve("$colors.a"), "$colors.a")
        self.assertEqual(cycle.diagnostics[0].code, "token-cycle")

    def test_baseline_tamper_is_rejected(self):
        evidence = property_evidence("Screen.kt", 1, 'Text("Hello")', "compose")
        ir = {
            "version": 1,
            "fidelity": {"schemaVersion": "0.3"},
            "screens": [{"id": "home", "name": "Home", "root": "root"}],
            "screenTree": [{"screenId": "home", "label": "Home"}],
            "nodes": {"root": {"type": "text", "text": "Hello", "style": {}, "layout": {}, "children": [], "source": {"file": "Screen.kt", "line": 1}, "confidence": "exact", "provenance": {"text": evidence}}},
            "tokens": {}, "themes": {}, "scenarioFixtures": {},
            "review": {"baselineVersion": "baseline", "versions": [{"id": "baseline", "kind": "baseline", "nodeOverrides": {}}]},
        }
        seal_baseline(ir)
        self.assertEqual(validate_strict_ir(ir), [])
        original = baseline_hash(ir)
        ir["nodes"]["root"]["text"] = "Changed"
        self.assertNotEqual(baseline_hash(ir), original)
        self.assertEqual(fidelity_report(ir)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
