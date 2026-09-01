from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fidelity_adapters import SourceContext, registered_adapters
from fidelity_core import fidelity_report, seal_baseline, validate_strict_ir
from render_preview import fidelity_audit
from scan_ui import scan, starter_ir


ANDROID_NS = "http://schemas.android.com/apk/res/android"
APP_NS = "http://schemas.android.com/apk/res-auto"


class AndroidXmlSupportTests(unittest.TestCase):
    def android_adapter(self, path: Path, text: str, role: str = "screen"):
        context = SourceContext(path.parents[5], path, path.as_posix(), text, ("android-views",), role)
        adapter = next(item for item in registered_adapters() if item.id == "android-xml")
        return adapter.translate(context)

    def test_data_binding_wrapper_is_not_rendered_as_custom_ui(self) -> None:
        text = f'''<layout xmlns:android="{ANDROID_NS}" xmlns:app="{APP_NS}">
  <data><variable name="title" type="String" /></data>
  <androidx.constraintlayout.widget.ConstraintLayout
      android:layout_width="match_parent" android:layout_height="match_parent">
    <TextView android:id="@+id/title" android:layout_width="wrap_content"
        android:layout_height="wrap_content" android:text="@string/welcome"
        app:layout_constraintStart_toStartOf="parent" />
  </androidx.constraintlayout.widget.ConstraintLayout>
</layout>'''
        path = Path("app/src/main/res/layout/fragment_login.xml")
        result = self.android_adapter(path, text)
        self.assertEqual([screen["id"] for screen in result.screens], ["fragment-login"])
        components = {node.get("component") for node in result.nodes.values()}
        self.assertNotIn("layout", components)
        self.assertNotIn("data", components)
        text_node = next(node for node in result.nodes.values() if node.get("type") == "text")
        self.assertEqual(text_node["text"], "@string/welcome")
        self.assertIn("unresolved-constraint-equations", {item["reason"] for item in result.unsupported})
        self.assertIn("unresolved-android-resource", {item["reason"] for item in result.unsupported})

    def test_android_resources_keep_strings_out_of_spacing(self) -> None:
        text = f'''<resources>
  <string name="welcome">Добро пожаловать</string>
  <color name="overlay">#66000000</color>
  <dimen name="space_md">16dp</dimen>
  <dimen name="body_size">16sp</dimen>
</resources>'''
        path = Path("app/src/main/res/values/resources.xml")
        result = self.android_adapter(path, text, "theme")
        self.assertEqual(result.tokens["strings"]["welcome"]["value"], "Добро пожаловать")
        self.assertNotIn("welcome", result.tokens["spacing"])
        self.assertEqual(result.tokens["colors"]["overlay"]["value"], "#66000000")
        self.assertIn("body_size", result.tokens["typography"])

    def test_unsupported_placeholder_fails_fidelity_but_remains_renderable_as_draft(self) -> None:
        ir = {
            "version": 1,
            "fidelity": {"schemaVersion": "0.3"},
            "screens": [{"id": "main", "name": "Main", "root": "root"}],
            "screenTree": [{"screenId": "main", "label": "Main"}],
            "nodes": {
                "root": {
                    "type": "custom", "component": "RuntimeView", "layout": {}, "style": {}, "children": [],
                    "source": {"file": "fragment_main.xml", "line": 1}, "confidence": "unsupported", "provenance": {},
                }
            },
            "tokens": {}, "themes": {}, "scenarioFixtures": {},
            "review": {"baselineVersion": "baseline", "versions": [{"id": "baseline", "kind": "baseline", "nodeOverrides": {}}]},
        }
        seal_baseline(ir)
        self.assertEqual(validate_strict_ir(ir), [])
        report = fidelity_report(ir)
        self.assertEqual(report["status"], "fail")
        self.assertIn("unsupported placeholder", report["fidelityErrors"][0])

    def test_reconstruction_does_not_treat_bare_inherited_appearance_as_complete(self) -> None:
        ir = {
            "design": {"mode": "reconstruct", "targetPlatforms": ["android"], "decisions": []},
            "fidelity": {"status": "translated", "sourceDerived": True},
            "screens": [{"id": "main", "name": "Main", "root": "button", "platform": "android"}],
            "nodes": {
                "button": {
                    "type": "button", "text": "Continue", "inheritsAppearance": True,
                    "layout": {}, "style": {}, "children": [], "source": {"file": "main.xml", "line": 1},
                    "confidence": "high", "provenance": {},
                }
            },
            "tokens": {}, "componentCatalog": {"components": []},
        }
        self.assertEqual(fidelity_audit(ir)["appearanceCoverage"], 0)

    def test_scan_uses_navigation_destinations_and_excludes_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = root / "app/src/main/res/layout"
            landscape_layout = root / "app/src/main/res/layout-land"
            navigation = root / "app/src/main/res/navigation"
            values = root / "app/src/main/res/values"
            kotlin = root / "app/src/main/java/sample"
            for folder in (layout, landscape_layout, navigation, values, kotlin):
                folder.mkdir(parents=True, exist_ok=True)
            (layout / "activity_main.xml").write_text(
                f'<FrameLayout xmlns:android="{ANDROID_NS}" android:layout_width="match_parent" android:layout_height="match_parent" />',
                encoding="utf-8",
            )
            (layout / "fragment_login.xml").write_text(
                f'<FrameLayout xmlns:android="{ANDROID_NS}" android:layout_width="match_parent" android:layout_height="match_parent"><TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:text="@string/welcome" /><include layout="@layout/cell_vehicle" /></FrameLayout>',
                encoding="utf-8",
            )
            (landscape_layout / "fragment_login.xml").write_text(
                f'<FrameLayout xmlns:android="{ANDROID_NS}" android:layout_width="match_parent" android:layout_height="match_parent"><TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:text="Landscape" /></FrameLayout>',
                encoding="utf-8",
            )
            (layout / "cell_vehicle.xml").write_text(
                f'<TextView xmlns:android="{ANDROID_NS}" android:layout_width="match_parent" android:layout_height="wrap_content" android:text="Vehicle" />',
                encoding="utf-8",
            )
            (values / "strings.xml").write_text('<resources><string name="welcome">Welcome</string></resources>', encoding="utf-8")
            (kotlin / "LoginFragment.kt").write_text(
                "class LoginFragment : BaseLoginFragment()",
                encoding="utf-8",
            )
            (kotlin / "BaseLoginFragment.kt").write_text(
                "abstract class BaseLoginFragment : BaseFragment<FragmentLoginBinding>(R.layout.fragment_login)",
                encoding="utf-8",
            )
            (kotlin / "MainActivity.kt").write_text(
                "class MainActivity : Activity() { fun view() = ActivityMainBinding.inflate(layoutInflater) }",
                encoding="utf-8",
            )
            (navigation / "nav_graph.xml").write_text(f'''<navigation xmlns:android="{ANDROID_NS}" xmlns:app="{APP_NS}" android:id="@+id/main_graph" app:startDestination="@id/loginFragment">
  <fragment android:id="@+id/loginFragment" android:name="sample.LoginFragment" android:label="Login">
    <action android:id="@+id/action_login_to_main" app:destination="@id/mainActivity" />
  </fragment>
  <activity android:id="@+id/mainActivity" android:name="sample.MainActivity" android:label="Main" />
</navigation>''', encoding="utf-8")

            inventory = scan(root)
            self.assertEqual({item["name"] for item in inventory["screens"]}, {"LoginFragment", "MainActivity"})
            self.assertEqual(inventory["navigationTargets"][0]["source"], "@id/loginFragment")
            self.assertEqual(inventory["navigationTargets"][0]["target"], "@id/mainActivity")
            self.assertTrue(any(item["name"] == "CellVehicle" for item in inventory["components"]))

            ir = starter_ir(inventory)
            self.assertEqual({screen.get("fragment") for screen in ir["screens"]}, {"@id/loginFragment", "@id/mainActivity"})
            self.assertEqual([screen["id"] for screen in ir["screens"]].count("fragment-login"), 1)

            def tree_leaves(items, groups=()):
                leaves = []
                for item in items:
                    if item.get("screenId"):
                        leaves.append((item["screenId"], groups))
                    else:
                        leaves.extend(tree_leaves(item.get("children", []), (*groups, item.get("label", ""))))
                return leaves

            login_leaves = [item for item in tree_leaves(ir["screenTree"]) if item[0] == "fragment-login"]
            self.assertEqual(len(login_leaves), 1)
            self.assertIn("main_graph", login_leaves[0][1])
            self.assertTrue(any(edge["kind"] == "navigate" for edge in ir["navigationGraph"]["edges"]))
            self.assertFalse(any(screen.get("source", {}).get("file", "").endswith("nav_graph.xml") for screen in ir["screens"]))
            self.assertTrue(any(node.get("text") == "Welcome" for node in ir["nodes"].values()))
            self.assertTrue(any(node.get("text") == "Vehicle" for node in ir["nodes"].values()))
            self.assertFalse(any(item["reason"] == "unresolved-android-include" for item in ir["fidelity"]["unsupported"]))
            self.assertEqual(validate_strict_ir(ir), [])

    def test_layout_qualifier_variants_share_one_canonical_screen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default_layout = root / "app/src/main/res/layout"
            landscape_layout = root / "app/src/main/res/layout-land"
            for folder in (default_layout, landscape_layout):
                folder.mkdir(parents=True, exist_ok=True)
            markup = f'<FrameLayout xmlns:android="{ANDROID_NS}" android:layout_width="match_parent" android:layout_height="match_parent" />'
            (default_layout / "scene_intro.xml").write_text(markup, encoding="utf-8")
            (landscape_layout / "scene_intro.xml").write_text(markup, encoding="utf-8")

            inventory = scan(root)
            ir = starter_ir(inventory)
            screens = [screen for screen in ir["screens"] if screen["id"] == "scene-intro"]

            self.assertEqual(len(screens), 1)
            self.assertEqual({item["qualifier"] for item in screens[0]["resourceVariants"]}, {"default", "land"})
            self.assertFalse(any(screen["id"] == "sceneintro-land" for screen in ir["screens"]))
            self.assertEqual(validate_strict_ir(ir), [])


if __name__ == "__main__":
    unittest.main()
