#!/usr/bin/env python3
"""Build a deterministic UI translation coverage report from ui-ir.json."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from quality_common import read_json, walk_tree_screen_ids, write_json
from render_preview import fidelity_audit
from validate_platform_profiles import validate_profiles


def gate(gate_id: str, label: str, passed: bool, actual: Any, expected: Any, details: Any = None) -> dict[str, Any]:
    value = {"id": gate_id, "label": label, "status": "pass" if passed else "fail", "actual": actual, "expected": expected}
    if details:
        value["details"] = details
    return value


def build_report(ir: dict[str, Any]) -> dict[str, Any]:
    audit = fidelity_audit(ir)
    profiles = validate_profiles(ir)
    screen_ids = [str(item.get("id")) for item in ir.get("screens", []) if item.get("id")]
    tree_ids = walk_tree_screen_ids(ir.get("screenTree", []))
    tree_counts = Counter(tree_ids)
    missing_tree = sorted(set(screen_ids) - set(tree_ids))
    duplicate_tree = sorted(item for item, count in tree_counts.items() if count > 1)
    unknown_tree = sorted(set(tree_ids) - set(screen_ids))
    mode = ir.get("design", {}).get("mode", "reconstruct")
    needs_design_evidence = mode in {"generate", "redesign"}
    needs_source = mode == "reconstruct"

    gates = [
        gate("fidelity", "Renderer fidelity audit", audit.get("status") == "reviewable", audit.get("status"), "reviewable", audit.get("reasons")),
        gate("screen-tree", "Every screen appears once in screenTree", not missing_tree and not duplicate_tree and not unknown_tree, len(tree_ids), len(screen_ids), {"missing": missing_tree, "duplicates": duplicate_tree, "unknown": unknown_tree}),
        gate("screens", "Discovered screen coverage", audit.get("screenCoverage", 0) == 1, audit.get("screenCoverage", 0), 1, audit.get("missingScreens")),
        gate("routes", "Discovered route coverage", audit.get("routeCoverage", 0) == 1, audit.get("routeCoverage", 0), 1, audit.get("missingRoutes")),
        gate("navigation", "Discovered navigation coverage", audit.get("navigationCoverage", 0) == 1, audit.get("navigationCoverage", 0), 1, audit.get("missingNavigationTargets")),
        gate("components", "Mapped component coverage", audit.get("componentCoverage", 0) == 1, audit.get("componentCoverage", 0), 1),
        gate("appearance", "Explicit appearance coverage", audit.get("appearanceCoverage", 0) >= .9, audit.get("appearanceCoverage", 0), .9),
        gate("profiles", "Platform profiles", profiles.get("status") == "pass", profiles.get("status"), "pass", profiles.get("issues")),
    ]
    if needs_source:
        gates.append(gate("source", "Source mapping coverage", audit.get("sourceCoverage", 0) >= .8, audit.get("sourceCoverage", 0), .8))
    if needs_design_evidence:
        gates.extend([
            gate("evidence", "Design evidence coverage", audit.get("evidenceCoverage", 0) >= .9, audit.get("evidenceCoverage", 0), .9),
            gate("semantics", "Interactive semantics coverage", audit.get("semanticCoverage", 0) == 1, audit.get("semanticCoverage", 0), 1),
            gate("standards", "Platform-standard coverage", audit.get("standardCoverage", 0) == 1, audit.get("standardCoverage", 0), 1),
            gate("targets", "Interactive target coverage", audit.get("targetCoverage", 0) == 1, audit.get("targetCoverage", 0), 1, audit.get("targetFailures")),
            gate("contrast", "Resolvable contrast coverage", audit.get("contrastCoverage", 0) == 1 and not audit.get("contrastFailures"), audit.get("contrastCoverage", 0), 1, {"failures": audit.get("contrastFailures"), "unresolved": audit.get("contrastUnresolved")}),
            gate("states", "Required state coverage", audit.get("stateCoverage", 0) == 1, audit.get("stateCoverage", 0), 1, audit.get("missingStates")),
        ])

    failed = [item for item in gates if item["status"] == "fail"]
    return {
        "version": 1,
        "status": "blocked" if failed else "pass",
        "project": ir.get("project", {}).get("name", "Project"),
        "designMode": mode,
        "summary": {"passed": len(gates) - len(failed), "failed": len(failed), "total": len(gates)},
        "inventory": {
            "screens": len(screen_ids),
            "treeEntries": len(tree_ids),
            "nodes": len(ir.get("nodes", {})),
            "components": len(ir.get("componentCatalog", {}).get("components", [])),
            "actions": audit.get("interactionActions", 0),
            "navigationActions": audit.get("navigationActions", 0),
        },
        "coverage": {key: value for key, value in audit.items() if key.endswith("Coverage")},
        "gates": gates,
        "platformProfiles": profiles,
        "fidelityAudit": audit,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# UI coverage · {report['project']}",
        "",
        f"Status: **{report['status']}** · passed {report['summary']['passed']} / {report['summary']['total']}",
        "",
        "| Gate | Status | Actual | Expected |",
        "| --- | --- | ---: | ---: |",
    ]
    for item in report["gates"]:
        lines.append(f"| {item['label']} | {item['status']} | {item['actual']} | {item['expected']} |")
    failed = [item for item in report["gates"] if item["status"] == "fail"]
    if failed:
        lines.extend(["", "## Blocking details", ""])
        for item in failed:
            lines.append(f"- **{item['label']}**: {item.get('details') or 'threshold not met'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", help="Path to ui-ir.json")
    parser.add_argument("--output", required=True, help="Path for ui-coverage.json")
    parser.add_argument("--markdown", help="Optional Markdown summary path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when a gate fails")
    args = parser.parse_args()
    report = build_report(read_json(args.ir))
    write_json(args.output, report)
    if args.markdown:
        target = Path(args.markdown)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown(report), encoding="utf-8")
    print(f"Coverage: {report['status']} | {report['summary']['passed']}/{report['summary']['total']} gates")
    return 2 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    sys.exit(main())
