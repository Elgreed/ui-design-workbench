#!/usr/bin/env python3
"""Fail a release when its tag, package, CLI, and changelog versions disagree."""

from __future__ import annotations

import re
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from pathlib import Path


def validate_release_version(root: Path, tag: str) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return [f"Release tag must match vX.Y.Z, got {tag!r}"]
    version = tag[1:]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = str(project.get("project", {}).get("version") or "")
    if package_version != version:
        errors.append(f"pyproject.toml version is {package_version!r}, expected {version!r}")
    cli_source = (root / "scripts" / "uidw.py").read_text(encoding="utf-8")
    cli_match = re.search(r'^CLI_VERSION\s*=\s*["\']([^"\']+)["\']', cli_source, re.MULTILINE)
    cli_version = cli_match.group(1) if cli_match else ""
    if cli_version != version:
        errors.append(f"CLI_VERSION is {cli_version!r}, expected {version!r}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE):
        errors.append(f"CHANGELOG.md has no dated [{version}] release section")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_release_version.py vX.Y.Z", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    errors = validate_release_version(root, sys.argv[1])
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Release version {sys.argv[1]} is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
