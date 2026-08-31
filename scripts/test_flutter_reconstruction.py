#!/usr/bin/env python3
"""Regression coverage for repository-scale Flutter reconstruction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scan_ui import scan, starter_ir


class FlutterReconstructionTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "pubspec.yaml").write_text("name: fixture\nflutter:\n  uses-material-design: true\n", encoding="utf-8")
        (root / "lib" / "l10n").mkdir(parents=True)
        (root / "lib" / "l10n" / "app_en.arb").write_text(
            json.dumps({"marketTitle": "Market", "openLabel": "Open"}),
            encoding="utf-8",
        )
        (root / "lib" / "router.dart").write_text(
            """import 'package:flutter/widgets.dart';
GoRouter router = GoRouter(routes: [
  GoRoute(path: '/game', builder: (_, __) => const HomePage(), routes: [
    GoRoute(path: 'market', builder: (_, __) => const MarketPage()),
  ]),
]);
""",
            encoding="utf-8",
        )
        (root / "lib" / "pages.dart").write_text(
            """import 'package:flutter/material.dart';
class HomePage extends ConsumerWidget {
  const HomePage();
  Widget build(BuildContext context, WidgetRef ref) => const Text('Home');
}
class MarketPage extends StatelessWidget {
  const MarketPage();
  Widget build(BuildContext context) => RsScreen(
    title: context.l10n.marketTitle,
    body: const MarketCard(label: 'Equipment'),
  );
}
class MarketCard extends StatelessWidget {
  const MarketCard({required this.label});
  final String label;
  Widget build(BuildContext context) => Card(
    child: Column(children: [Text(label), FilledButton(onPressed: () {}, child: Text(context.l10n.openLabel))]),
  );
}
class RsScreen extends StatelessWidget {
  const RsScreen({required this.title, required this.body});
  final String title;
  final Widget body;
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(title)),
    body: SafeArea(child: body),
  );
}
class DecorativeSparkle extends StatelessWidget {
  const DecorativeSparkle();
  Widget build(BuildContext context) => const SizedBox(width: 4, height: 4);
}
""",
            encoding="utf-8",
        )
        (root / "docs").mkdir()
        (root / "docs" / "prototype.html").write_text("<section id='fake'>Fake docs UI</section>", encoding="utf-8")
        (root / "ios" / "Runner" / "Base.lproj").mkdir(parents=True)
        (root / "ios" / "Runner" / "Base.lproj" / "LaunchScreen.storyboard").write_text(
            '<document targetRuntime="iOS.CocoaTouch"><viewController id="launch"/></document>',
            encoding="utf-8",
        )

    def test_flutter_primary_project_uses_routes_and_component_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            result = scan(root)
            ir = starter_ir(result)

        self.assertEqual(result["primaryPlatforms"], ["flutter"])
        self.assertEqual(ir["design"]["targetPlatforms"], ["flutter"])
        self.assertEqual({item["route"] for item in result["routes"]}, {"/game", "/game/market"})
        self.assertEqual({item["name"] for item in ir["screens"]}, {"HomePage", "MarketPage"})
        self.assertNotIn("DecorativeSparkle", {item["name"] for item in ir["screens"]})
        self.assertNotIn("RsScreen", {item["name"] for item in ir["screens"]})
        market = next(item for item in ir["screens"] if item["name"] == "MarketPage")
        self.assertEqual(market["route"], "/game/market")
        reachable = []
        pending = [market["root"]]
        while pending:
            node_id = pending.pop()
            node = ir["nodes"][node_id]
            reachable.append(node)
            pending.extend(node.get("children", []))
        self.assertTrue({"Market", "Equipment", "Open"}.issubset({node.get("text") for node in reachable}))
        self.assertTrue({"RsScreen", "MarketCard", "FilledButton"}.issubset({node.get("component") for node in reachable}))
        self.assertFalse(any(node.get("component") == "UntranslatedSource" for node in reachable))

    def test_consumer_stateful_widget_uses_its_state_build_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pubspec.yaml").write_text("name: fixture\nflutter:\n", encoding="utf-8")
            (root / "lib").mkdir()
            (root / "lib" / "counter_page.dart").write_text(
                """import 'package:flutter/material.dart';
class CounterPage extends ConsumerStatefulWidget { const CounterPage(); }
class _CounterPageState extends ConsumerState<CounterPage> {
  Widget build(BuildContext context) { return Text('Counter'); }
}
""",
                encoding="utf-8",
            )
            ir = starter_ir(scan(root))

        self.assertEqual([item["name"] for item in ir["screens"]], ["CounterPage"])
        self.assertIn("Counter", {node.get("text") for node in ir["nodes"].values()})


if __name__ == "__main__":
    unittest.main()
