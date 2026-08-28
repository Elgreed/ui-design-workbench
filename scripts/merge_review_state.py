#!/usr/bin/env python3
"""Merge exported HTML review feedback into UI IR without touching app source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {"new", "in-progress", "proposed", "accepted", "rejected", "resolved"}
FIX_REQUEST_TYPES = {"ui-design-workbench-fix-request", "ui-code-preview-fix-request"}
ALLOWED_DECISIONS = {"pending", "accepted", "rejected"}
ALLOWED_FINDING_DECISIONS = {"accepted", "rejected", "deferred"}
ALLOWED_SEVERITIES = {"blocker", "high", "medium", "low"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_EFFORT = {"small", "medium", "large"}
ALLOWED_EVIDENCE = {
    "requirement", "user-feedback", "research", "analytics", "source",
    "project-pattern", "platform-standard", "accessibility-standard", "heuristic",
}


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_runtime_findings(
    runtime_findings: Any,
    *,
    nodes: dict[str, Any],
    screen_ids: set[Any],
    existing_ids: set[Any],
) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    valid_ids: set[str] = set()
    if runtime_findings is None:
        return errors, valid_ids
    if not isinstance(runtime_findings, list):
        return ["Feedback runtimeFindings must be an array"], valid_ids
    required = (
        "id", "title", "category", "severity", "confidence", "screenId",
        "observation", "impact", "recommendation", "effort",
    )
    for index, finding in enumerate(runtime_findings):
        if not isinstance(finding, dict):
            errors.append(f"runtimeFindings[{index}] must be an object")
            continue
        finding_id = finding.get("id")
        for field in required:
            if not finding.get(field):
                errors.append(f"runtimeFindings[{index}] is missing {field}")
        if finding_id in existing_ids or finding_id in valid_ids:
            errors.append(f"Duplicate runtime finding id: {finding_id}")
        elif finding_id:
            valid_ids.add(finding_id)
        if finding.get("severity") not in ALLOWED_SEVERITIES:
            errors.append(f"Runtime finding {finding_id} has invalid severity")
        if finding.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(f"Runtime finding {finding_id} has invalid confidence")
        if finding.get("effort") not in ALLOWED_EFFORT:
            errors.append(f"Runtime finding {finding_id} has invalid effort")
        if finding.get("screenId") not in screen_ids:
            errors.append(f"Runtime finding {finding_id} references a missing screen")
        if finding.get("nodeId") and finding.get("nodeId") not in nodes:
            errors.append(f"Runtime finding {finding_id} references a missing node")
        if not finding.get("proposalVersionId") and not finding.get("noProposalReason"):
            errors.append(f"Runtime finding {finding_id} needs noProposalReason")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"Runtime finding {finding_id} needs evidence")
        else:
            for evidence_index, item in enumerate(evidence):
                if (
                    not isinstance(item, dict)
                    or item.get("type") not in ALLOWED_EVIDENCE
                    or not item.get("ref")
                    or not item.get("note")
                ):
                    errors.append(
                        f"Runtime finding {finding_id} has invalid evidence[{evidence_index}]"
                    )
    return errors, valid_ids


def validate_feedback(ir: dict[str, Any], feedback: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    review = ir.get("review", {})
    nodes = ir.get("nodes", {})
    screen_ids = {item.get("id") for item in ir.get("screens", [])}
    version_ids = {item.get("id") for item in review.get("versions", [])}
    if feedback.get("version") not in {1, 2, 3}:
        errors.append("Feedback version must be 1, 2, or 3")
    if review.get("sessionId") and feedback.get("sessionId") != review.get("sessionId"):
        errors.append("Feedback sessionId does not match this IR review session")
    if feedback.get("activeVersion") not in version_ids:
        errors.append("Feedback activeVersion is not present in the IR")
    if feedback.get("versionDecision", "pending") not in ALLOWED_DECISIONS:
        errors.append("Feedback versionDecision is invalid")
    finding_ids = {
        item.get("id") for item in review.get("audit", {}).get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    runtime_errors, runtime_finding_ids = validate_runtime_findings(
        feedback.get("runtimeFindings", []),
        nodes=nodes,
        screen_ids=screen_ids,
        existing_ids=finding_ids,
    )
    errors.extend(runtime_errors)
    finding_ids.update(runtime_finding_ids)
    finding_decisions = feedback.get("findingDecisions", {})
    if not isinstance(finding_decisions, dict):
        errors.append("Feedback findingDecisions must be an object")
    else:
        for finding_id, decision in finding_decisions.items():
            if finding_id not in finding_ids:
                errors.append(f"Feedback references missing finding {finding_id}")
            if decision not in ALLOWED_FINDING_DECISIONS:
                errors.append(f"Finding {finding_id} has invalid decision {decision}")
    diagnostics = feedback.get("diagnostics")
    if diagnostics is not None:
        if not isinstance(diagnostics, dict):
            errors.append("Feedback diagnostics must be an object or null")
        else:
            if diagnostics.get("version") not in {1, 2}:
                errors.append("Feedback diagnostics version must be 1 or 2")
            if diagnostics.get("status") != "complete":
                errors.append("Feedback diagnostics status must be complete")
            if not isinstance(diagnostics.get("summary"), dict):
                errors.append("Feedback diagnostics summary must be an object")
            if not isinstance(diagnostics.get("checks"), list):
                errors.append("Feedback diagnostics checks must be an array")
    annotation_ids: set[str] = set()
    for index, item in enumerate(feedback.get("annotations", [])):
        if not isinstance(item, dict):
            errors.append(f"annotations[{index}] must be an object")
            continue
        annotation_id = item.get("id")
        if not annotation_id:
            errors.append(f"annotations[{index}] is missing id")
        elif annotation_id in annotation_ids:
            errors.append(f"Duplicate annotation id: {annotation_id}")
        annotation_ids.add(annotation_id or "")
        if not str(item.get("text", "")).strip():
            errors.append(f"Annotation {annotation_id} has no text")
        if item.get("nodeId") and item.get("nodeId") not in nodes:
            errors.append(f"Annotation {annotation_id} references missing node {item.get('nodeId')}")
        if item.get("screenId") and item.get("screenId") not in screen_ids:
            errors.append(f"Annotation {annotation_id} references missing screen {item.get('screenId')}")
        if item.get("versionId") and item.get("versionId") not in version_ids:
            errors.append(f"Annotation {annotation_id} references missing version {item.get('versionId')}")
        if item.get("status", "new") not in ALLOWED_STATUSES:
            errors.append(f"Annotation {annotation_id} has invalid status {item.get('status')}")
    return errors


def validate_fix_request(ir: dict[str, Any], request: dict[str, Any]) -> list[str]:
    if request.get("type") not in FIX_REQUEST_TYPES:
        return []
    errors: list[str] = []
    accepted = request.get("acceptedFindingIds", [])
    if request.get("version") not in {1, 2}:
        errors.append("Fix request version must be 1 or 2")
    if not isinstance(accepted, list) or not accepted:
        errors.append("Fix request acceptedFindingIds must be a non-empty array")
        accepted = []
    if len(accepted) != len(set(accepted)):
        errors.append("Fix request acceptedFindingIds contains duplicates")
    finding_ids = {
        item.get("id") for item in ir.get("review", {}).get("audit", {}).get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    review_feedback = request.get("reviewFeedback", {})
    finding_ids.update(
        item.get("id") for item in review_feedback.get("runtimeFindings", [])
        if isinstance(item, dict) and item.get("id")
    )
    decisions = review_feedback.get("findingDecisions", {})
    for finding_id in accepted:
        if finding_id not in finding_ids:
            errors.append(f"Fix request references missing finding {finding_id}")
        if decisions.get(finding_id) != "accepted":
            errors.append(f"Fix request finding {finding_id} is not accepted in reviewFeedback")
    return errors


def merge(ir: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    review = ir.setdefault("review", {})
    audit = review.setdefault("audit", {})
    merged_findings = {
        item.get("id"): item for item in audit.get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    for item in feedback.get("runtimeFindings", []):
        merged_findings[item["id"]] = item
    if merged_findings:
        audit["findings"] = list(merged_findings.values())
    existing = {
        item.get("id"): item for item in review.get("annotations", [])
        if isinstance(item, dict) and item.get("id")
    }
    for item in feedback.get("annotations", []):
        existing[item["id"]] = item
    review["annotations"] = list(existing.values())
    review["activeVersion"] = feedback["activeVersion"]
    review["versionDecision"] = feedback.get("versionDecision", "pending")
    if feedback.get("findingDecisions"):
        audit["findingDecisions"] = feedback["findingDecisions"]
    if feedback.get("diagnostics"):
        review["diagnosticsReport"] = feedback["diagnostics"]
    review["feedbackExportedAt"] = feedback.get("exportedAt")
    review["feedbackRevision"] = feedback.get("revision")
    return ir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge exported ui-review-state.json or ui-fix-request.json into ui-ir.json.")
    parser.add_argument("ir", type=Path, help="Existing ui-ir.json")
    parser.add_argument("feedback", type=Path, help="Exported ui-review-state.json (legacy ui-review-feedback.json is accepted)")
    parser.add_argument("--output", type=Path, required=True, help="Output IR; use a new file for auditability")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ir = load_object(args.ir, "IR")
        payload = load_object(args.feedback, "feedback or fix request")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    is_fix_request = payload.get("type") in FIX_REQUEST_TYPES
    feedback = payload.get("reviewFeedback") if is_fix_request else payload
    if not isinstance(feedback, dict):
        print("Fix request reviewFeedback must be an object", file=sys.stderr)
        return 2
    errors = validate_feedback(ir, feedback) + validate_fix_request(ir, payload)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    merged = merge(ir, feedback)
    if is_fix_request:
        merged.setdefault("review", {})["correctionRequest"] = {
            "acceptedFindingIds": payload.get("acceptedFindingIds", []),
            "existingProposalVersionIds": payload.get("existingProposalVersionIds", []),
            "requestedAction": payload.get("requestedAction"),
            "createdAt": payload.get("createdAt"),
        }
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
