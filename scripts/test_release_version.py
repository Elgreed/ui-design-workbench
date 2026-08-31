#!/usr/bin/env python3
"""Tests for tag-driven release version validation."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from check_release_version import validate_release_version


class ReleaseVersionTests(unittest.TestCase):
    def write_project(self, root: Path, package: str, cli: str, changelog: str) -> None:
        (root / "scripts").mkdir()
        (root / "pyproject.toml").write_text(f'[project]\nname = "sample"\nversion = "{package}"\n', encoding="utf-8")
        (root / "scripts" / "uidw.py").write_text(f'CLI_VERSION = "{cli}"\n', encoding="utf-8")
        (root / "README.md").write_text(f"Current CLI version: `{package}`.\n", encoding="utf-8")
        (root / "README.ru.md").write_text(f"Текущая версия CLI: `{package}`.\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")

    def test_consistent_release_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_project(root, "1.2.3", "1.2.3", "## [1.2.3] - 2026-08-29\n")
            self.assertEqual(validate_release_version(root, "v1.2.3"), [])

    def test_mismatched_or_unreleased_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_project(root, "1.2.2", "1.2.1", "## [Unreleased]\n")
            errors = validate_release_version(root, "v1.2.3")
            self.assertEqual(len(errors), 5)

    def test_stale_readme_versions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_project(root, "1.2.3", "1.2.3", "## [1.2.3] - 2026-08-29\n")
            (root / "README.md").write_text("Current CLI version: `0.0.0`.\n", encoding="utf-8")
            (root / "README.ru.md").write_text("Текущая версия CLI: `0.0.0`.\n", encoding="utf-8")

            errors = validate_release_version(root, "v1.2.3")

            self.assertTrue(any("README.md" in error for error in errors))
            self.assertTrue(any("README.ru.md" in error for error in errors))

    def test_tag_format_is_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn("vX.Y.Z", validate_release_version(Path(directory), "1.2.3")[0])

    def test_repository_version_is_documented(self) -> None:
        root = Path(__file__).resolve().parent.parent
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        version_match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject, re.MULTILINE)
        self.assertIsNotNone(version_match)
        version = version_match.group(1)
        self.assertEqual(validate_release_version(root, f"v{version}"), [])

    def test_repository_documents_mandatory_tag_driven_release_completion(self) -> None:
        root = Path(__file__).resolve().parent.parent
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        releasing = (root / "RELEASING.md").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        self.assertIn("create an annotated `vX.Y.Z` tag", agents)
        self.assertIn("verify that the tag created a `Release` GitHub Actions run", agents)
        self.assertIn('git push origin "v${VERSION}"', releasing)
        self.assertIn("test -n \"${RUN_ID}\"", releasing)
        self.assertIn('gh run watch "${RUN_ID}" --exit-status', releasing)
        self.assertIn('tags:\n      - "v*.*.*"', workflow)
        self.assertIn("python scripts/verify_workbench_goldens.py", workflow)


if __name__ == "__main__":
    unittest.main()
