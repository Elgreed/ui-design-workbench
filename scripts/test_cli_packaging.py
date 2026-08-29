#!/usr/bin/env python3
"""Regression tests for CLI-first packaging and provider-neutral handoff."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import coverage_report as coverage_module
import uidw as uidw_module
from render_preview import render_html
from uidw import finding_report, help_topic, install_skill, pack_artifact, prepare_agent_job, read_json, unpack_artifact, validate_artifact, write_json


ROOT = Path(__file__).resolve().parent.parent


class CliPackagingTests(unittest.TestCase):
    def test_context_command_auto_initializes_and_then_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "sample"
            repo.mkdir()
            (repo / "Home.tsx").write_text("import React from 'react'; export function HomeScreen(){ return <main>Home</main>; }", encoding="utf-8")
            env = {**os.environ, "UIDW_CACHE_HOME": str(root / "cache")}
            command = [sys.executable, str(ROOT / "scripts" / "uidw.py"), "--repo", str(repo), "--json", "context"]

            first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False)
            second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["initialization"]["status"], "created")
            self.assertEqual(json.loads(second.stdout)["initialization"]["status"], "reused")

    def test_review_command_builds_first_mockups_without_manual_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "sample"
            repo.mkdir()
            (repo / "Home.tsx").write_text("import React from 'react'; export function HomeScreen(){ return <main><h1>Home</h1></main>; }", encoding="utf-8")
            output_dir = root / "review"
            env = {**os.environ, "UIDW_CACHE_HOME": str(root / "cache")}
            command = [
                sys.executable,
                str(ROOT / "scripts" / "uidw.py"),
                "--repo",
                str(repo),
                "--json",
                "review",
                "--no-open",
                "--output-dir",
                str(output_dir),
            ]

            completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["initialization"]["status"], "created")
            self.assertTrue((output_dir / "ui-preview.html").is_file())

    def test_legacy_fidelity_is_not_applicable_without_failing_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ir_path = root / "ui-ir.json"
            write_json(ir_path, {"version": 1, "screens": [], "nodes": {}})
            with mock.patch("coverage_report.build_report", return_value={"status": "pass"}), mock.patch("validate_platform_profiles.validate_profiles", return_value={"status": "pass"}), mock.patch.object(uidw_module, "fidelity_report", return_value={"status": "not-applicable"}):
                result = validate_artifact(ir_path, root / "validation")
            self.assertEqual(result["status"], "pass")

    def test_projection_coverage_never_enables_ui_quality_gates(self) -> None:
        audit = {
            "status": "reviewable",
            "reasons": [],
            "screenCoverage": 1,
            "routeCoverage": 1,
            "navigationCoverage": 1,
            "componentCoverage": 1,
            "appearanceCoverage": 1,
            "evidenceCoverage": 0,
            "semanticCoverage": 0,
            "standardCoverage": 0,
            "targetCoverage": 0,
            "contrastCoverage": 0,
            "stateCoverage": 0,
        }
        ir = {"design": {"mode": "redesign"}, "screens": [], "screenTree": [], "nodes": {}}
        with mock.patch.object(coverage_module, "fidelity_audit", return_value=audit), mock.patch.object(coverage_module, "validate_profiles", return_value={"status": "pass", "issues": []}):
            projection = coverage_module.build_report(ir, "projection")
            review = coverage_module.build_report(ir, "review")
        projection_gates = {item["id"] for item in projection["gates"]}
        review_gates = {item["id"] for item in review["gates"]}
        self.assertEqual(projection["purpose"], "projection")
        self.assertTrue({"targets", "contrast", "semantics", "standards"}.isdisjoint(projection_gates))
        self.assertTrue({"targets", "contrast", "semantics", "standards"}.issubset(review_gates))

    def test_review_uses_effective_defaults_without_blocking_on_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {"config": root / "config.json", "dir": root}
            workbench = {
                "version": 1,
                "status": "pass",
                "render": {"status": "rendered"},
                "check": {"status": "pass"},
                "previewFile": str(root / "ui-preview.html"),
                "url": "file:///preview",
            }
            output = io.StringIO()
            argv = ["uidw", "--repo", str(root), "--json", "review", "--no-open"]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(uidw_module, "state_paths", return_value=paths), mock.patch.object(uidw_module, "load_config", return_value={}), mock.patch.object(uidw_module, "build_workbench", return_value=workbench) as build_mock, contextlib.redirect_stdout(output):
                exit_code = uidw_module.main()
            self.assertEqual(exit_code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["workflow"], "review")
            self.assertIn("детализация не выбрана", result["configurationNotice"])
            self.assertEqual(build_mock.call_args.args[-1], "review")

    def test_primary_help_hides_advanced_commands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "uidw.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("review", completed.stdout)
        self.assertIn("apply", completed.stdout)
        self.assertIn("install-skill", completed.stdout)
        self.assertNotIn("==SUPPRESS==", completed.stdout)
        self.assertNotIn("visual-test", completed.stdout)

    def test_fidelity_capabilities_do_not_require_initialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "uidw.py"), "--repo", str(root), "--json", "fidelity", "capabilities"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        families = {family for adapter in payload["adapters"] for family in adapter["platforms"]}
        self.assertEqual(families, {"android", "ios", "macos", "windows", "flutter", "web"})

    def test_task_help_covers_primary_review_and_apply_commands(self) -> None:
        self.assertIn("uidw workbench", help_topic("overview")["text"])
        self.assertIn("uidw review", help_topic("overview")["text"])
        self.assertIn("три шага", help_topic("review")["text"])
        self.assertIn("не оценивает UI/UX", help_topic("workbench")["text"])
        self.assertIn("--direct", help_topic("apply")["text"])
        self.assertIn("workbench", help_topic("advanced")["text"])

    def test_finding_report_requires_verification_for_completion(self) -> None:
        finding = {"id": "f-1", "title": "Issue", "severity": "high", "screenId": "home", "status": "resolved"}
        ir = {"review": {"audit": {"findings": [finding], "findingDecisions": {}}, "versions": []}}
        self.assertEqual(finding_report(ir)["findings"][0]["status"], "pending")
        finding["verification"] = {"result": "pass"}
        self.assertEqual(finding_report(ir)["findings"][0]["status"], "verified")

    def test_apply_requires_an_approved_proposal_unless_direct_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "screen.html"
            source.write_text("<button>Save</button>", encoding="utf-8")
            ir_path = root / "ui-ir.json"
            ir = {
                "project": {"name": "Sample", "root": str(root)},
                "review": {
                    "audit": {
                        "findings": [{"id": "f-1", "title": "Issue", "screenId": "home", "sourceTarget": "screen.html"}],
                        "findingDecisions": {"f-1": "accepted"},
                    },
                    "versions": [],
                },
                "screens": [{"id": "home"}],
            }
            write_json(ir_path, ir)
            with self.assertRaisesRegex(ValueError, "new mockup"):
                prepare_agent_job(root, ir_path, ir, "implementation", root / "blocked.json")
            direct = prepare_agent_job(root, ir_path, ir, "implementation", root / "direct.json", direct=True)
            self.assertEqual(direct["status"], "prepared")
            payload = read_json(root / "direct.json", {})
            self.assertTrue(payload["directSourceAuthorization"])

    def test_console_entry_and_public_schemas_exist(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["scripts"]["uidw"], "uidw:main")
        self.assertEqual(config["project"]["scripts"]["uidw-mcp"], "uidw_mcp:main")
        self.assertIn("mcp", config["project"]["optional-dependencies"])
        for name in ("ui-graph.schema.json", "ui-agent-job.schema.json", "ui-ir.schema.json", "ui-ir.patch.schema.json", "uidw-config.schema.json", "native-render-state.schema.json"):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertIn("$schema", schema)
        data_files = config["tool"]["setuptools"]["data-files"]
        self.assertIn("SKILL.md", data_files["share/ui-design-workbench"])
        self.assertIn("references/*.md", data_files["share/ui-design-workbench/references"])
        self.assertIn("scripts/uidw.py", data_files["share/ui-design-workbench/scripts"])

    def test_packaged_skill_installs_and_updates_without_checkout_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "codex-skill"
            installed = install_skill("codex", target=target, source=ROOT)
            self.assertEqual(installed["skillInstallations"][0]["status"], "installed")
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / "references" / "agent-integrations.md").is_file())
            self.assertTrue((target / "schemas" / "ui-ir.schema.json").is_file())
            self.assertTrue((target / "scripts" / "uidw.py").is_file())
            self.assertEqual(read_json(target / ".uidw-skill.json", {})["cliVersion"], uidw_module.CLI_VERSION)

            updated = install_skill("codex", target=target, source=ROOT)
            self.assertEqual(updated["skillInstallations"][0]["status"], "updated")

    def test_skill_installer_refuses_unmanaged_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing"
            target.mkdir()
            (target / "private.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not UIDW-managed"):
                install_skill("codex", target=target, source=ROOT)
            self.assertEqual((target / "private.txt").read_text(encoding="utf-8"), "keep")

    def test_skill_is_thin_and_cli_first(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(skill.splitlines()), 120)
        self.assertIn("uidw --repo <repo> context --json", skill)
        self.assertIn("The CLI, not the skill prompt, owns scanning", skill)
        self.assertIn("ui-ir.patch.json", skill)
        self.assertIn("metadata:", skill)
        self.assertIn("compatibility:", skill)
        self.assertIn("ui_native_status", skill)

    def test_installers_cover_supported_agents(self) -> None:
        combined = (ROOT / "install.ps1").read_text(encoding="utf-8") + (ROOT / "install.sh").read_text(encoding="utf-8")
        for agent in ("codex", "claude", "cursor", "gemini", "copilot", "opencode", "agents"):
            self.assertIn(agent, combined)

    def test_generic_handoff_is_default_and_codex_is_optional(self) -> None:
        ir = {"project": {"name": "Sample"}, "screens": [], "nodes": {}, "versions": []}
        with tempfile.TemporaryDirectory() as directory:
            generic = render_html(ir, Path(directory))
            codex = render_html(ir, Path(directory), "codex")
        self.assertIn('"handoffProvider":"generic"', generic)
        self.assertIn('"handoffProvider":"codex"', codex)
        self.assertIn("open-agent-review", generic)
        self.assertIn("agent-handoff-panel", generic)
        self.assertIn('data-canvas-layer="findings"', generic)
        self.assertIn('data-view="compare"', generic)
        self.assertIn("compare-base-select", generic)
        self.assertIn("compare-target-select", generic)
        self.assertIn("resolvedFindingIdsForVersion", generic)
        self.assertIn("findingAddressedInProposal", generic)
        self.assertIn("verification.status==='verified'", generic)
        self.assertIn("Показать в исходном", generic)
        self.assertIn("version-application-status", generic)
        self.assertIn(".review-secondary-action[hidden]", generic)
        self.assertIn("diagnosticMenuAction", generic)
        self.assertNotIn("menus[0]?.querySelector('.menu-popover button')?.click()", generic)
        self.assertIn("reviewTargetRevision", generic)
        self.assertIn("targetRevision:reviewTargetRevision", generic)
        self.assertIn("if(state.staleReview)return", generic)
        self.assertIn("addEventListener('beforeunload',persist)", generic)
        self.assertNotIn("addEventListener('beforeunload',downloadFeedback", generic)
        self.assertEqual(generic.count("downloadFeedback"), 2)
        self.assertIn("interactiveActionTypes", generic)
        self.assertNotIn("Boolean(node.dataset.action)", generic)
        self.assertIn("scenario.entryScreenIds", generic)
        self.assertIn("screen.navigationEntry", generic)
        self.assertNotIn("renderFindingsV2", generic)
        self.assertNotIn("JSON.stringify({workbenchSchema,screens,nodes,themes,versions", generic)
        self.assertNotIn('data-version-visibility="before"', generic)
        self.assertIn("finding-pin-card", generic)
        self.assertIn("data-collapse-finding", generic)
        self.assertIn("finding-list-index", generic)
        self.assertIn("bindCanvasPan", generic)
        self.assertIn("data-workbench-locale", generic)
        self.assertIn('aria-label="Этапы ревью"', generic)
        self.assertIn('data-review-section="summary"', generic)
        self.assertIn('data-review-section="problems"', generic)
        self.assertIn('data-review-section="changes"', generic)
        self.assertIn("review-next-action", generic)
        self.assertIn("review-advanced-tools", generic)
        self.assertIn("review-danger-zone", generic)
        self.assertIn("versionDisplayLabel", generic)
        self.assertIn("redesignDefaultVersion", generic)
        self.assertIn("showBefore:redesignDefaultVersion?false", generic)
        self.assertIn("showAfter:redesignDefaultVersion?true", generic)
        self.assertIn("activeVersion:redesignDefaultVersion||", generic)
        self.assertIn("state.compareTargetVersion=redesignDefaultVersion||", generic)
        self.assertIn("Перейти к исправлению", generic)
        self.assertIn("state.reviewSection!=='changes'", generic)
        self.assertNotIn('class="review-launcher-action primary run-review"', generic)
        self.assertNotIn("open-codex-review", generic)
        self.assertNotIn("codex-handoff-panel", generic)
        self.assertNotIn("uiIr:ir", generic)
        self.assertIn("ui-ir.patch.json", generic)

    def test_portable_bundle_round_trip_has_no_absolute_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact"
            artifact.mkdir()
            ir_path = artifact / "ui-ir.json"
            write_json(ir_path, {"version": 1, "project": {"name": "Sample", "root": str(root / "private-source")}, "screens": [], "nodes": {}})
            (artifact / "ui-preview.html").write_text("<!doctype html><title>Sample</title>", encoding="utf-8")
            bundle = root / "sample.uidw.zip"
            result = pack_artifact(ir_path, bundle)
            self.assertEqual(result["status"], "packed")
            extracted = root / "extracted"
            unpack_artifact(bundle, extracted)
            manifest = read_json(extracted / "uidw-bundle.json", {})
            self.assertEqual(manifest["type"], "ui-design-workbench-bundle")
            self.assertTrue((extracted / "ui-ir.json").is_file())
            self.assertTrue(all(not Path(item["path"]).is_absolute() for item in manifest["files"]))
            with zipfile.ZipFile(bundle) as archive:
                self.assertNotIn(str(root), archive.read("ui-ir.json").decode("utf-8"))
                self.assertFalse(manifest["sourceIncluded"])


if __name__ == "__main__":
    unittest.main()
