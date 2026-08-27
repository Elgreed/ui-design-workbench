#!/usr/bin/env python3
"""Validate platform-profile selection and node standard references in UI IR."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from quality_common import framework_adapters, node_screen_map, platform_family, profile_catalog, read_json, target_families, write_json


def validate_profiles(ir: dict[str, Any]) -> dict[str, Any]:
    catalog = profile_catalog()
    profiles = catalog.get("profiles", {})
    adapters = catalog.get("frameworkAdapters", {})
    families = target_families(ir)
    selected = ir.get("design", {}).get("standardProfiles", {})
    issues: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}

    if not families:
        issues.append({"code": "target-platform-missing", "severity": "error", "message": "design.targetPlatforms must resolve to android, ios, or web."})

    for adapter_id in sorted(framework_adapters(ir)):
        adapter = adapters[adapter_id]
        if adapter.get("requiresExplicitTarget") and not ir.get("design", {}).get("targetPlatforms"):
            issues.append({"code": "framework-target-ambiguous", "severity": "error", "adapter": adapter_id, "message": f"{adapter_id} requires explicit design.targetPlatforms."})

    for family in sorted(families):
        selection = selected.get(family)
        if not isinstance(selection, dict):
            issues.append({"code": "profile-missing", "severity": "error", "family": family, "message": f"Missing design.standardProfiles.{family}."})
            continue
        profile_id = selection.get("id")
        if profile_id == "project":
            if not selection.get("reason"):
                issues.append({"code": "project-profile-unreasoned", "severity": "error", "family": family, "message": "A project profile needs a reason and evidence."})
            else:
                resolved[family] = {**selection, "family": family, "standardRefPrefixes": ["project."]}
            continue
        profile = profiles.get(profile_id)
        if not profile or profile.get("family") != family:
            issues.append({"code": "profile-invalid", "severity": "error", "family": family, "profile": profile_id, "message": f"Profile {profile_id!r} does not belong to {family}."})
            continue
        resolved[family] = {**profile, "id": profile_id, "source": selection.get("source")}

    decisions = {item.get("id") for item in ir.get("design", {}).get("decisions", []) if isinstance(item, dict)}
    screen_families = {str(screen.get("id")): platform_family(screen.get("platform")) for screen in ir.get("screens", [])}
    node_screens = node_screen_map(ir)
    for node_id, node in ir.get("nodes", {}).items():
        if node.get("type") == "spacer" or node.get("decisionId") in decisions:
            continue
        shared = str(node.get("standardRef", ""))
        per_platform = node.get("standardRefs", {}) if isinstance(node.get("standardRefs"), dict) else {}
        node_families = {screen_families.get(screen_id) for screen_id in node_screens.get(str(node_id), set())}
        node_families.discard(None)
        node_families = node_families or families
        for family in sorted(node_families):
            profile = resolved.get(family)
            if not profile:
                continue
            ref = str(per_platform.get(family, shared))
            prefixes = tuple(profile.get("standardRefPrefixes", []))
            if not ref.startswith(prefixes):
                issues.append({"code": "standard-ref-mismatch", "severity": "error", "family": family, "node": node_id, "ref": ref or None, "allowedPrefixes": list(prefixes), "message": f"Node {node_id} lacks a {family} standard reference or decision."})

    return {
        "version": 1,
        "status": "blocked" if any(item["severity"] == "error" for item in issues) else "pass",
        "targetFamilies": sorted(families),
        "frameworkAdapters": sorted(framework_adapters(ir)),
        "resolvedProfiles": resolved,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", help="Path to ui-ir.json")
    parser.add_argument("--output", required=True, help="Path for platform-profile-report.json")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the report is blocked")
    args = parser.parse_args()
    report = validate_profiles(read_json(args.ir))
    write_json(args.output, report)
    print(Path(args.output).resolve())
    return 2 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    sys.exit(main())
