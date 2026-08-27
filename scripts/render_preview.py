#!/usr/bin/env python3
"""Render UI IR as a standalone interactive HTML review preview."""

from __future__ import annotations

import argparse
import base64
import copy
import html
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any

from quality_common import platform_family as catalog_platform_family, profile_catalog


def validate(ir: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if ir.get("version") != 1:
        errors.append("IR version must be 1")
    screens = ir.get("screens")
    nodes = ir.get("nodes")
    if not isinstance(screens, list) or not screens:
        errors.append("IR must contain at least one screen")
    if not isinstance(nodes, dict):
        errors.append("IR nodes must be an object")
        nodes = {}
    screen_ids: set[str] = set()
    for index, screen in enumerate(screens or []):
        for key in ("id", "name", "root"):
            if not screen.get(key):
                errors.append(f"screens[{index}] is missing {key}")
        if screen.get("id") in screen_ids:
            errors.append(f"Duplicate screen id: {screen.get('id')}")
        screen_ids.add(screen.get("id", ""))
        if screen.get("root") not in nodes:
            errors.append(f"Screen {screen.get('id')} references missing root node {screen.get('root')}")
    screen_tree = ir.get("screenTree")
    if screen_tree is None:
        errors.append("IR must contain a complete screenTree")
    elif not isinstance(screen_tree, list) or not screen_tree:
        errors.append("screenTree must be a non-empty array")
    else:
        tree_screen_ids: list[str] = []

        def visit_tree(items: list[Any], path: str) -> None:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{path}[{index}] must be an object")
                    continue
                screen_id = item.get("screenId") or item.get("screen")
                if screen_id:
                    tree_screen_ids.append(str(screen_id))
                    if screen_id not in screen_ids:
                        errors.append(f"{path}[{index}] references missing screen {screen_id}")
                    continue
                children = item.get("children")
                if not item.get("label") or not isinstance(children, list) or not children:
                    errors.append(f"{path}[{index}] group needs label and non-empty children")
                    continue
                visit_tree(children, f"{path}[{index}].children")

        visit_tree(screen_tree, "screenTree")
        duplicates = sorted({item for item in tree_screen_ids if tree_screen_ids.count(item) > 1})
        missing = sorted(screen_ids - set(tree_screen_ids))
        if duplicates:
            errors.append(f"screenTree contains duplicate screen references: {', '.join(duplicates)}")
        if missing:
            errors.append(f"screenTree is missing screens: {', '.join(missing)}")
    for node_id, node in nodes.items():
        for child_id in node.get("children", []):
            if child_id not in nodes:
                errors.append(f"Node {node_id} references missing child {child_id}")
        action = node.get("action", {})
        if action.get("type") == "navigate" and action.get("target") not in screen_ids:
            errors.append(f"Node {node_id} navigates to missing screen {action.get('target')}")
        if action.get("type") in {"set-node-state", "toggle-node-state", "toggle"} and action.get("target") not in nodes:
            errors.append(f"Node {node_id} targets missing state node {action.get('target')}")
        if action.get("type") and action.get("type") not in {"navigate", "back", "set-node-state", "toggle-node-state", "toggle", "reset-state"}:
            errors.append(f"Node {node_id} uses unsupported action {action.get('type')}")

    catalog = ir.get("componentCatalog", {})
    catalog_ids: set[str] = set()
    for index, component in enumerate(catalog.get("components", [])):
        component_id = component.get("id")
        if not component_id:
            errors.append(f"componentCatalog.components[{index}] is missing id")
        elif component_id in catalog_ids:
            errors.append(f"Duplicate component catalog id: {component_id}")
        catalog_ids.add(component_id or "")

    review = ir.get("review", {})
    versions = review.get("versions", [])
    if review:
        if not isinstance(versions, list) or not versions:
            errors.append("review must contain at least one version")
            versions = []
        version_ids: set[str] = set()
        for index, version in enumerate(versions):
            version_id = version.get("id")
            if not version_id:
                errors.append(f"review.versions[{index}] is missing id")
                continue
            if version_id in version_ids:
                errors.append(f"Duplicate review version id: {version_id}")
            version_ids.add(version_id)
            overrides = version.get("nodeOverrides", {})
            if not isinstance(overrides, dict):
                errors.append(f"Review version {version_id} nodeOverrides must be an object")
            else:
                for node_id in overrides:
                    if node_id not in nodes:
                        errors.append(f"Review version {version_id} overrides missing node {node_id}")
        for version in versions:
            if version.get("parent") and version.get("parent") not in version_ids:
                errors.append(f"Review version {version.get('id')} references missing parent {version.get('parent')}")
        for key in ("baselineVersion", "activeVersion"):
            if review.get(key) and review.get(key) not in version_ids:
                errors.append(f"review.{key} references missing version {review.get(key)}")
        annotation_ids: set[str] = set()
        for index, annotation in enumerate(review.get("annotations", [])):
            annotation_id = annotation.get("id")
            if not annotation_id:
                errors.append(f"review.annotations[{index}] is missing id")
            elif annotation_id in annotation_ids:
                errors.append(f"Duplicate annotation id: {annotation_id}")
            annotation_ids.add(annotation_id or "")
            if annotation.get("nodeId") and annotation.get("nodeId") not in nodes:
                errors.append(f"Annotation {annotation_id} references missing node {annotation.get('nodeId')}")
            if annotation.get("screenId") and annotation.get("screenId") not in screen_ids:
                errors.append(f"Annotation {annotation_id} references missing screen {annotation.get('screenId')}")
        diagnostics = review.get("diagnostics")
        if diagnostics is not None:
            if not isinstance(diagnostics, dict):
                errors.append("review.diagnostics must be an object")
            else:
                profiles = diagnostics.get("profiles", [])
                scenarios = diagnostics.get("scenarios", [])
                if not isinstance(profiles, list) or not profiles:
                    errors.append("review.diagnostics.profiles must be a non-empty array")
                    profiles = []
                if not isinstance(scenarios, list) or not scenarios:
                    errors.append("review.diagnostics.scenarios must be a non-empty array")
                    scenarios = []
                profile_ids: set[str] = set()
                for index, profile in enumerate(profiles):
                    if not isinstance(profile, dict):
                        errors.append(f"review.diagnostics.profiles[{index}] must be an object")
                        continue
                    profile_id = profile.get("id")
                    if not profile_id or not profile.get("label"):
                        errors.append(f"review.diagnostics.profiles[{index}] needs id and label")
                    if profile_id in profile_ids:
                        errors.append(f"Duplicate diagnostics profile id: {profile_id}")
                    profile_ids.add(profile_id or "")
                    viewport = profile.get("viewport", "current")
                    if viewport != "current":
                        if not isinstance(viewport, dict) or not isinstance(viewport.get("width"), (int, float)) or not isinstance(viewport.get("height"), (int, float)) or viewport.get("width", 0) <= 0 or viewport.get("height", 0) <= 0:
                            errors.append(f"Diagnostics profile {profile_id} viewport must be 'current' or a positive width/height object")
                    zoom_levels = profile.get("zoomLevels", [])
                    if not isinstance(zoom_levels, list) or not zoom_levels:
                        errors.append(f"Diagnostics profile {profile_id} needs non-empty zoomLevels")
                    elif any(not isinstance(value, (int, float)) or value < 0.2 or value > 2 for value in zoom_levels):
                        errors.append(f"Diagnostics profile {profile_id} zoomLevels must stay between 0.2 and 2")
                allowed_scenarios = {"zoom-reset", "overview-geometry", "menu-exclusivity", "layout-integrity", "accessibility-basics", "state-matrix", "navigation-flow", "contrast-focus"}
                scenario_ids: set[str] = set()
                for index, scenario in enumerate(scenarios):
                    if not isinstance(scenario, dict):
                        errors.append(f"review.diagnostics.scenarios[{index}] must be an object")
                        continue
                    scenario_id = scenario.get("id")
                    if not scenario_id or not scenario.get("label") or not scenario.get("kind"):
                        errors.append(f"review.diagnostics.scenarios[{index}] needs id, label and kind")
                    if scenario_id in scenario_ids:
                        errors.append(f"Duplicate diagnostics scenario id: {scenario_id}")
                    scenario_ids.add(scenario_id or "")
                    if scenario.get("kind") not in allowed_scenarios:
                        errors.append(f"Diagnostics scenario {scenario_id} uses unsupported kind {scenario.get('kind')}")
        audit = review.get("audit")
        if audit is not None:
            if not isinstance(audit, dict):
                errors.append("review.audit must be an object")
            else:
                if not audit.get("summary"):
                    errors.append("review.audit is missing summary")
                declared_finding_ids = {
                    item.get("id") for item in audit.get("findings", [])
                    if isinstance(item, dict) and item.get("id")
                }
                scope = audit.get("scope", {})
                if not isinstance(scope, dict) or not scope.get("tasks") or not scope.get("screens"):
                    errors.append("review.audit.scope needs non-empty tasks and screens")
                else:
                    for screen_id in scope.get("screens", []):
                        if screen_id not in screen_ids:
                            errors.append(f"review.audit.scope references missing screen {screen_id}")
                    if audit.get("status") == "complete":
                        if not scope.get("interactions"):
                            errors.append("complete review.audit.scope needs non-empty interactions")
                        if not scope.get("uxLenses"):
                            errors.append("complete review.audit.scope needs non-empty uxLenses")
                interaction_checks = audit.get("interactionChecks", [])
                if audit.get("status") == "complete" and not interaction_checks:
                    errors.append("complete review.audit needs non-empty interactionChecks")
                if not isinstance(interaction_checks, list):
                    errors.append("review.audit.interactionChecks must be an array")
                    interaction_checks = []
                for index, check in enumerate(interaction_checks):
                    if not isinstance(check, dict):
                        errors.append(f"review.audit.interactionChecks[{index}] must be an object")
                        continue
                    for field in ("id", "startState", "actions", "expected", "observed", "result", "viewports", "inputMethods"):
                        if not check.get(field):
                            errors.append(f"review.audit.interactionChecks[{index}] is missing {field}")
                    if check.get("result") not in {"pass", "fail", "not-run"}:
                        errors.append(f"Interaction check {check.get('id')} uses unsupported result {check.get('result')}")
                    linked_findings = check.get("findingIds", [])
                    if check.get("result") == "fail" and not linked_findings:
                        errors.append(f"Failed interaction check {check.get('id')} needs findingIds")
                    for finding_id in linked_findings:
                        if finding_id not in declared_finding_ids:
                            errors.append(f"Interaction check {check.get('id')} references missing finding {finding_id}")
                    if audit.get("status") == "complete" and check.get("result") == "not-run":
                        errors.append(f"Complete audit cannot contain untested interaction check {check.get('id')}")
                layout_checks = audit.get("layoutChecks", [])
                if audit.get("status") == "complete" and not layout_checks:
                    errors.append("complete review.audit needs non-empty layoutChecks")
                if not isinstance(layout_checks, list):
                    errors.append("review.audit.layoutChecks must be an array")
                    layout_checks = []
                required_layout_kinds = {"typography", "sibling-alignment", "control-padding", "text-containment", "icon-label-optics"}
                covered_layout_kinds: set[str] = set()
                for index, check in enumerate(layout_checks):
                    if not isinstance(check, dict):
                        errors.append(f"review.audit.layoutChecks[{index}] must be an object")
                        continue
                    for field in ("id", "kind", "scope", "viewports", "zoomLevels", "metrics", "expected", "observed", "result"):
                        if not check.get(field):
                            errors.append(f"review.audit.layoutChecks[{index}] is missing {field}")
                    kind = check.get("kind")
                    if kind not in required_layout_kinds:
                        errors.append(f"Layout check {check.get('id')} uses unsupported kind {kind}")
                    else:
                        covered_layout_kinds.add(kind)
                    if check.get("result") not in {"pass", "fail", "not-run"}:
                        errors.append(f"Layout check {check.get('id')} uses unsupported result {check.get('result')}")
                    linked_findings = check.get("findingIds", [])
                    if check.get("result") == "fail" and not linked_findings:
                        errors.append(f"Failed layout check {check.get('id')} needs findingIds")
                    for finding_id in linked_findings:
                        if finding_id not in declared_finding_ids:
                            errors.append(f"Layout check {check.get('id')} references missing finding {finding_id}")
                    if audit.get("status") == "complete" and check.get("result") == "not-run":
                        errors.append(f"Complete audit cannot contain untested layout check {check.get('id')}")
                if audit.get("status") == "complete":
                    missing_layout_kinds = sorted(required_layout_kinds - covered_layout_kinds)
                    if missing_layout_kinds:
                        errors.append(f"complete review.audit.layoutChecks misses kinds: {', '.join(missing_layout_kinds)}")
                ux_assessment = audit.get("uxAssessment", [])
                if audit.get("status") == "complete" and not ux_assessment:
                    errors.append("complete review.audit needs non-empty uxAssessment")
                if not isinstance(ux_assessment, list):
                    errors.append("review.audit.uxAssessment must be an array")
                    ux_assessment = []
                for index, assessment in enumerate(ux_assessment):
                    if not isinstance(assessment, dict):
                        errors.append(f"review.audit.uxAssessment[{index}] must be an object")
                        continue
                    for field in ("lens", "status", "observation"):
                        if not assessment.get(field):
                            errors.append(f"review.audit.uxAssessment[{index}] is missing {field}")
                    if assessment.get("status") not in {"pass", "finding", "gap"}:
                        errors.append(f"UX assessment {assessment.get('lens')} uses unsupported status {assessment.get('status')}")
                    linked_findings = assessment.get("findingIds", [])
                    if assessment.get("status") == "finding" and not linked_findings:
                        errors.append(f"UX assessment {assessment.get('lens')} with finding status needs findingIds")
                    for finding_id in linked_findings:
                        if finding_id not in declared_finding_ids:
                            errors.append(f"UX assessment {assessment.get('lens')} references missing finding {finding_id}")
                findings = audit.get("findings", [])
                if not isinstance(findings, list):
                    errors.append("review.audit.findings must be an array")
                    findings = []
                finding_ids: set[str] = set()
                allowed_severities = {"blocker", "high", "medium", "low"}
                allowed_confidence = {"high", "medium", "low"}
                allowed_effort = {"small", "medium", "large"}
                allowed_evidence = {
                    "requirement", "user-feedback", "research", "analytics", "source",
                    "project-pattern", "platform-standard", "accessibility-standard", "heuristic",
                }
                decision_ids = {
                    item.get("id") for item in ir.get("design", {}).get("decisions", [])
                    if isinstance(item, dict) and item.get("id")
                }
                required_fields = ("id", "title", "category", "severity", "confidence", "screenId", "observation", "impact", "recommendation", "effort")
                for index, finding in enumerate(findings):
                    if not isinstance(finding, dict):
                        errors.append(f"review.audit.findings[{index}] must be an object")
                        continue
                    finding_id = finding.get("id")
                    for field in required_fields:
                        if not finding.get(field):
                            errors.append(f"review.audit.findings[{index}] is missing {field}")
                    if finding_id in finding_ids:
                        errors.append(f"Duplicate review finding id: {finding_id}")
                    finding_ids.add(finding_id or "")
                    if finding.get("severity") not in allowed_severities:
                        errors.append(f"Finding {finding_id} uses unsupported severity {finding.get('severity')}")
                    if finding.get("confidence") not in allowed_confidence:
                        errors.append(f"Finding {finding_id} uses unsupported confidence {finding.get('confidence')}")
                    if finding.get("effort") not in allowed_effort:
                        errors.append(f"Finding {finding_id} uses unsupported effort {finding.get('effort')}")
                    if finding.get("screenId") not in screen_ids:
                        errors.append(f"Finding {finding_id} references missing screen {finding.get('screenId')}")
                    if finding.get("nodeId") and finding.get("nodeId") not in nodes:
                        errors.append(f"Finding {finding_id} references missing node {finding.get('nodeId')}")
                    proposal_id = finding.get("proposalVersionId")
                    if proposal_id and proposal_id not in version_ids:
                        errors.append(f"Finding {finding_id} references missing proposal version {proposal_id}")
                    elif proposal_id:
                        proposal = next((item for item in versions if item.get("id") == proposal_id), {})
                        if proposal.get("kind") != "proposal":
                            errors.append(f"Finding {finding_id} must reference a proposal version")
                        if finding_id not in proposal.get("findingIds", []):
                            errors.append(f"Proposal version {proposal_id} must link back to finding {finding_id}")
                    if not proposal_id and not finding.get("noProposalReason"):
                        errors.append(f"Finding {finding_id} needs proposalVersionId or noProposalReason")
                    if finding.get("decisionId") and finding.get("decisionId") not in decision_ids:
                        errors.append(f"Finding {finding_id} references missing design decision {finding.get('decisionId')}")
                    evidence = finding.get("evidence", [])
                    if not isinstance(evidence, list) or not evidence:
                        errors.append(f"Finding {finding_id} needs at least one evidence entry")
                    else:
                        for evidence_index, item in enumerate(evidence):
                            if not isinstance(item, dict) or item.get("type") not in allowed_evidence or not item.get("ref") or not item.get("note"):
                                errors.append(f"Finding {finding_id} has invalid evidence[{evidence_index}]")
                for version in versions:
                    for finding_id in version.get("findingIds", []):
                        if finding_id not in finding_ids:
                            errors.append(f"Review version {version.get('id')} references missing finding {finding_id}")
    return errors


def fidelity_audit(ir: dict[str, Any]) -> dict[str, Any]:
    nodes = ir.get("nodes", {})
    screens = ir.get("screens", [])
    design = ir.get("design", {})
    design_mode = design.get("mode", "reconstruct")
    fidelity = ir.get("fidelity", {})
    meaningful_items = [(node_id, node) for node_id, node in nodes.items() if node.get("type") != "spacer"]
    meaningful = [node for _, node in meaningful_items]
    placeholders = [
        node for node in meaningful
        if node.get("component") in {"UntranslatedSource", "DiscoveredScreen"}
        or (node.get("type") == "custom" and node.get("confidence") == "unsupported")
    ]
    sourced = [node for node in meaningful if node.get("source", {}).get("file")]
    confident = [node for node in meaningful if node.get("confidence") in {"exact", "high"}]
    visual = [node for node in meaningful if node.get("type") in {"text", "button", "input", "image", "icon", "card"}]
    decisions = {item.get("id") for item in design.get("decisions", []) if isinstance(item, dict) and item.get("id")}
    catalog = ir.get("componentCatalog", {})
    catalog_entries = {
        item.get("id"): item for item in catalog.get("components", [])
        if isinstance(item, dict) and item.get("id")
    }
    project_component_nodes = [
        (node_id, node) for node_id, node in meaningful_items
        if node.get("componentRef") or any(item.get("name") == node.get("component") for item in catalog_entries.values())
    ]
    mapped_component_nodes = [
        node for _, node in project_component_nodes
        if node.get("componentRef") in catalog_entries
        and catalog_entries[node.get("componentRef")].get("inspection") == "mapped"
    ]

    def platform_family(value: Any) -> str | None:
        return catalog_platform_family(value)

    target_platforms = {platform_family(item) for item in design.get("targetPlatforms", [])}
    target_platforms.discard(None)
    if not target_platforms:
        target_platforms = {platform_family(item) for item in ir.get("platforms", [])}
        target_platforms.discard(None)

    node_platforms: dict[str, set[str]] = {node_id: set() for node_id in nodes}

    def mark_platform(node_id: str, families: set[str], seen: set[str]) -> None:
        if node_id in seen or node_id not in nodes:
            return
        seen.add(node_id)
        node_platforms[node_id].update(families)
        for child_id in nodes[node_id].get("children", []):
            mark_platform(child_id, families, seen)

    for screen in screens:
        family = platform_family(screen.get("platform"))
        families = {family} if family else set(target_platforms)
        mark_platform(screen.get("root", ""), families, set())

    parents: dict[str, str] = {}
    for parent_id, node in nodes.items():
        for child_id in node.get("children", []):
            parents.setdefault(child_id, parent_id)

    def resolve_token(value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        resolved: Any = ir.get("tokens", {})
        for part in value[1:].split("."):
            if not isinstance(resolved, dict):
                return value
            resolved = resolved.get(part)
        return value if resolved is None else resolved

    def inherited_style(node_id: str, keys: tuple[str, ...]) -> Any:
        current = node_id
        seen: set[str] = set()
        while current in nodes and current not in seen:
            seen.add(current)
            style = nodes[current].get("style", {})
            for key in keys:
                if style.get(key) is not None:
                    return resolve_token(style[key])
            current = parents.get(current, "")
        return None

    def parse_hex_color(value: Any) -> tuple[float, float, float] | None:
        value = resolve_token(value)
        if not isinstance(value, str) or not value.startswith("#"):
            return None
        raw = value[1:]
        if len(raw) == 3:
            raw = "".join(char * 2 for char in raw)
        if len(raw) != 6:
            return None
        try:
            channels = tuple(int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4))
        except ValueError:
            return None
        return channels

    def luminance(color: tuple[float, float, float]) -> float:
        converted = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in color]
        return 0.2126 * converted[0] + 0.7152 * converted[1] + 0.0722 * converted[2]

    def contrast_ratio(foreground: tuple[float, float, float], background: tuple[float, float, float]) -> float:
        first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (first + 0.05) / (second + 0.05)

    def appearance_complete(node: dict[str, Any]) -> bool:
        if node.get("inheritsAppearance") is True:
            return True
        node_type = node.get("type")
        style = node.get("style", {})
        layout = node.get("layout", {})
        if node_type == "text":
            return bool(style.get("typography") or any(key in style for key in ("fontFamily", "fontSize", "fontWeight", "lineHeight")))
        if node_type in {"image", "icon"}:
            sized = ("width" in layout and "height" in layout) or "aspectRatio" in layout
            return bool(node.get("asset") and sized)
        if node_type in {"button", "input"}:
            visual_style = any(key in style for key in ("background", "backgroundColor", "border", "borderColor", "borderWidth", "boxShadow", "shadow"))
            geometry = any(key in layout for key in ("height", "minHeight", "padding", "paddingVertical", "paddingTop", "paddingBottom"))
            typography = bool(style.get("typography") or node.get("inheritsTypography") is True or any(key in style for key in ("fontFamily", "fontSize", "fontWeight", "lineHeight")))
            return visual_style and geometry and typography
        if node_type == "card":
            return any(key in style for key in ("background", "backgroundColor", "border", "borderColor", "boxShadow", "shadow"))
        return True

    def exclusion_keys(items: list[Any], kind: str) -> tuple[set[str], list[str]]:
        keys: set[str] = set()
        invalid: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                invalid.append(str(item))
                continue
            key = item.get("key")
            if not key and kind == "screen":
                key = f'{item.get("file", "")}#{item.get("name", "")}'
            if not key and kind == "route":
                key = item.get("route")
            if key:
                keys.add(key)
            if not key or not item.get("reason"):
                invalid.append(str(key or item))
        return keys, invalid

    appearance_complete_nodes = [node for node in visual if appearance_complete(node)]
    excluded_screens, invalid_screen_exclusions = exclusion_keys(fidelity.get("excludedScreens", []), "screen")
    excluded_routes, invalid_route_exclusions = exclusion_keys(fidelity.get("excludedRoutes", []), "route")
    discovered_screens = ir.get("discoveredScreens", [])
    discovered_routes = ir.get("discoveredRoutes", [])
    translated_screen_keys = {
        f'{screen.get("source", {}).get("file", "")}#{screen.get("source", {}).get("symbol", screen.get("name", ""))}'
        for screen in screens
    }
    expected_screen_keys = {f'{screen.get("file", "")}#{screen.get("name", "")}' for screen in discovered_screens}
    missing_screen_keys = sorted(expected_screen_keys - translated_screen_keys - excluded_screens)
    translated_routes = {screen.get("route") for screen in screens if screen.get("route")}
    expected_routes = {route.get("route") for route in discovered_routes if route.get("route")}
    missing_routes = sorted(expected_routes - translated_routes - excluded_routes)
    actions = [node.get("action", {}) for node in nodes.values() if node.get("action", {}).get("type")]
    navigation_actions = [action for action in actions if action.get("type") == "navigate"]
    discovered_navigation = ir.get("discoveredNavigationTargets", [])
    excluded_navigation: set[str] = set()
    invalid_navigation_exclusions: list[str] = []
    for item in fidelity.get("excludedNavigationTargets", []):
        if isinstance(item, dict) and item.get("target") and item.get("reason"):
            excluded_navigation.add(str(item["target"]))
        else:
            invalid_navigation_exclusions.append(str(item))
    screen_for_fragment = {
        screen.get("fragment"): screen.get("id") for screen in screens if screen.get("fragment")
    }
    navigated_screen_ids = {action.get("target") for action in navigation_actions}
    expected_navigation_targets = {
        str(item.get("target")) for item in discovered_navigation
        if isinstance(item, dict) and item.get("target")
    }
    missing_navigation_targets = sorted(
        target for target in expected_navigation_targets - excluded_navigation
        if target not in screen_for_fragment or screen_for_fragment[target] not in navigated_screen_ids
    )
    evidence_nodes = [
        node for node in meaningful
        if node.get("source", {}).get("file") or node.get("standardRef") or node.get("standardRefs")
        or node.get("decisionId") in decisions
    ]
    interactive_items = [
        (node_id, node) for node_id, node in meaningful_items
        if node.get("type") in {"button", "input"} or node.get("action", {}).get("type")
    ]
    semantic_nodes = [
        node for _, node in interactive_items
        if node.get("semantics", {}).get("role") and node.get("semantics", {}).get("label")
    ]

    platform_catalog = profile_catalog().get("profiles", {})
    expected_profile_ids = {
        str(profile.get("family")): profile_id
        for profile_id, profile in platform_catalog.items()
        if isinstance(profile, dict) and profile.get("family")
    }
    allowed_ref_prefixes = {
        family: tuple(platform_catalog[profile_id].get("standardRefPrefixes", []))
        for family, profile_id in expected_profile_ids.items()
    }
    profiles = design.get("standardProfiles", {})
    missing_profiles: list[str] = []
    invalid_profiles: list[str] = []
    for family in sorted(target_platforms):
        profile = profiles.get(family, {})
        if not profile:
            missing_profiles.append(family)
        elif profile.get("id") not in {expected_profile_ids[family], "project"}:
            invalid_profiles.append(family)
        elif profile.get("id") == "project" and not profile.get("reason"):
            invalid_profiles.append(family)

    standard_complete: list[dict[str, Any]] = []
    target_complete: list[dict[str, Any]] = []
    target_failures: list[str] = []
    minimum_targets = {
        family: float(platform_catalog[profile_id].get("minimumTarget", {}).get("height", 24))
        for family, profile_id in expected_profile_ids.items()
    }
    for node_id, node in meaningful_items:
        families = node_platforms.get(node_id) or target_platforms
        refs = node.get("standardRefs", {})
        shared_ref = node.get("standardRef", "")
        ref_ok = bool(node.get("decisionId") in decisions)
        if not ref_ok:
            ref_ok = all(
                str(refs.get(family, shared_ref) if isinstance(refs, dict) else shared_ref).startswith(allowed_ref_prefixes[family])
                for family in families
            )
        if ref_ok:
            standard_complete.append(node)

    for node_id, node in interactive_items:
        families = node_platforms.get(node_id) or target_platforms
        semantics = node.get("semantics", {})
        exception = semantics.get("targetSizeException")
        size = semantics.get("targetSize")
        if exception and isinstance(exception, dict) and exception.get("reason"):
            target_complete.append(node)
            continue
        if isinstance(size, (int, float)):
            width = height = float(size)
        elif isinstance(size, dict):
            width = size.get("width")
            height = size.get("height")
        else:
            width = height = None
        minimum = max((minimum_targets[family] for family in families), default=24)
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width >= minimum and height >= minimum:
            target_complete.append(node)
        else:
            target_failures.append(node_id)

    contrast_items = [
        (node_id, node) for node_id, node in meaningful_items
        if node.get("type") in {"text", "button"} and (node.get("text") or node.get("children"))
    ]
    contrast_resolved: list[str] = []
    contrast_failures: list[dict[str, Any]] = []
    contrast_unresolved: list[str] = []
    for node_id, node in contrast_items:
        exception = node.get("accessibility", {}).get("contrastException")
        if isinstance(exception, dict) and exception.get("reason"):
            contrast_resolved.append(node_id)
            continue
        foreground = parse_hex_color(inherited_style(node_id, ("color",)))
        background = parse_hex_color(inherited_style(node_id, ("backgroundColor", "background")))
        if not foreground or not background:
            contrast_unresolved.append(node_id)
            continue
        style = node.get("style", {})
        typography = resolve_token(style.get("typography"))
        typography = typography if isinstance(typography, dict) else {}
        font_size = resolve_token(style.get("fontSize", typography.get("fontSize", 16)))
        font_weight = resolve_token(style.get("fontWeight", typography.get("fontWeight", 400)))
        large = isinstance(font_size, (int, float)) and (
            font_size >= 24 or (font_size >= 18.66 and isinstance(font_weight, (int, float)) and font_weight >= 700)
        )
        minimum_ratio = 3 if large else 4.5
        ratio = contrast_ratio(foreground, background)
        contrast_resolved.append(node_id)
        if ratio + 1e-9 < minimum_ratio:
            contrast_failures.append({"node": node_id, "ratio": round(ratio, 2), "required": minimum_ratio})

    required_states = {"default", "loading", "empty", "error", "offline", "permission", "disabled", "success", "destructive-confirmation"}
    addressed_states: dict[str, set[str]] = {screen.get("id", ""): set() for screen in screens}
    invalid_state_exclusions: list[str] = []
    for entry in design.get("stateMatrix", []):
        if not isinstance(entry, dict):
            invalid_state_exclusions.append(str(entry))
            continue
        entry_screens = entry.get("screens", [])
        if entry.get("screen"):
            entry_screens = [entry["screen"]]
        covered = {str(item) for item in entry.get("covered", [])}
        excluded: set[str] = set()
        for item in entry.get("notApplicable", []):
            if isinstance(item, dict) and item.get("state") and item.get("reason"):
                excluded.add(str(item["state"]))
            else:
                invalid_state_exclusions.append(str(item))
        for screen_id in entry_screens:
            if screen_id in addressed_states:
                addressed_states[screen_id].update(covered | excluded)
    missing_states = {
        screen_id: sorted(required_states - states)
        for screen_id, states in addressed_states.items()
        if required_states - states
    }

    source_coverage = round(len(sourced) / len(meaningful), 3) if meaningful else 0
    evidence_coverage = round(len(evidence_nodes) / len(meaningful), 3) if meaningful else 0
    confidence_coverage = round(len(confident) / len(meaningful), 3) if meaningful else 0
    appearance_coverage = round(len(appearance_complete_nodes) / len(visual), 3) if visual else 0
    semantic_coverage = round(len(semantic_nodes) / len(interactive_items), 3) if interactive_items else 1
    standard_coverage = round(len(standard_complete) / len(meaningful_items), 3) if meaningful_items else 0
    target_coverage = round(len(target_complete) / len(interactive_items), 3) if interactive_items else 1
    contrast_coverage = round(len(contrast_resolved) / len(contrast_items), 3) if contrast_items else 1
    total_state_checks = len(required_states) * len(screens)
    state_coverage = round(
        sum(len(required_states & states) for states in addressed_states.values()) / total_state_checks, 3
    ) if total_state_checks else 1
    component_coverage = round(len(mapped_component_nodes) / len(project_component_nodes), 3) if project_component_nodes else 1
    reasons: list[str] = []
    expected_status = "translated" if design_mode == "reconstruct" else "designed"
    if design_mode not in {"reconstruct", "generate", "redesign"}:
        reasons.append(f"Unsupported design mode: {design_mode}.")
    if fidelity.get("status") != expected_status:
        reasons.append(f"Fidelity status must be {expected_status} for {design_mode} mode.")
    if design_mode == "reconstruct" and fidelity.get("sourceDerived") is not True:
        reasons.append("Reconstruction must be explicitly marked sourceDerived.")
    if placeholders:
        reasons.append(f"IR contains {len(placeholders)} untranslated or unsupported placeholder nodes.")
    if not meaningful:
        reasons.append("IR contains no meaningful UI nodes.")
    if design_mode == "reconstruct" and source_coverage < 0.8:
        reasons.append(f"Only {source_coverage:.0%} of meaningful nodes map to source; at least 80% is required.")
    if design_mode in {"generate", "redesign"} and evidence_coverage < 0.9:
        reasons.append(f"Only {evidence_coverage:.0%} of meaningful nodes have project, standard, or decision evidence; at least 90% is required.")
    if appearance_coverage < 0.9:
        reasons.append(f"Only {appearance_coverage:.0%} of visual nodes have explicit appearance and geometry; at least 90% is required.")
    if catalog.get("enforce") is True:
        if catalog.get("status") != "ready":
            reasons.append("The discovered project component catalog must be inspected and marked ready.")
        if component_coverage < 1:
            reasons.append("Every used project component must reference a mapped component catalog entry.")
    if design_mode in {"generate", "redesign"}:
        if not design.get("brief", {}).get("primaryTask"):
            reasons.append("Generate and redesign modes require a brief.primaryTask.")
        if ir.get("policyFile") and not design.get("policySnapshot"):
            reasons.append("A discovered project UI policy must be copied into design.policySnapshot before design work.")
        if missing_profiles or invalid_profiles:
            reasons.append("Every target platform needs a valid Material 3, Apple HIG, web-platform, or reasoned project profile.")
        if semantic_coverage < 1:
            reasons.append("Every interactive node needs semantics.role and semantics.label.")
        if standard_coverage < 1:
            reasons.append("Every meaningful node needs a matching platform component reference or a valid design decision.")
        if target_coverage < 1:
            reasons.append(f"Interactive target sizes are missing or below platform baseline for {len(target_failures)} nodes.")
        if contrast_coverage < 1 or contrast_failures:
            reasons.append(f"Text contrast is unresolved for {len(contrast_unresolved)} nodes and below WCAG thresholds for {len(contrast_failures)} nodes.")
        if missing_states or invalid_state_exclusions:
            reasons.append("Every screen must address default, loading, empty, error, offline, permission, disabled, success, and destructive-confirmation states; non-applicable states need reasons.")
    if design_mode in {"reconstruct", "redesign"} and missing_screen_keys:
        reasons.append(f"IR is missing {len(missing_screen_keys)} discovered screens; translate or explicitly exclude them with reasons.")
    if design_mode in {"reconstruct", "redesign"} and missing_routes:
        reasons.append(f"IR is missing {len(missing_routes)} discovered routes; map or explicitly exclude them with reasons.")
    if invalid_screen_exclusions or invalid_route_exclusions:
        reasons.append("Every excluded screen or route must be an object with a stable key and non-empty reason.")
    if design_mode in {"reconstruct", "redesign"} and missing_navigation_targets:
        reasons.append(f"IR is missing screens or navigate actions for {len(missing_navigation_targets)} discovered navigation targets.")
    if invalid_navigation_exclusions:
        reasons.append("Every excluded navigation target must include target and a non-empty reason.")
    return {
        "status": "blocked" if reasons else "reviewable",
        "designMode": design_mode,
        "meaningfulNodes": len(meaningful),
        "placeholderNodes": len(placeholders),
        "sourceCoverage": source_coverage,
        "evidenceCoverage": evidence_coverage,
        "highConfidenceCoverage": confidence_coverage,
        "appearanceCoverage": appearance_coverage,
        "semanticCoverage": semantic_coverage,
        "standardCoverage": standard_coverage,
        "targetCoverage": target_coverage,
        "contrastCoverage": contrast_coverage,
        "stateCoverage": state_coverage,
        "componentCoverage": component_coverage,
        "catalogComponents": len(catalog_entries),
        "screenCoverage": round((len(expected_screen_keys) - len(missing_screen_keys)) / len(expected_screen_keys), 3) if expected_screen_keys else 1,
        "routeCoverage": round((len(expected_routes) - len(missing_routes)) / len(expected_routes), 3) if expected_routes else 1,
        "interactionActions": len(actions),
        "navigationActions": len(navigation_actions),
        "navigationCoverage": round((len(expected_navigation_targets) - len(missing_navigation_targets)) / len(expected_navigation_targets), 3) if expected_navigation_targets else 1,
        "missingNavigationTargets": missing_navigation_targets,
        "missingScreens": missing_screen_keys,
        "missingRoutes": missing_routes,
        "targetFailures": target_failures,
        "contrastFailures": contrast_failures,
        "contrastUnresolved": contrast_unresolved,
        "missingStates": missing_states,
        "reasons": reasons,
    }


def resolve_assets(ir: dict[str, Any]) -> dict[str, Any]:
    rendered = copy.deepcopy(ir)
    project_root = Path(rendered.get("project", {}).get("root", ".")).resolve()

    def embed(asset: str) -> tuple[str | None, str | None]:
        if asset.startswith("data:"):
            return asset, None
        if asset.startswith(("http://", "https://")):
            return None, "Remote assets are not embedded"
        path = (project_root / asset).resolve()
        if not path.is_relative_to(project_root):
            return None, "Asset path escapes the project root"
        try:
            if not path.is_file() or path.stat().st_size > 2_500_000:
                return None, "Missing or larger than 2.5 MB"
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{encoded}", None
        except OSError as exc:
            return None, str(exc)

    for node in rendered.get("nodes", {}).values():
        asset = node.get("asset")
        if not isinstance(asset, str) or not asset:
            continue
        resolved, error = embed(asset)
        if resolved:
            node["resolvedAsset"] = resolved
        if error:
            node["assetError"] = error
    for font in rendered.get("fonts", []):
        asset = font.get("asset")
        if not isinstance(asset, str) or not asset:
            continue
        resolved, error = embed(asset)
        if resolved:
            font["resolvedAsset"] = resolved
        if error:
            font["assetError"] = error
    return rendered


CSS = r"""
*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:#eef1f5;color:#111827}button,input,textarea,select{font:inherit}.review-app{min-height:100vh;display:grid;grid-template-columns:260px minmax(320px,1fr) 300px}.sidebar,.inspector{background:#fff}.sidebar{border-right:1px solid #d8dee8;padding:20px 14px}.inspector{border-left:1px solid #d8dee8;padding:20px;overflow-wrap:anywhere}.brand{font-size:15px;font-weight:700;margin:0 6px 4px}.project{font-size:12px;color:#667085;margin:0 6px 12px}.audit{margin:0 6px 18px;font-size:11px;color:#475467}.screen-list{display:grid;gap:5px}.screen-link{width:100%;border:0;background:transparent;color:#344054;text-align:left;padding:9px 10px;border-radius:8px;cursor:pointer}.screen-link:hover{background:#f2f4f7}.screen-link[aria-current=true]{background:#eaf1ff;color:#174ea6;font-weight:650}.workspace{min-width:0;display:flex;flex-direction:column}.toolbar{height:58px;background:#fff;border-bottom:1px solid #d8dee8;display:flex;align-items:center;justify-content:space-between;padding:0 18px;gap:14px}.toolbar-group{display:flex;align-items:center;gap:8px}.tool-button{border:1px solid #cfd6e1;background:#fff;color:#344054;border-radius:8px;padding:7px 11px;cursor:pointer}.tool-button[aria-pressed=true]{background:#1d4ed8;color:#fff;border-color:#1d4ed8}.screen-title{font-size:14px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.stage{flex:1;display:flex;align-items:flex-start;justify-content:center;padding:30px;overflow:auto;background-image:linear-gradient(45deg,rgba(15,23,42,.025) 25%,transparent 25%),linear-gradient(-45deg,rgba(15,23,42,.025) 25%,transparent 25%),linear-gradient(45deg,transparent 75%,rgba(15,23,42,.025) 75%),linear-gradient(-45deg,transparent 75%,rgba(15,23,42,.025) 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}.device{box-sizing:content-box;flex:0 0 auto;position:relative;background:transparent;box-shadow:0 18px 55px rgba(15,23,42,.2);overflow:hidden;transform-origin:top center}.device.phone.framed{border:10px solid #20242b;border-radius:38px}.device.desktop.framed{border:1px solid #aeb7c5;border-radius:10px}.device-content{width:100%;height:100%;overflow:auto;position:relative;background:transparent}.device-content>.ui-node{min-height:100%}.ui-node{min-width:0;margin:0}.ui-node[data-selected=true]{outline:3px solid #2563eb!important;outline-offset:2px}.ui-container,.ui-card,.ui-list{display:flex}.ui-text{white-space:pre-wrap}.ui-button{appearance:none;-webkit-appearance:none;border:0;padding:0;margin:0;background:transparent;color:inherit;text-align:inherit;cursor:pointer}.ui-button:focus-visible,.tool-button:focus-visible,.screen-link:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}.ui-input{appearance:none;-webkit-appearance:none;border:0;padding:0;margin:0;background:transparent;color:inherit;min-width:0}.ui-input::placeholder{color:var(--placeholder-color,currentColor);opacity:1}.ui-image{display:block}.ui-icon{display:inline-flex;align-items:center;justify-content:center}.ui-spacer{flex:0 0 auto}.ui-custom{padding:14px;border:1px dashed #d97706;border-radius:8px;background:#fff7ed;color:#9a3412;font-size:13px}.empty{padding:40px;text-align:center;color:#667085}.inspect-heading{font-size:13px;margin:0 0 14px}.inspect-empty{font-size:13px;line-height:1.5;color:#667085}.inspect-table{display:grid;grid-template-columns:86px 1fr;gap:8px 10px;font-size:12px}.inspect-table dt{color:#667085}.inspect-table dd{margin:0;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.confidence{display:inline-flex;padding:2px 7px;border-radius:999px;font-size:11px;font-family:inherit}.confidence.exact{background:#dcfce7;color:#166534}.confidence.high{background:#dbeafe;color:#1e40af}.confidence.approximate{background:#ffedd5;color:#9a3412}.confidence.unsupported{background:#fee2e2;color:#991b1b}.warning-panel{margin-top:22px;border-top:1px solid #eaecf0;padding-top:16px}.warning-panel summary{cursor:pointer;font-size:12px;font-weight:650}.warning-panel ul{padding-left:18px;font-size:12px;line-height:1.45;color:#667085}@media(max-width:980px){.review-app{grid-template-columns:210px minmax(300px,1fr)}.inspector{display:none}}@media(max-width:720px){.review-app{display:block}.sidebar{border:0;border-bottom:1px solid #d8dee8}.screen-list{display:flex;overflow:auto}.screen-link{width:auto;white-space:nowrap}.toolbar{position:sticky;top:0;z-index:5}.stage{padding:18px}}
"""

VIEW_CSS = r"""
.toolbar-controls{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.view-button{border:0;background:transparent;color:#475467;border-radius:8px;padding:7px 10px;cursor:pointer}.view-button[aria-pressed=true]{background:#eaf1ff;color:#174ea6;font-weight:650}.stage.overview{display:block;padding:28px}.overview-canvas-shell{position:relative;min-width:100%;min-height:100%}.overview-canvas{position:absolute;left:0;top:0;transform-origin:top left}.overview-grid{display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;align-content:flex-start}.screen-card{flex:0 0 auto;min-width:0}.screen-card-header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.screen-card-title{font-size:13px;font-weight:700;color:#344054;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.screen-card-open{border:1px solid #cfd6e1;background:#fff;color:#344054;border-radius:7px;padding:5px 8px;cursor:pointer;font-size:11px}.overview-viewport{position:relative;overflow:hidden;background:transparent;box-shadow:0 8px 24px rgba(15,23,42,.14)}.overview-device{position:absolute;left:0;top:0;transform-origin:top left;background:transparent;overflow:hidden}.overview-device .device-content{overflow:hidden}.stage.prototype .device,.stage.single .device{flex:0 0 auto}.stage.overview .ui-node{pointer-events:none}.stage.overview.inspect-mode .ui-node{pointer-events:auto}.view-button:focus-visible,.screen-card-open:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}@media(max-width:1100px){.toolbar{height:auto;min-height:58px;padding-top:8px;padding-bottom:8px}.toolbar-controls{gap:8px}}@media(max-width:720px){.stage.overview{padding:18px}}
"""


LEGACY_JS = r"""
const ir=JSON.parse(document.getElementById('ui-ir-data').textContent);const nodes=ir.nodes||{};const screens=ir.screens||[];const state={interaction:'interact',view:'overview',screen:null,selected:null,nodeStates:{}};
const $=s=>document.querySelector(s);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const iconMarkup=name=>`<svg class="icon" aria-hidden="true"><use href="#icon-${esc(name)}"></use></svg>`;
function token(path){if(typeof path!=='string'||!path.startsWith('$'))return path;let value=ir.tokens;for(const part of path.slice(1).split('.'))value=value?.[part];return value??path}
function cssValue(value,unit='px'){value=token(value);if(typeof value==='number')return `${value}${unit}`;if(value==='fill')return '100%';if(value==='hug')return 'fit-content';return value??''}
function styleFor(node){
  const l=node.layout||{},s=node.style||{},out={};
  const raw=(key,value)=>{if(value!=null)out[key]=token(value)};
  const length=(key,value)=>{if(value!=null)out[key]=cssValue(value)};
  const direction=l.direction||((node.type==='container'||node.type==='list'||node.type==='card')?'column':null);
  if(direction){
    out.display='flex';
    if(direction==='row'||direction==='column')out.flexDirection=direction;
    if(direction==='grid'){
      out.display='grid';
      const columns=l.columns??2;
      out.gridTemplateColumns=typeof columns==='number'?`repeat(${columns},minmax(0,1fr))`:token(columns);
      if(l.rows!=null)out.gridTemplateRows=token(l.rows);
    }
    if(direction==='overlay'){out.position='relative';out.display='block'}
  }
  length('gap',l.gap);length('rowGap',l.rowGap);length('columnGap',l.columnGap);
  length('padding',l.padding);length('margin',l.margin);
  if(l.paddingHorizontal!=null){length('paddingLeft',l.paddingHorizontal);length('paddingRight',l.paddingHorizontal)}
  if(l.paddingVertical!=null){length('paddingTop',l.paddingVertical);length('paddingBottom',l.paddingVertical)}
  if(l.marginHorizontal!=null){length('marginLeft',l.marginHorizontal);length('marginRight',l.marginHorizontal)}
  if(l.marginVertical!=null){length('marginTop',l.marginVertical);length('marginBottom',l.marginVertical)}
  for(const side of ['Top','Right','Bottom','Left']){
    length(`padding${side}`,l[`padding${side}`]);length(`margin${side}`,l[`margin${side}`]);
  }
  for(const key of ['width','height','minWidth','maxWidth','minHeight','maxHeight','top','right','bottom','left','flexBasis'])length(key,l[key]);
  raw('position',l.position);raw('display',l.display);raw('overflow',l.overflow);raw('overflowX',l.overflowX);raw('overflowY',l.overflowY);
  raw('alignSelf',l.alignSelf);raw('order',l.order);raw('zIndex',l.zIndex);raw('aspectRatio',l.aspectRatio);
  raw('flexGrow',l.grow);raw('flexShrink',l.shrink);raw('flexWrap',l.wrap===true?'wrap':l.wrap);
  if(l.align)out.alignItems=({start:'flex-start',end:'flex-end',center:'center',stretch:'stretch',baseline:'baseline'}[l.align]||l.align);
  if(l.justify)out.justifyContent=({start:'flex-start',end:'flex-end',between:'space-between',around:'space-around',evenly:'space-evenly',center:'center'}[l.justify]||l.justify);
  const lengths={borderWidth:'borderWidth',borderTopWidth:'borderTopWidth',borderRightWidth:'borderRightWidth',borderBottomWidth:'borderBottomWidth',borderLeftWidth:'borderLeftWidth',radius:'borderRadius',radiusTopLeft:'borderTopLeftRadius',radiusTopRight:'borderTopRightRadius',radiusBottomRight:'borderBottomRightRadius',radiusBottomLeft:'borderBottomLeftRadius',fontSize:'fontSize',lineHeight:'lineHeight',letterSpacing:'letterSpacing',outlineWidth:'outlineWidth'};
  const raws={background:'background',backgroundColor:'backgroundColor',backgroundImage:'backgroundImage',color:'color',border:'border',borderColor:'borderColor',borderTopColor:'borderTopColor',borderRightColor:'borderRightColor',borderBottomColor:'borderBottomColor',borderLeftColor:'borderLeftColor',borderStyle:'borderStyle',outlineColor:'outlineColor',outlineStyle:'outlineStyle',opacity:'opacity',fontFamily:'fontFamily',fontWeight:'fontWeight',fontStyle:'fontStyle',textAlign:'textAlign',textDecoration:'textDecoration',textTransform:'textTransform',whiteSpace:'whiteSpace',overflowWrap:'overflowWrap',textOverflow:'textOverflow',objectFit:'objectFit',objectPosition:'objectPosition',boxShadow:'boxShadow',filter:'filter',backdropFilter:'backdropFilter',transform:'transform',transformOrigin:'transformOrigin',cursor:'cursor',visibility:'visibility'};
  for(const [key,cssKey] of Object.entries(lengths))length(cssKey,s[key]);
  for(const [key,cssKey] of Object.entries(raws))raw(cssKey,s[key]);
  if(s.shadow!=null)raw('boxShadow',s.shadow);
  if(s.placeholderColor!=null)raw('--placeholder-color',s.placeholderColor);
  const typo=token(s.typography);
  if(typo&&typeof typo==='object'){
    for(const key of ['fontSize','lineHeight','letterSpacing'])length(key,typo[key]);
    for(const key of ['fontFamily','fontWeight','fontStyle','textTransform'])raw(key,typo[key]);
  }
  if(s.css&&typeof s.css==='object')for(const [key,value] of Object.entries(s.css)){
    if(/^(--[a-z0-9-]+|[a-zA-Z][a-zA-Z0-9-]*)$/.test(key))out[key]=token(value);
  }
  return Object.entries(out).filter(([,v])=>v!==''&&v!=null).map(([k,v])=>`${k.replace(/[A-Z]/g,m=>'-'+m.toLowerCase())}:${v}`).join(';')
}
function effectiveNode(id){const base=nodes[id];if(!base)return null;const variant=base.states?.[state.nodeStates[id]];if(!variant)return base;return {...base,...variant,layout:{...(base.layout||{}),...(variant.layout||{})},style:{...(base.style||{}),...(variant.style||{})}}}
function provenance(id,node){const src=node.source||{},action=node.action||{},semantics=node.semantics||{},standard=node.standardRef||Object.entries(node.standardRefs||{}).map(([platform,ref])=>`${platform}:${ref}`).join(', ');return `data-node-id="${esc(id)}" data-source-file="${esc(src.file||'')}" data-source-line="${esc(src.line||'')}" data-source-symbol="${esc(src.symbol||'')}" data-component="${esc(node.component||'')}" data-confidence="${esc(node.confidence||'approximate')}" data-standard-ref="${esc(standard)}" data-decision-id="${esc(node.decisionId||'')}" data-semantic-role="${esc(semantics.role||'')}" data-semantic-label="${esc(semantics.label||'')}" data-target-size="${esc(typeof semantics.targetSize==='object'?`${semantics.targetSize.width||'?'}×${semantics.targetSize.height||'?'}`:(semantics.targetSize||''))}" data-action="${esc(action.type||'')}" data-target="${esc(action.target||'')}" data-action-state="${esc(action.state||'')}" data-action-off-state="${esc(action.offState||'')}"`}
function renderNode(id,stack=[]){const n=effectiveNode(id);if(!n)return `<div class="ui-custom">Missing node ${esc(id)}</div>`;if(stack.includes(id))return `<div class="ui-custom">Circular node ${esc(id)}</div>`;const style=styleFor(n),p=provenance(id,n),children=(n.children||[]).map(child=>renderNode(child,[...stack,id])).join('');switch(n.type){case'text':return `<div class="ui-node ui-text" ${p} style="${esc(style)}">${esc(n.text||'')}</div>`;case'button':return `<button type="button" class="ui-node ui-button" ${p} ${n.disabled?'disabled':''} style="${esc(style)}">${children||esc(n.text||n.component||'')}</button>`;case'input':return `<input class="ui-node ui-input" ${p} type="${esc(n.inputType||'text')}" value="${esc(n.value||'')}" placeholder="${esc(n.placeholder||'')}" ${n.disabled?'disabled':''} style="${esc(style)}">`;case'image':return n.resolvedAsset?`<img class="ui-node ui-image" ${p} src="${n.resolvedAsset}" alt="${esc(n.alt||'')}" style="${esc(style)}">`:`<div class="ui-node ui-custom" ${p}>Asset unavailable: ${esc(n.asset||'')}</div>`;case'icon':return n.resolvedAsset?`<img class="ui-node ui-icon" ${p} src="${n.resolvedAsset}" alt="${esc(n.alt||'')}" style="${esc(style)}">`:`<span class="ui-node ui-icon" ${p} style="${esc(style)}">${esc(n.iconName||'◇')}</span>`;case'spacer':return `<div class="ui-node ui-spacer" ${p} style="${esc(style)}"></div>`;case'custom':return `<div class="ui-node ui-custom" ${p} style="${esc(style)}">${esc(n.text||n.component||'Unsupported UI')}</div>`;case'card':return `<div class="ui-node ui-card" ${p} style="${esc(style)}">${children}</div>`;case'list':return `<div class="ui-node ui-list" ${p} style="${esc(style)}">${children}</div>`;default:return `<div class="ui-node ui-container" ${p} style="${esc(style)}">${children}</div>`}}
const vp=ir.viewport||{width:390,height:844,device:'phone'};
function currentFromLocation(){const id=new URL(location.href).searchParams.get('screen');return screens.some(s=>s.id===id)?id:screens[0]?.id}
function viewFromLocation(){const view=new URL(location.href).searchParams.get('view');return ['overview','prototype','single'].includes(view)?view:'overview'}
function viewportFor(screen){return {...vp,...(screen?.viewport||{})}}
function writeLocation(push=true){const u=new URL(location.href);u.searchParams.set('view',state.view);if(state.screen)u.searchParams.set('screen',state.screen);const payload={view:state.view,screen:state.screen};push?history.pushState(payload,'',u):history.replaceState(payload,'',u)}
function deviceMarkup(screen,extraClass=''){const screenVp=viewportFor(screen);return `<div class="device ${esc(extraClass)}" data-width="${esc(screenVp.width)}" data-height="${esc(screenVp.height)}" data-device="${esc(screenVp.device||'phone')}" data-frame="${screenVp.frame===true}" data-background="${esc(screenVp.background||'')}"><div class="device-content">${renderNode(screen.root)}</div></div>`}
function configureDevice(device){device.style.width=`${device.dataset.width}px`;device.style.height=`${device.dataset.height}px`;device.classList.add(device.dataset.device==='desktop'?'desktop':'phone');if(device.dataset.frame==='true')device.classList.add('framed');device.querySelector('.device-content').style.background=token(device.dataset.background)||'transparent'}
function overviewMarkup(){return `<div class="overview-grid">${screens.map(screen=>{const screenVp=viewportFor(screen),scale=screenVp.device==='desktop'?0.2:0.52;return `<article class="screen-card" data-screen-card="${esc(screen.id)}"><header class="screen-card-header"><span class="screen-card-title">${esc(screen.name)}</span><button type="button" class="screen-card-open" data-open-screen="${esc(screen.id)}">Open</button></header><div class="overview-viewport" style="width:${screenVp.width*scale}px;height:${screenVp.height*scale}px">${deviceMarkup(screen,'overview-device').replace('class="device overview-device"',`class="device overview-device" style="transform:scale(${scale})"`)}</div></article>`}).join('')}</div>`}
function renderView(){const screen=screens.find(item=>item.id===state.screen)||screens[0];state.screen=screen?.id;document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.view===state.view)));document.querySelectorAll('.screen-link').forEach(button=>button.setAttribute('aria-current',String(button.dataset.screen===state.screen)));$('.screen-title').textContent=state.view==='overview'?`All screens (${screens.length})`:screen?.name||'';const stage=$('.stage');stage.className=`stage ${state.view}${state.interaction==='inspect'?' inspect-mode':''}`;stage.innerHTML=state.view==='overview'?overviewMarkup():(screen?deviceMarkup(screen):'<div class="empty">No screens</div>');document.querySelectorAll('.device').forEach(configureDevice);bindNodes();document.querySelectorAll('[data-open-screen]').forEach(button=>button.addEventListener('click',()=>setScreen(button.dataset.openScreen,'single')));selectNode(null)}
function setView(view,push=true){if(!['overview','prototype','single'].includes(view))return;state.view=view;writeLocation(push);renderView()}
function setScreen(id,view='single',push=true){if(!screens.some(screen=>screen.id===id))return;state.screen=id;state.view=view;writeLocation(push);renderView()}
function navigate(id,push=true){setScreen(id,'prototype',push)}
function applyAction(el,event){const type=el.dataset.action,target=el.dataset.target;if(!type||state.view==='overview')return;if(type==='navigate'){if(state.view==='prototype'){event.preventDefault();event.stopPropagation();navigate(target)}return}if(type==='back'){event.preventDefault();event.stopPropagation();history.back();return}if(type==='set-node-state'){event.preventDefault();event.stopPropagation();state.nodeStates[target]=el.dataset.actionState;renderView();return}if(type==='toggle-node-state'||type==='toggle'){event.preventDefault();event.stopPropagation();state.nodeStates[target]=state.nodeStates[target]===el.dataset.actionState?(el.dataset.actionOffState||'default'):el.dataset.actionState;renderView();return}if(type==='reset-state'){event.preventDefault();event.stopPropagation();state.nodeStates={};renderView()}}
function bindNodes(){document.querySelectorAll('.ui-node').forEach(el=>el.addEventListener('click',event=>{if(state.interaction==='inspect'){event.preventDefault();event.stopPropagation();selectNode(el);return}applyAction(el,event)}))}
function selectNode(el){document.querySelectorAll('[data-selected=true]').forEach(n=>n.removeAttribute('data-selected'));state.selected=el;if(!el){$('.inspect-body').innerHTML='<p class="inspect-empty">Switch to Inspect and select an element to see its source mapping, standard, semantics, and fidelity.</p>';return}el.dataset.selected='true';const c=el.dataset.confidence||'approximate';$('.inspect-body').innerHTML=`<dl class="inspect-table"><dt>Node</dt><dd>${esc(el.dataset.nodeId)}</dd><dt>Component</dt><dd>${esc(el.dataset.component||'—')}</dd><dt>Source</dt><dd>${esc(el.dataset.sourceFile||'—')}${el.dataset.sourceLine?':'+esc(el.dataset.sourceLine):''}</dd><dt>Symbol</dt><dd>${esc(el.dataset.sourceSymbol||'—')}</dd><dt>Standard</dt><dd>${esc(el.dataset.standardRef||'—')}</dd><dt>Decision</dt><dd>${esc(el.dataset.decisionId||'—')}</dd><dt>Semantics</dt><dd>${esc(el.dataset.semanticRole||'—')}${el.dataset.semanticLabel?' · '+esc(el.dataset.semanticLabel):''}</dd><dt>Target</dt><dd>${esc(el.dataset.targetSize||'—')}</dd><dt>Fidelity</dt><dd><span class="confidence ${esc(c)}">${esc(c)}</span></dd></dl>`}
document.querySelectorAll('[data-interaction]').forEach(button=>button.addEventListener('click',()=>{state.interaction=button.dataset.interaction;document.querySelectorAll('[data-interaction]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));renderView()}));document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.view)));document.querySelectorAll('.screen-link').forEach(button=>button.addEventListener('click',()=>setScreen(button.dataset.screen,'single')));addEventListener('popstate',()=>{state.screen=currentFromLocation();state.view=viewFromLocation();renderView()});state.screen=currentFromLocation();state.view=viewFromLocation();writeLocation(false);renderView();
"""

REVIEW_CSS = r"""
.review-app{--left-panel:230px;--right-panel:300px;--left-grip:5px;--right-grip:5px;height:100vh;min-height:0;overflow:hidden;grid-template-columns:var(--left-panel) var(--left-grip) minmax(360px,1fr) var(--right-grip) var(--right-panel)}
.sidebar,.inspector{min-width:0;height:100vh;overflow:auto;padding:12px 10px}.brand{font-size:13px;margin:0 4px 2px}.project{font-size:10px;margin:0 4px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.audit-panel{margin:0 2px 8px;border:1px solid #e4e7ec;border-radius:6px;background:#f8fafc}.audit-panel>summary{cursor:pointer;list-style:none;padding:5px 7px;font-size:10px;font-weight:650;color:#475467}.audit-panel>summary::-webkit-details-marker{display:none}.audit-panel>summary:before{content:'›';display:inline-block;margin-right:5px}.audit-panel[open]>summary:before{transform:rotate(90deg)}.audit-panel .audit{margin:0;padding:0 7px 7px;font-size:9px;line-height:1.35;color:#667085}
.panel-resizer{position:relative;z-index:20;background:#e4e7ec;cursor:col-resize;touch-action:none}.panel-resizer:after{content:'';position:absolute;inset:0 -3px}.panel-resizer:hover,.panel-resizer:focus-visible,.review-app.resizing .panel-resizer{background:#60a5fa;outline:none}.review-app.sidebar-hidden>.sidebar,.review-app.inspector-hidden>.inspector{visibility:hidden;padding:0;border:0;overflow:hidden}.review-app.sidebar-hidden>.left-resizer,.review-app.inspector-hidden>.right-resizer{pointer-events:none}
.workspace{height:100vh;min-height:0;position:relative;overflow:hidden;container-type:inline-size}.workbench-header{flex:0 0 auto;position:relative;z-index:15;box-shadow:0 2px 8px rgba(15,23,42,.16)}.menu-bar{height:29px;display:flex;align-items:center;gap:10px;padding:0 8px;background:#f8fafc;border-bottom:1px solid #cbd5e1;color:#334155}.app-mark{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:750;white-space:nowrap}.app-mark-dot{width:8px;height:8px;border-radius:2px;background:#2563eb}.menu-strip{display:flex;align-items:stretch;height:100%}.menu{position:relative;margin:0}.menu>summary{height:100%;display:flex;align-items:center;list-style:none;padding:0 7px;cursor:pointer;font-size:10px;color:#475569}.menu>summary::-webkit-details-marker{display:none}.menu>summary:hover,.menu[open]>summary{background:#e2e8f0;color:#0f172a}.menu-popover{position:absolute;top:27px;left:0;z-index:30;min-width:176px;padding:5px;background:#fff;border:1px solid #cbd5e1;border-radius:7px;box-shadow:0 10px 28px rgba(15,23,42,.18)}.menu-popover button{display:block;width:100%;border:0;border-radius:5px;background:transparent;padding:6px 8px;text-align:left;color:#334155;font-size:11px;cursor:pointer}.menu-popover button:hover{background:#eff6ff;color:#1d4ed8}.menu-spacer{flex:1}.version-select{max-width:180px;border:1px solid #cbd5e1;border-radius:5px;padding:3px 6px;background:#fff;color:#334155;font-size:10px}
.action-bar{height:46px;display:flex;align-items:center;gap:8px;padding:6px 8px;background:#18324f;color:#fff}.panel-toggle{flex:0 0 auto;width:28px;height:28px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.22);border-radius:6px;background:rgba(255,255,255,.08);color:#fff;font-size:18px;line-height:1;cursor:pointer}.panel-toggle:hover{background:rgba(255,255,255,.18)}.screen-context{min-width:110px;max-width:240px;display:grid;gap:1px}.screen-title{font-size:11px;color:#fff}.navigation-preview-label{display:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px;color:#fbbf24}.navigation-preview-label.visible{display:block}.mode-switch,.interaction-switch{display:flex;align-items:center;padding:2px;border-radius:7px;background:rgba(3,16,31,.34)}.mode-button,.interaction-button,.compare-button{height:28px;border:0;border-radius:5px;padding:0 8px;background:transparent;color:#cbd5e1;font-size:10px;white-space:nowrap;cursor:pointer}.mode-button .button-icon,.interaction-button .button-icon{margin-right:4px;font-size:12px}.mode-button[aria-pressed=true],.interaction-button[aria-pressed=true]{background:#fff;color:#174ea6;font-weight:700;box-shadow:0 1px 3px rgba(0,0,0,.18)}.mode-status{display:flex;align-items:center;gap:5px;min-width:0;padding:4px 7px;border:1px solid rgba(255,255,255,.2);border-radius:999px;color:#dbeafe;font-size:9px;white-space:nowrap}.mode-status:before{content:'';width:6px;height:6px;border-radius:50%;background:#94a3b8}.mode-status.prototype:before{background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.18)}.action-spacer{flex:1}.compare-controls{display:none;align-items:center;gap:2px}.review-app[data-view=compare] .compare-controls{display:flex}.review-app[data-view=compare] .screen-context{display:none}.review-app[data-view=compare] .interaction-button .button-label{display:none}.review-app[data-view=compare] .interaction-button{width:30px;padding:0}.compare-button{background:rgba(255,255,255,.08)}.compare-button[aria-pressed=true]{background:#fff;color:#174ea6}
.stage{min-height:0}.stage.prototype,.stage.single{justify-content:flex-start}.stage.prototype>.device,.stage.single>.device{margin-inline:auto}.floating-zoom{position:absolute;right:14px;bottom:14px;z-index:16;display:flex;align-items:center;gap:2px;padding:3px;border:1px solid #cbd5e1;border-radius:8px;background:rgba(255,255,255,.94);box-shadow:0 5px 18px rgba(15,23,42,.18);backdrop-filter:blur(6px)}.zoom-button{height:25px;min-width:25px;border:0;border-radius:5px;background:transparent;color:#334155;font-size:12px;cursor:pointer}.zoom-button:hover{background:#eaf1ff;color:#174ea6}.zoom-label{min-width:39px;text-align:center;font-size:9px;color:#475467}.workbench-toast{position:absolute;left:50%;bottom:18px;z-index:40;transform:translate(-50%,12px);max-width:min(440px,calc(100% - 120px));padding:8px 11px;border-radius:7px;background:#0f172a;color:#fff;font-size:11px;box-shadow:0 10px 30px rgba(15,23,42,.25);opacity:0;pointer-events:none;transition:.18s}.workbench-toast.visible{opacity:1;transform:translate(-50%,0)}
.screen-list{display:block}.screen-tree-group{margin:1px 0}.screen-tree-group>summary{list-style:none;display:flex;align-items:center;gap:5px;min-height:24px;padding:3px 6px;border-radius:5px;cursor:pointer;color:#475467;font-size:10px;font-weight:700;line-height:1.2}.screen-tree-group>summary::-webkit-details-marker{display:none}.screen-tree-group>summary:before{content:'›';display:inline-block;transition:transform .15s}.screen-tree-group[open]>summary:before{transform:rotate(90deg)}.screen-tree-group>summary:hover{background:#f2f4f7}.screen-tree-children{margin-left:7px;padding-left:5px;border-left:1px solid #e4e7ec}.screen-link{position:relative;min-height:24px;padding-top:4px!important;padding-bottom:4px!important;padding-right:6px!important;border-radius:5px;font-size:11px;line-height:1.25;white-space:normal}.screen-link[aria-current=true]{background:#eaf1ff;color:#174ea6;font-weight:700}.screen-link[aria-current=true]:before{content:'';position:absolute;left:1px;top:5px;bottom:5px;width:2px;border-radius:2px;background:#2563eb}.screen-link[data-navigation-preview=true]{background:#fff4e5;color:#b54708;box-shadow:inset 0 0 0 1px #fdb022;font-weight:700}.screen-link[aria-current=true][data-navigation-preview=true]{background:linear-gradient(90deg,#eaf1ff 0 72%,#fff4e5 72%);color:#174ea6;box-shadow:inset -3px 0 0 #f79009}.tree-count{margin-left:auto;padding:1px 4px;border-radius:999px;background:#eef2f6;color:#64748b;font-size:8px;font-weight:600}
.inspector-header{display:flex;align-items:center;justify-content:space-between;gap:8px}.inspect-heading{margin:0;font-size:12px}.inspector-help{margin:8px 0 10px;border:1px solid #dbe3ee;border-radius:7px;background:#f8fafc}.inspector-help>summary{padding:6px 8px;cursor:pointer;font-size:10px;font-weight:700;color:#475569}.inspector-help p{margin:0;padding:0 8px 8px;color:#64748b;font-size:10px;line-height:1.45}.review-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:10px 0}.review-action{border:1px solid #cfd6e1;background:#fff;color:#344054;border-radius:6px;padding:6px 7px;cursor:pointer;font-size:10px}.review-action.primary{background:#1d4ed8;border-color:#1d4ed8;color:#fff}.review-decision{margin:7px 0 12px;padding:7px;border-radius:6px;background:#f2f4f7;color:#475467;font-size:10px}.review-decision.accepted{background:#dcfce7;color:#166534}.review-decision.rejected{background:#fee2e2;color:#991b1b}.queue-heading{font-size:11px;margin:15px 0 8px;padding-top:12px;border-top:1px solid #eaecf0}.annotation-list{display:grid;gap:7px}.annotation-card{border:1px solid #d8dee8;border-radius:7px;padding:8px;background:#fff}.annotation-card[data-status=accepted],.annotation-card[data-status=resolved]{border-color:#86efac}.annotation-card[data-status=rejected]{border-color:#fca5a5}.annotation-meta{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:#667085;text-transform:uppercase}.annotation-text{font-size:11px;line-height:1.4;margin:6px 0;color:#344054}.annotation-target{border:0;background:transparent;color:#1d4ed8;padding:0;cursor:pointer;font-size:10px;text-align:left}.annotation-controls{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}.annotation-status{border:1px solid #cfd6e1;background:#fff;border-radius:5px;padding:3px 5px;font-size:9px;cursor:pointer}.comment-form{display:grid;gap:7px;margin-top:10px;padding-top:10px;border-top:1px solid #eaecf0}.comment-form textarea{width:100%;min-height:72px;resize:vertical;border:1px solid #cfd6e1;border-radius:6px;padding:8px;font-size:11px}.comment-form select{border:1px solid #cfd6e1;border-radius:6px;padding:5px;font-size:10px}.comment-form button{border:0;border-radius:6px;background:#1d4ed8;color:#fff;padding:7px;cursor:pointer;font-size:10px}.inspect-empty{font-size:11px}.inspect-table{grid-template-columns:72px 1fr;gap:6px 8px;font-size:10px}
.automated-review{margin-top:10px;padding-top:10px;border-top:1px solid #e2e8f0}.review-section-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}.review-section-heading h2{margin:0;font-size:11px}.finding-total{padding:2px 6px;border-radius:999px;background:#eaf1ff;color:#174ea6;font-size:9px;font-weight:700}.audit-summary{margin-bottom:7px;color:#475569;font-size:10px;line-height:1.4}.audit-counts{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}.audit-count{padding:2px 5px;border-radius:999px;background:#f1f5f9;color:#475569;font-size:8px}.audit-gaps{margin-top:6px}.audit-gaps summary{cursor:pointer;font-size:9px;font-weight:700;color:#64748b}.audit-gaps ul{margin:5px 0 0;padding-left:16px;font-size:9px;color:#64748b}.finding-filters{display:flex;gap:3px;overflow-x:auto;margin:7px 0}.finding-filter{border:1px solid #d8dee8;border-radius:5px;background:#fff;padding:3px 5px;color:#475569;font-size:8px;cursor:pointer;white-space:nowrap}.finding-filter[aria-pressed=true]{border-color:#2563eb;background:#eaf1ff;color:#174ea6;font-weight:700}.finding-list{display:grid;gap:6px}.finding-card{border:1px solid #d8dee8;border-left-width:4px;border-radius:7px;padding:7px;background:#fff}.finding-card[data-severity=blocker]{border-left-color:#7f1d1d}.finding-card[data-severity=high]{border-left-color:#dc2626}.finding-card[data-severity=medium]{border-left-color:#f59e0b}.finding-card[data-severity=low]{border-left-color:#3b82f6}.finding-card[data-decision=accepted]{background:#f0fdf4}.finding-card[data-decision=rejected]{opacity:.62}.finding-card-header{display:flex;align-items:flex-start;justify-content:space-between;gap:6px}.finding-title{margin:0;color:#1e293b;font-size:10px;line-height:1.3}.finding-severity{flex:0 0 auto;padding:2px 4px;border-radius:4px;background:#f1f5f9;color:#475569;font-size:7px;font-weight:800;text-transform:uppercase}.finding-meta{margin-top:3px;color:#64748b;font-size:8px}.finding-observation,.finding-impact,.finding-recommendation{margin:5px 0 0;color:#475569;font-size:9px;line-height:1.4}.finding-recommendation{color:#1e3a5f}.finding-evidence{margin-top:5px}.finding-evidence summary{cursor:pointer;color:#475569;font-size:8px;font-weight:700}.finding-evidence ul{margin:4px 0 0;padding-left:14px;color:#64748b;font-size:8px;line-height:1.35}.finding-actions{display:flex;gap:3px;flex-wrap:wrap;margin-top:6px}.finding-action{border:1px solid #cbd5e1;border-radius:5px;background:#fff;padding:3px 5px;color:#334155;font-size:8px;cursor:pointer}.finding-action.primary{border-color:#2563eb;background:#2563eb;color:#fff}.finding-action[aria-pressed=true]{border-color:#16a34a;background:#dcfce7;color:#166534}.screen-issue-count{margin-left:auto;min-width:15px;padding:1px 4px;border-radius:999px;background:#fee2e2;color:#b91c1c;text-align:center;font-size:8px;font-weight:800}.screen-issue-count[data-severity=medium],.screen-issue-count[data-severity=low]{background:#fff4e5;color:#b54708}.ui-node[data-finding-severity=blocker],.ui-node[data-finding-severity=high]{outline:3px solid #dc2626!important;outline-offset:2px}.ui-node[data-finding-severity=medium]{outline:3px solid #f59e0b!important;outline-offset:2px}.ui-node[data-finding-severity=low]{outline:3px solid #3b82f6!important;outline-offset:2px}.panel-section{margin:9px 0;border:1px solid #e2e8f0;border-radius:7px}.panel-section>summary{padding:6px 8px;cursor:pointer;color:#475569;font-size:10px;font-weight:700}.panel-section>.inspect-body{padding:0 8px 8px}
.compare-grid{display:grid;grid-template-columns:repeat(2,minmax(max-content,1fr));gap:28px;align-items:start}.compare-panel{display:grid;justify-items:center;gap:9px}.compare-label{font-size:12px;font-weight:700;color:#344054}.compare-overlay{position:relative;overflow:hidden;box-shadow:0 18px 55px rgba(15,23,42,.2)}.compare-overlay .device{position:absolute;inset:0;box-shadow:none}.compare-overlay .after-layer{overflow:hidden;width:var(--overlay-width,50%)}.compare-overlay-slider{width:min(520px,100%)}.ui-node[data-changed=true]{outline:2px dashed #7c3aed;outline-offset:-2px}.stage.compare{display:block}.stage.compare .compare-grid,.stage.compare .compare-overlay-wrap{width:max-content;margin:auto}.stage.compare .ui-node{pointer-events:none}.stage.comment-mode .ui-node{cursor:crosshair}.stage.comment-mode .ui-node:hover{outline:2px solid #f59e0b;outline-offset:1px}.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#98a2b3;margin-right:5px}.status-dot.proposal{background:#f59e0b}.status-dot.approved{background:#22c55e}.status-dot.rejected{background:#ef4444}
.audit-depth{margin-top:6px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc}.audit-depth>summary{padding:5px 6px;cursor:pointer;font-size:9px;font-weight:750;color:#475569}.audit-depth-list{display:grid;gap:4px;margin:0;padding:0 6px 6px;list-style:none}.audit-depth-item{padding:5px;border-radius:5px;background:#fff;color:#475569;font-size:8px;line-height:1.35}.audit-depth-item[data-result=fail],.audit-depth-item[data-status=finding]{border-left:3px solid #dc2626}.audit-depth-item[data-result=pass],.audit-depth-item[data-status=pass]{border-left:3px solid #16a34a}.audit-depth-item[data-result=not-run],.audit-depth-item[data-status=gap]{border-left:3px solid #f59e0b}
.audit-depth-title{display:flex;align-items:flex-start;justify-content:space-between;gap:5px}.audit-depth-links{display:flex;gap:3px;flex-wrap:wrap;margin-top:5px}.audit-depth-action{border:1px solid #cbd5e1;border-radius:4px;background:#fff;padding:2px 5px;color:#334155;font-size:8px;cursor:pointer}.audit-depth-action.primary{border-color:#2563eb;background:#eaf1ff;color:#174ea6}.audit-depth-unlinked{display:inline-block;margin-top:4px;color:#98a2b3;font-size:8px}.finding-context{display:flex;align-items:center;justify-content:space-between;gap:6px;margin:5px 0;padding:5px 6px;border-radius:5px;background:#fff7ed;color:#9a3412;font-size:8px}.finding-context button{border:0;background:transparent;color:#9a3412;font-size:8px;font-weight:700;cursor:pointer}.finding-decision-label{display:inline-flex;align-items:center;gap:3px;margin-top:5px;padding:2px 5px;border-radius:999px;background:#f1f5f9;color:#64748b;font-size:8px;font-weight:700}.finding-card[data-decision=accepted] .finding-decision-label{background:#dcfce7;color:#166534}.finding-card[data-decision=rejected] .finding-decision-label{background:#fee2e2;color:#991b1b}.finding-proposal-note{margin-top:5px;padding:4px 5px;border-radius:5px;background:#f8fafc;color:#64748b;font-size:8px}.fix-queue{margin:9px 0;border:1px solid #bfdbfe;border-radius:8px;background:#eff6ff}.fix-queue>summary{padding:7px 8px;cursor:pointer;color:#1e3a8a;font-size:10px;font-weight:800}.fix-queue-body{padding:0 8px 8px}.fix-queue-copy{margin:0 0 7px;color:#475569;font-size:9px;line-height:1.4}.fix-queue-stats{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:7px}.fix-queue-stat{padding:2px 5px;border-radius:999px;background:#fff;color:#475569;font-size:8px}.fix-queue-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px}.fix-queue-action{min-height:29px;border:1px solid #93c5fd;border-radius:6px;background:#fff;padding:4px 6px;color:#1d4ed8;font-size:9px;cursor:pointer}.fix-queue-action.primary{border-color:#1d4ed8;background:#1d4ed8;color:#fff}.fix-queue-action:disabled{cursor:not-allowed;opacity:.5}.review-workflow-guide{margin:6px 0 8px;padding:6px 7px;border-radius:6px;background:#f8fafc;color:#64748b;font-size:8px;line-height:1.4}.review-workflow-guide b{color:#334155}
.revision-badge{padding:1px 4px;border-radius:4px;background:#e2e8f0;color:#64748b;font-size:8px;font-weight:600}.revision-notice{margin:7px 0;padding:7px;border:1px solid #fdba74;border-radius:7px;background:#fff7ed;color:#9a3412;font-size:9px;line-height:1.4}.revision-notice-actions{display:flex;gap:4px;margin-top:6px}.revision-notice button{border:1px solid #fdba74;border-radius:5px;background:#fff;padding:3px 6px;color:#9a3412;font-size:8px;cursor:pointer}.review-phases{display:grid;grid-template-columns:repeat(5,1fr);gap:2px;margin:0 0 7px}.review-phase{min-width:0;padding:4px 2px;border-radius:4px;background:#dbe3ee;color:#64748b;text-align:center;font-size:7px;line-height:1.2}.review-phase.active{background:#2563eb;color:#fff;font-weight:700}.review-phase.complete{background:#dcfce7;color:#166534}.source-handoff{margin-top:7px;padding-top:7px;border-top:1px solid #bfdbfe}.source-handoff-copy{margin:0 0 5px;color:#64748b;font-size:8px;line-height:1.35}
.runtime-diagnostics>.diagnostics-body{padding:0 8px 8px}.diagnostics-copy{margin:0 0 7px;color:#64748b;font-size:9px;line-height:1.4}.diagnostics-actions{display:flex;gap:5px;flex-wrap:wrap}.diagnostics-action{min-height:27px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;padding:4px 7px;color:#334155;font-size:9px;cursor:pointer}.diagnostics-action.primary{border-color:#2563eb;background:#2563eb;color:#fff}.diagnostics-action:disabled{cursor:wait;opacity:.55}.diagnostics-status{float:right;padding:1px 5px;border-radius:999px;background:#f1f5f9;color:#64748b;font-size:8px}.diagnostics-status.running{background:#dbeafe;color:#1d4ed8}.diagnostics-status.fail{background:#fee2e2;color:#b91c1c}.diagnostics-status.pass{background:#dcfce7;color:#166534}.diagnostics-progress{margin-top:6px;color:#1d4ed8;font-size:9px}.diagnostics-summary{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}.diagnostics-count{padding:2px 5px;border-radius:999px;background:#f1f5f9;color:#475569;font-size:8px}.diagnostics-results{display:grid;gap:4px;margin-top:7px}.diagnostic-card{border:1px solid #e2e8f0;border-left-width:3px;border-radius:6px;background:#fff;padding:6px;color:#475569;font-size:8px;line-height:1.35}.diagnostic-card[data-result=pass]{border-left-color:#16a34a}.diagnostic-card[data-result=fail]{border-left-color:#dc2626}.diagnostic-card[data-result=warning]{border-left-color:#f59e0b}.diagnostic-card b{color:#1e293b}.diagnostic-meta{margin-top:2px;color:#94a3b8}.diagnostic-card-actions{display:flex;gap:3px;flex-wrap:wrap;margin-top:5px}.diagnostic-card-action{border:1px solid #cbd5e1;border-radius:4px;background:#fff;padding:2px 5px;color:#334155;font-size:8px;cursor:pointer}.diagnostic-card-action.primary{border-color:#2563eb;background:#eaf1ff;color:#174ea6}.diagnostics-empty{margin:7px 0 0;color:#64748b;font-size:9px}.ui-node[data-diagnostic-target=true]{outline:3px solid #7c3aed!important;outline-offset:2px}
@container(max-width:900px){.mode-status{display:none}.screen-context{max-width:130px}.mode-button,.interaction-button{padding-inline:6px}.mode-button .button-icon,.interaction-button .button-icon{margin-right:2px}}@container(max-width:690px){.screen-context{display:none}.mode-button .button-label,.interaction-button .button-label{display:none}.mode-button,.interaction-button{width:30px;padding:0}}@media(max-width:820px){.review-app{--right-panel:0px;--right-grip:0px}.inspector,.right-resizer{display:none}.compare-grid{grid-template-columns:1fr}}@media(max-width:620px){.review-app{--left-panel:0px;--left-grip:0px;display:grid}.sidebar,.left-resizer{display:none}.menu-strip{display:none}.action-bar{overflow-x:auto}.stage{padding:16px}}

/* Production workbench shell */
.icon-sprite{position:absolute;width:0;height:0;overflow:hidden}.icon,.app-logo,.empty-icon{display:block;width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.icon use,.app-logo use,.empty-icon use{pointer-events:none}
.review-app{--rail:44px;--left-panel:244px;--right-panel:324px;--left-grip:4px;--right-grip:4px;grid-template-columns:var(--rail) var(--left-panel) var(--left-grip) minmax(360px,1fr) var(--right-grip) var(--right-panel);background:#f4f5f7;color:#18202b}
.workbench-rail{position:relative;z-index:25;height:100vh;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 6px;background:#171b24;color:#a9b1bf;border-right:1px solid #0e1118}.rail-button{position:relative;width:32px;height:32px;display:grid;place-items:center;border:0;border-radius:7px;background:transparent;color:inherit;cursor:pointer}.rail-button:hover{background:#272d39;color:#fff}.rail-button[aria-pressed=true]{background:#30394a;color:#fff}.rail-button[aria-pressed=true]:before{content:'';position:absolute;left:-6px;top:8px;bottom:8px;width:2px;border-radius:2px;background:#7aa2ff}.rail-divider{width:22px;height:1px;margin:3px 0;background:#313744}.rail-spacer{flex:1}.rail-badge{position:absolute!important;right:-2px;top:-2px;min-width:14px;height:14px;display:grid;place-items:center;padding:0 3px!important;border:2px solid #171b24!important;border-radius:999px!important;background:#3b82f6!important;color:#fff!important;font-size:7px!important;line-height:1!important}.annotation-total:empty,.rail-badge:empty{display:none}
.sidebar,.inspector{height:100vh;padding:0;background:#fff;border-color:#dfe3e8;overflow:hidden}.sidebar{display:flex;flex-direction:column}.side-panel-header,.inspector-header{height:44px;flex:0 0 44px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 10px;border-bottom:1px solid #e7e9ed;background:#fff}.panel-kicker{display:block;color:#8a93a2;font-size:8px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.side-panel-title,.pane-heading h2{margin:1px 0 0;color:#1d2430;font-size:13px;line-height:1.1}.panel-close,.header-panel-button{width:28px;height:28px;display:grid;place-items:center;border:0;border-radius:6px;background:transparent;color:#707a89;cursor:pointer}.panel-close:hover,.header-panel-button:hover{background:#f0f2f5;color:#1f2937}.sidebar-project{margin:10px 12px 7px;overflow:hidden;color:#4b5563;font-size:10px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.tree-search{height:30px;display:flex;align-items:center;gap:7px;margin:0 10px 8px;padding:0 8px;border:1px solid #dfe3e8;border-radius:7px;background:#f8f9fb;color:#8a93a2}.tree-search .icon{width:14px;height:14px}.tree-search input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:#202733;font-size:10px}.tree-search:focus-within{border-color:#8fb3ff;background:#fff;box-shadow:0 0 0 2px rgba(59,130,246,.12)}.screen-list{flex:1;overflow:auto;padding:0 8px 12px}.sidebar-meta{flex:0 0 auto;max-height:30%;overflow:auto;padding:8px;border-top:1px solid #eceef1;background:#fafbfc}.audit-panel{margin:0;border:0;background:transparent}.audit-panel>summary{padding:5px;color:#687384}.audit-panel .audit{padding:0 5px 6px}.warning-panel{margin:6px 4px 0;padding-top:6px}
.screen-tree-group>summary{min-height:26px;padding:4px 6px;border-radius:6px;color:#596474;font-size:10px}.screen-tree-children{margin-left:8px;padding-left:7px;border-left-color:#e5e8ec}.screen-link{min-height:27px;padding:5px 22px 5px 8px!important;border-radius:6px;color:#394454;font-size:10px;line-height:1.25}.screen-link:hover{background:#f2f4f7}.screen-link[aria-current=true]{background:#e9f0ff;color:#2457b8}.screen-link[aria-current=true]:before{left:2px;top:6px;bottom:6px}.tree-count{background:transparent;color:#9aa2af}
.panel-resizer{width:auto;background:#eef0f3}.panel-resizer:after{inset:0 -4px}.panel-resizer:hover,.panel-resizer:focus-visible,.review-app.resizing .panel-resizer{background:#7aa2ff}
.workspace{background:#f4f5f7}.workbench-header{height:44px;box-shadow:none;border-bottom:1px solid #dfe3e8;background:rgba(255,255,255,.96)}.menu-bar{height:44px;gap:6px;padding:0 8px 0 10px;border:0;background:transparent}.app-mark{height:30px;gap:7px;padding-right:9px;color:#222a36;font-size:11px}.app-logo{width:18px;height:18px;padding:3px;border-radius:5px;background:#202735;color:#fff;stroke-width:1.35}.revision-badge{padding:1px 4px;background:#eef0f3;color:#8992a0;font-size:7px}.menu-strip{height:30px;align-self:center}.menu>summary{height:30px;padding:0 7px;border-radius:5px;color:#657080;font-size:9px}.menu>summary:hover,.menu[open]>summary{background:#eff1f4;color:#242c38}.menu-popover{top:33px;min-width:190px;padding:5px;border-color:#d9dde3;border-radius:9px;box-shadow:0 12px 34px rgba(25,31,42,.18)}.menu-popover button{min-height:30px;padding:6px 9px;border-radius:6px;font-size:10px}.screen-context{min-width:0;max-width:min(360px,32vw);display:block;margin-left:4px;padding-left:10px;border-left:1px solid #e3e6ea}.screen-title{overflow:hidden;color:#303947;font-size:10px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.navigation-preview-label{font-size:8px;color:#b56a13}.version-select{height:28px;max-width:190px;padding:0 26px 0 8px;border-color:#d9dde3;border-radius:7px;background:#f8f9fb;color:#465160;font-size:9px}.header-panel-button{flex:0 0 auto}.mode-status{height:24px;padding:0 8px;border:0;background:#f0f2f5;color:#657080;font-size:8px}.mode-status:before{width:5px;height:5px}.mode-status.prototype{background:#e9f7ef;color:#25613d}.mode-status.prototype:before{box-shadow:none}
.stage{padding:46px 40px 72px;background-color:#f1f2f4;background-size:20px 20px;background-position:0 0,0 10px,10px -10px,-10px 0}.canvas-tools{position:absolute;left:50%;bottom:14px;z-index:18;display:flex;align-items:center;gap:5px;transform:translateX(-50%);padding:4px;border:1px solid #d8dce2;border-radius:10px;background:rgba(255,255,255,.96);box-shadow:0 8px 28px rgba(26,32,44,.15);backdrop-filter:blur(10px)}.mode-switch,.interaction-switch{gap:2px;padding:0;background:transparent}.mode-button,.interaction-button,.compare-button{height:30px;display:flex;align-items:center;justify-content:center;gap:5px;padding:0 8px;border-radius:7px;color:#657080;font-size:9px}.mode-button .icon,.interaction-button .icon{width:15px;height:15px}.mode-button:hover,.interaction-button:hover{background:#f0f2f5;color:#26303d}.mode-button[aria-pressed=true],.interaction-button[aria-pressed=true]{background:#273142;color:#fff;font-weight:650;box-shadow:none}.tool-divider{width:1px;height:20px;background:#e1e4e8}.compare-controls{position:absolute;left:50%;top:54px;z-index:17;transform:translateX(-50%);gap:2px;padding:3px;border:1px solid #d8dce2;border-radius:8px;background:#fff;box-shadow:0 5px 16px rgba(26,32,44,.1)}.compare-button{height:27px}.compare-button[aria-pressed=true]{background:#273142;color:#fff}.review-app[data-view=compare] .screen-context{display:block}.review-app[data-view=compare] .interaction-button{width:auto;padding:0 8px}.review-app[data-view=compare] .interaction-button .button-label{display:inline}.floating-zoom{right:14px;bottom:14px;gap:1px;padding:3px;border-color:#d8dce2;border-radius:9px;background:rgba(255,255,255,.96);box-shadow:0 6px 20px rgba(26,32,44,.12)}.zoom-button{height:28px;min-width:28px;border-radius:6px;color:#596474}.zoom-button .icon{width:14px;height:14px;margin:auto}.zoom-label{min-width:42px;font-size:9px;font-variant-numeric:tabular-nums}.workbench-toast{bottom:58px;border-radius:8px;background:#202735;font-size:10px}
.inspector{display:flex;flex-direction:column}.inspector-header{padding-left:7px}.inspector-tabs{min-width:0;display:flex;align-self:stretch;gap:2px}.inspector-tab{position:relative;min-width:0;height:43px;display:flex;align-items:center;gap:5px;border:0;border-bottom:2px solid transparent;background:transparent;padding:0 7px;color:#707a89;font-size:9px;cursor:pointer}.inspector-tab:hover{color:#28313e}.inspector-tab[aria-pressed=true]{border-bottom-color:#3b6fd8;color:#244f9f;font-weight:700}.inspector-tab .finding-total,.inspector-tab .annotation-total{min-width:15px;padding:1px 4px;border-radius:999px;background:#eef0f3;color:#687384;font-size:7px;text-align:center}.inspector-pane{flex:1;min-height:0;overflow:auto;padding:10px}.inspector-pane[hidden]{display:none}.pane-heading{display:flex;align-items:center;justify-content:space-between;margin:2px 2px 10px}.pane-heading>.annotation-total{padding:2px 6px;border-radius:999px;background:#eef0f3;color:#687384;font-size:8px}.panel-empty{min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;padding:24px;color:#8a93a2;text-align:center;font-size:10px;line-height:1.4}.panel-empty strong{color:#465160;font-size:11px}.empty-icon{width:24px;height:24px;color:#a8b0bc}.inspect-table{grid-template-columns:76px 1fr;gap:8px 9px;padding:4px;font-size:9px}.inspect-table dt{color:#8a93a2}.inspect-table dd{overflow-wrap:anywhere;color:#35404f}.comment-form{gap:8px;margin-top:14px;padding-top:12px}.comment-form textarea{min-height:92px;border-color:#d9dde3;border-radius:8px;padding:9px;font-size:10px}.comment-form select{height:30px;border-color:#d9dde3;border-radius:7px;font-size:9px}.comment-form button{min-height:32px;border-radius:7px;background:#315fbd;font-size:9px}
.revision-notice{margin:0 0 9px;padding:9px;border-color:#f2c879;border-radius:8px;background:#fff8e9;color:#825418;font-size:9px}.revision-notice-actions button{min-height:26px;padding:3px 7px;border-radius:6px}.fix-queue{margin:0 0 10px;border-color:#dce3ef;border-radius:9px;background:#f7f9fc}.fix-queue>summary,.panel-section>summary{min-height:34px;display:flex;align-items:center;justify-content:space-between;padding:7px 9px;list-style:none;color:#344054;font-size:10px;font-weight:700}.fix-queue>summary::-webkit-details-marker,.panel-section>summary::-webkit-details-marker{display:none}.fix-queue>summary:after,.panel-section>summary:after{content:'›';margin-left:auto;color:#9aa2af;transform:rotate(90deg)}.fix-queue:not([open])>summary:after,.panel-section:not([open])>summary:after{transform:none}.fix-queue-count{min-width:18px;margin-left:6px;padding:2px 5px;border-radius:999px;background:#e5eaf2;color:#526071;font-size:8px;text-align:center}.fix-queue-body{padding:0 9px 9px}.review-phases{gap:0;margin:2px 0 9px}.review-phase{position:relative;padding:15px 1px 0;background:transparent;color:#8a93a2;font-size:7px}.review-phase:before{content:'';position:absolute;left:calc(50% - 4px);top:2px;width:8px;height:8px;border:2px solid #cdd3dc;border-radius:50%;background:#fff;z-index:1}.review-phase:after{content:'';position:absolute;left:50%;right:-50%;top:6px;height:1px;background:#dce0e6}.review-phase:last-child:after{display:none}.review-phase.active,.review-phase.complete{background:transparent}.review-phase.active{color:#2f5fb7;font-weight:700}.review-phase.active:before{border-color:#3b6fd8;background:#3b6fd8;box-shadow:0 0 0 3px #dce8ff}.review-phase.complete{color:#3a7654}.review-phase.complete:before{border-color:#4f9a70;background:#4f9a70}.review-phase.complete:after{background:#7db394}.fix-queue-stats{margin-bottom:8px}.fix-queue-stat{background:#fff;border:1px solid #e1e5ea;color:#697586;font-size:7px}.fix-queue-actions{gap:6px}.fix-queue-action{min-height:31px;display:flex;align-items:center;justify-content:center;gap:5px;border-color:#d5dbe4;border-radius:7px;color:#45566f;font-size:8px}.fix-queue-action .icon{width:13px;height:13px}.fix-queue-action.primary{border-color:#315fbd;background:#315fbd}.source-handoff{margin-top:7px;padding-top:7px;border-top-color:#e1e6ed}.source-handoff .fix-queue-action{width:100%}
.automated-review{margin:0;padding:10px 0 0;border-top:1px solid #e7e9ed}.review-section-heading{margin:0 2px 8px}.review-section-heading h2{font-size:11px}.finding-total{padding:2px 6px;background:#eef0f3;color:#687384}.audit-summary{font-size:9px}.audit-count{background:#f2f4f7;font-size:7px}.audit-depth{border-color:#e4e7eb;background:#fafbfc}.finding-filters{gap:4px;margin:8px 0;padding-bottom:2px}.finding-filter{min-height:25px;padding:3px 7px;border-color:#dfe3e8;border-radius:999px;font-size:7px}.finding-filter[aria-pressed=true]{border-color:#9eb9ee;background:#edf3ff;color:#2857ac}.finding-list{gap:8px}.finding-card{padding:9px;border-color:#e0e4e9;border-left-width:3px;border-radius:8px;box-shadow:0 1px 1px rgba(22,29,40,.02)}.finding-title{font-size:10px}.finding-severity{border-radius:999px;font-size:6px}.finding-meta{font-size:7px}.finding-observation,.finding-impact,.finding-recommendation{font-size:8px;line-height:1.45}.finding-proposal-note{padding:5px 6px;border-radius:6px;font-size:7px}.finding-action{min-height:25px;display:inline-flex;align-items:center;gap:4px;padding:3px 6px;border-color:#d8dde4;border-radius:6px;font-size:7px}.finding-action.primary{border-color:#315fbd;background:#315fbd}.panel-section{margin:10px 0;border-color:#e1e5ea;border-radius:8px}.runtime-diagnostics>.diagnostics-body{padding:0 9px 9px}.diagnostics-action{min-height:29px;display:flex;align-items:center;gap:5px;border-radius:7px}.diagnostics-action .icon{width:13px;height:13px}.diagnostics-action.primary{border-color:#315fbd;background:#315fbd}.review-footer{position:sticky;bottom:-10px;margin:12px -10px -10px;padding:8px 10px 10px;border-top:1px solid #e1e5ea;background:rgba(255,255,255,.96);backdrop-filter:blur(8px)}.review-decision{margin:0 0 7px;padding:0;background:transparent;color:#7c8796;font-size:8px}.review-actions{display:grid;grid-template-columns:1fr 1fr 32px;gap:6px;margin:0}.review-action{min-height:32px;display:flex;align-items:center;justify-content:center;gap:5px;border-color:#d6dce4;border-radius:7px;font-size:8px}.review-action .icon{width:13px;height:13px}.review-action.primary{border-color:#315fbd;background:#315fbd}.review-action.icon-only{padding:0}.annotation-list{gap:8px}.annotation-card{padding:9px;border-color:#e0e4e9;border-radius:8px}.annotation-text{font-size:9px}.annotation-total{font-variant-numeric:tabular-nums}
.panel-empty.compact{min-height:132px;margin-bottom:10px;border:1px dashed #dce1e7;border-radius:8px}.comment-form{gap:8px;margin:0 0 12px;padding:10px;border:1px solid #dfe4ea;border-radius:9px;background:#fafbfc}.comment-target{overflow:hidden;color:#6f7a89;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.comment-form-row{display:grid;grid-template-columns:1fr 76px;gap:6px}.comment-form-row button{margin:0}.finding-details{margin-top:6px;border-top:1px solid #eceef1;padding-top:5px}.finding-details>summary{cursor:pointer;color:#667386;font-size:8px;font-weight:650}.finding-details[open]>summary{margin-bottom:4px}.finding-action .icon{width:12px;height:12px}.rail-badge[hidden]{display:none!important}
.review-launcher{margin:0 0 10px;padding:11px;border:1px solid #d8e1f0;border-radius:10px;background:linear-gradient(145deg,#f8fbff,#f3f6fb)}.review-launcher-head{display:flex;align-items:flex-start;gap:8px}.review-launcher-icon{width:28px;height:28px;flex:0 0 28px;display:grid;place-items:center;border-radius:8px;background:#e6efff;color:#2f5fb7}.review-launcher-icon .icon{width:15px;height:15px}.review-launcher-title{margin:0;color:#202936;font-size:11px;line-height:1.25}.review-launcher-meta{margin:2px 0 0;color:#788494;font-size:8px}.review-launcher-status{min-height:16px;margin:8px 0;color:#536174;font-size:9px;line-height:1.4}.review-launcher[data-state=complete] .review-launcher-status{color:#315f55}.review-launcher-actions{display:grid;gap:6px}.review-launcher-action{min-height:33px;display:flex;align-items:center;justify-content:center;gap:6px;border:1px solid #d4dae3;border-radius:7px;background:#fff;color:#455366;font-size:9px;font-weight:650;cursor:pointer}.review-launcher-action.primary{border-color:#315fbd;background:#315fbd;color:#fff}.review-launcher-action:hover:not(:disabled){border-color:#9eb6df;background:#f7faff}.review-launcher-action.primary:hover:not(:disabled){border-color:#284f9e;background:#284f9e}.review-launcher-action:disabled{cursor:not-allowed;opacity:.52}.review-launcher-action .icon{width:14px;height:14px}.review-launcher-progress{height:3px;overflow:hidden;margin:-2px 0 8px;border-radius:999px;background:#dfe7f3}.review-launcher-progress:after{content:'';display:block;width:38%;height:100%;border-radius:inherit;background:#3b6fd8;animation:review-progress 1s ease-in-out infinite alternate}.review-launcher:not([data-state=running]) .review-launcher-progress{display:none}@keyframes review-progress{from{transform:translateX(-20%)}to{transform:translateX(210%)}}
.review-subtabs{position:sticky;top:-10px;z-index:8;display:grid;grid-template-columns:repeat(3,1fr);gap:3px;margin:-10px -10px 10px;padding:8px 10px;border-bottom:1px solid #e4e7ec;background:rgba(255,255,255,.96);backdrop-filter:blur(8px)}.review-subtab{min-width:0;height:29px;border:0;border-radius:7px;background:transparent;color:#667386;font-size:8px;font-weight:650;cursor:pointer}.review-subtab:hover{background:#f1f3f6;color:#2c3440}.review-subtab[aria-pressed=true]{background:#e9f0ff;color:#2857ac}.review-subtab-count{margin-left:3px;color:#8d97a5;font-size:7px;font-variant-numeric:tabular-nums}.review-workspace[hidden]{display:none}.review-scope-row{display:grid;grid-template-columns:1fr 104px;align-items:center;gap:8px;margin:8px 0 0}.review-scope-label{color:#6c7888;font-size:8px}.review-scope-select,.finding-select{height:28px;min-width:0;border:1px solid #d8dee7;border-radius:7px;background:#fff;color:#465264;padding:0 7px;font-size:8px}.coverage-panel,.review-history,.import-review-panel{margin:0 0 10px;padding:10px;border:1px solid #e0e4e9;border-radius:9px;background:#fff}.coverage-head,.history-head,.import-review-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.coverage-head h3,.history-head h3,.import-review-head h3{margin:0;color:#293443;font-size:10px}.coverage-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.coverage-metric{padding:7px;border-radius:7px;background:#f5f7fa}.coverage-metric b{display:block;color:#263243;font-size:13px;font-variant-numeric:tabular-nums}.coverage-metric span{color:#7b8796;font-size:7px}.coverage-gaps{margin:8px 0 0;padding:7px;border-radius:7px;background:#fff7e8;color:#8b5a13;font-size:8px;line-height:1.4}.coverage-gaps.pass{background:#edf8f1;color:#326648}.coverage-matrix{margin-top:8px;display:grid;gap:4px}.coverage-row{display:grid;grid-template-columns:minmax(70px,1fr) 42px 42px 42px;align-items:center;gap:3px;color:#657181;font-size:7px}.coverage-row.header{color:#929aa6}.coverage-cell{padding:3px;border-radius:4px;background:#eef1f5;text-align:center;font-variant-numeric:tabular-nums}.coverage-cell.pass{background:#e6f5eb;color:#2f6c48}.coverage-cell.gap{background:#fff0d6;color:#8b5a13}.review-history-list{display:grid;gap:5px}.review-history-item{display:grid;grid-template-columns:1fr auto;gap:5px;padding:6px;border-radius:7px;background:#f6f7f9;color:#4f5c6c;font-size:8px}.review-history-item small{grid-column:1/-1;color:#8a94a2}.history-clear{border:0;background:transparent;color:#7b8796;font-size:7px;cursor:pointer}.finding-toolbar{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:7px 0}.finding-bulk{display:flex;gap:5px;margin:6px 0}.finding-bulk button,.import-review-action{min-height:27px;border:1px solid #d8dee7;border-radius:6px;background:#fff;color:#4b596b;padding:4px 7px;font-size:7px;cursor:pointer}.finding-group-label{margin:7px 0 3px;color:#7c8796;font-size:7px;font-weight:700;text-transform:uppercase}.import-review-copy{margin:0 0 8px;color:#6d7989;font-size:8px;line-height:1.4}.import-review-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px}.import-review-status{margin-top:7px;color:#607083;font-size:8px}.review-context-footer{position:sticky;bottom:-10px;z-index:9;margin:12px -10px -10px;padding:8px 10px 10px;border-top:1px solid #dfe3e8;background:rgba(255,255,255,.96);backdrop-filter:blur(8px)}.review-context-status{margin:0 0 6px;color:#7a8594;font-size:8px}.review-context-actions{display:grid;grid-template-columns:1fr auto auto;gap:5px}.review-next-action,.review-secondary-action{min-height:33px;display:flex;align-items:center;justify-content:center;gap:5px;border:1px solid #d4dae3;border-radius:7px;background:#fff;color:#526073;padding:0 9px;font-size:8px;cursor:pointer}.review-next-action{border-color:#315fbd;background:#315fbd;color:#fff;font-weight:700}.review-next-action:disabled{opacity:.5;cursor:not-allowed}.review-secondary-action.icon-only{width:33px;padding:0}.screen-card{content-visibility:auto;contain-intrinsic-size:320px 620px}
.codex-handoff-panel{margin:0 0 10px;padding:9px;border:1px solid #cfdcf3;border-radius:9px;background:#f5f8ff}.codex-handoff-panel[hidden]{display:none}.codex-handoff-head{display:flex;align-items:center;gap:7px;color:#2857ac}.codex-handoff-head .icon{width:14px;height:14px}.codex-handoff-status{font-size:9px;font-weight:700}.codex-handoff-meta{margin:5px 0 8px;color:#657386;font-size:8px;line-height:1.4}.codex-handoff-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px}.codex-handoff-action{min-height:28px;border:1px solid #ccd7e7;border-radius:6px;background:#fff;color:#46566c;font-size:7px;cursor:pointer}.review-launcher-action.icon-only{min-height:29px}.review-launcher-actions.with-handoff{grid-template-columns:1fr 34px}.review-launcher-actions.with-handoff .run-review{grid-column:1/-1}
.compare-version-select{height:27px;max-width:150px;border:0;border-radius:6px;background:#f5f6f8;color:#465160;padding:0 7px;font-size:8px}.compare-version-arrow{color:#929aa6;font-size:9px}.screen-card{content-visibility:visible;contain-intrinsic-size:auto}
.review-session-name{width:100%;height:28px;margin:0 0 7px;border:1px solid #dde2e8;border-radius:7px;background:#fafbfc;color:#465160;padding:0 7px;font-size:8px}
@container(max-width:760px){.screen-context{display:none}.menu-strip{display:none}.version-select{max-width:140px}.mode-status{display:none}.canvas-tools .button-label{display:none}.canvas-tools .mode-button,.canvas-tools .interaction-button{width:30px;padding:0}.canvas-tools{gap:3px}}
@media(max-width:980px){.review-app{grid-template-columns:var(--rail) var(--left-panel) var(--left-grip) minmax(0,1fr)}.right-resizer{display:none}.inspector{display:flex;position:fixed;right:0;top:0;z-index:60;width:min(360px,calc(100vw - var(--rail)));box-shadow:-12px 0 36px rgba(24,31,43,.18)}.review-app.inspector-hidden>.inspector{display:none}.compare-grid{grid-template-columns:1fr}.header-panel-button{display:grid}}
@media(max-width:720px){.review-app{grid-template-columns:var(--rail) minmax(0,1fr)}.sidebar{display:flex;position:fixed;left:var(--rail);top:0;z-index:60;width:min(280px,calc(100vw - var(--rail)));box-shadow:12px 0 36px rgba(24,31,43,.18)}.left-resizer{display:none}.review-app.sidebar-hidden>.sidebar{display:none}.app-mark>span:not(.revision-badge){display:none}.stage{padding:34px 18px 68px}.floating-zoom{bottom:58px}.canvas-tools{bottom:12px}}
@media(max-width:480px){.version-select{display:none}.screen-context{display:none}.canvas-tools{max-width:calc(100% - 64px);overflow-x:auto}.floating-zoom{right:8px}.menu-bar{padding-inline:7px}.stage{padding-inline:12px}}
"""

JS = r"""
const previewContext=JSON.parse(document.getElementById('ui-preview-context')?.textContent||'{}');const ir=JSON.parse(document.getElementById('ui-ir-data').textContent);const nodes=ir.nodes||{},screens=ir.screens||[],review=ir.review||{},expertAudit=review.audit||{};const baseFindings=Array.isArray(expertAudit.findings)?expertAudit.findings:[];const diagnosticsConfig=review.diagnostics||{profiles:[{id:'current',label:'Текущее окно',viewport:'current',zoomLevels:[.2,1,2]}],scenarios:[{id:'zoom-reset',label:'Сброс масштаба',kind:'zoom-reset'},{id:'overview-geometry',label:'Геометрия обзора',kind:'overview-geometry'},{id:'menu-exclusivity',label:'Взаимодействие меню',kind:'menu-exclusivity'},{id:'layout-integrity',label:'Целостность макета',kind:'layout-integrity'},{id:'accessibility-basics',label:'Базовая доступность',kind:'accessibility-basics'}]};
const mandatoryDiagnosticScenarios=[{id:'state-matrix',label:'Состояния компонентов',kind:'state-matrix'},{id:'navigation-flow',label:'Пользовательские переходы',kind:'navigation-flow'},{id:'contrast-focus',label:'Контраст и клавиатура',kind:'contrast-focus'}];diagnosticsConfig.profiles=diagnosticsConfig.profiles||[];diagnosticsConfig.scenarios=diagnosticsConfig.scenarios||[];for(const scenario of mandatoryDiagnosticScenarios)if(!diagnosticsConfig.scenarios.some(item=>item.kind===scenario.kind))diagnosticsConfig.scenarios.push(scenario);
const versions=Array.isArray(review.versions)&&review.versions.length?review.versions:[{id:'baseline',label:'Before',kind:'baseline',status:'approved',nodeOverrides:{}}];
const versionById=Object.fromEntries(versions.map(v=>[v.id,v]));const baselineVersion=review.baselineVersion&&versionById[review.baselineVersion]?review.baselineVersion:versions[0].id;const initialVersion=review.activeVersion&&versionById[review.activeVersion]?review.activeVersion:versions.at(-1).id;
function revisionHash(value){let hash=2166136261;for(let index=0;index<value.length;index++){hash^=value.charCodeAt(index);hash=Math.imul(hash,16777619)}return (hash>>>0).toString(36)}
const workbenchSchema=4;const reviewRevision=`${review.revision||'auto'}-${revisionHash(JSON.stringify({workbenchSchema,screens,nodes,versions,audit:expertAudit}))}`;const storageKey=`ui-code-preview:${ir.project?.name||'project'}:${review.sessionId||'default'}`;let saved={};try{saved=JSON.parse(localStorage.getItem(storageKey)||'{}')}catch(_){saved={}}const staleReviewSnapshot=saved.revision&&saved.revision!==reviewRevision?saved:null;if(staleReviewSnapshot)saved={};
const annotationMap=new Map((review.annotations||[]).map(item=>[item.id,item]));for(const item of saved.annotations||[])annotationMap.set(item.id,item);
const state={interaction:'interact',view:'overview',screen:null,selected:null,selectedNodeId:saved.selectedNodeId||null,selectedScreenId:saved.selectedScreenId||null,focusedFindingId:saved.focusedFindingId||null,diagnosticTargetIds:Array.isArray(saved.diagnosticTargetIds)?saved.diagnosticTargetIds:[],nodeStates:{},screenScrolls:saved.screenScrolls||{},stageScroll:saved.stageScroll||{left:0,top:0},activeVersion:saved.activeVersion&&versionById[saved.activeVersion]?saved.activeVersion:initialVersion,compareMode:saved.compareMode||'split',overlayPosition:saved.overlayPosition||50,zoomMode:saved.zoomMode||'fit',zoom:Number(saved.zoom)||1,computedZoom:1,sidebarOpen:saved.sidebarOpen!==false,inspectorOpen:saved.inspectorOpen!==false,inspectorTab:['inspect','review','comments'].includes(saved.inspectorTab)?saved.inspectorTab:'review',reviewSection:['summary','problems','changes'].includes(saved.reviewSection)?saved.reviewSection:'summary',reviewScope:['all','current'].includes(saved.reviewScope)?saved.reviewScope:'all',leftWidth:Number(saved.leftWidth)||244,rightWidth:Number(saved.rightWidth)||324,findingFilter:saved.findingFilter||'all',findingSource:saved.findingSource||'all',findingScreen:saved.findingScreen||'all',findingFocus:Array.isArray(saved.findingFocus)?saved.findingFocus:[],findingDecisions:saved.findingDecisions||expertAudit.findingDecisions||{},runtimeFindings:Array.isArray(saved.runtimeFindings)?saved.runtimeFindings:[],annotations:[...annotationMap.values()],versionDecision:saved.versionDecision||'pending',sourcePreparedVersionId:saved.sourcePreparedVersionId||null,diagnostics:saved.diagnostics||null,diagnosticsRunning:false,diagnosticsProgress:'',reviewRuns:Array.isArray(saved.reviewRuns)?saved.reviewRuns:[],importedReview:saved.importedReview||null,codexHandoff:saved.codexHandoff||null,staleReview:staleReviewSnapshot};
state.compareBaseVersion=saved.compareBaseVersion&&versionById[saved.compareBaseVersion]?saved.compareBaseVersion:baselineVersion;state.compareTargetVersion=saved.compareTargetVersion&&versionById[saved.compareTargetVersion]?saved.compareTargetVersion:state.activeVersion;state.reviewSessionName=saved.reviewSessionName||review.sessionId||ir.project?.name||'Ревью';
const findings=new Proxy([],{get(_,property){const items=[...baseFindings,...state.runtimeFindings];const value=items[property];return typeof value==='function'?value.bind(items):value}});
const $=s=>document.querySelector(s);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const iconMarkup=name=>`<svg class="icon" aria-hidden="true"><use href="#icon-${esc(name)}"></use></svg>`;
function persist(){localStorage.setItem(storageKey,JSON.stringify({revision:reviewRevision,activeVersion:state.activeVersion,compareMode:state.compareMode,compareBaseVersion:state.compareBaseVersion,compareTargetVersion:state.compareTargetVersion,overlayPosition:state.overlayPosition,zoomMode:state.zoomMode,zoom:state.zoom,sidebarOpen:state.sidebarOpen,inspectorOpen:state.inspectorOpen,inspectorTab:state.inspectorTab,reviewSection:state.reviewSection,reviewScope:state.reviewScope,reviewSessionName:state.reviewSessionName,leftWidth:state.leftWidth,rightWidth:state.rightWidth,findingFilter:state.findingFilter,findingSource:state.findingSource,findingScreen:state.findingScreen,findingFocus:state.findingFocus,findingDecisions:state.findingDecisions,runtimeFindings:state.runtimeFindings,annotations:state.annotations,versionDecision:state.versionDecision,sourcePreparedVersionId:state.sourcePreparedVersionId,diagnostics:state.diagnostics,reviewRuns:state.reviewRuns,importedReview:state.importedReview,codexHandoff:state.codexHandoff,selectedNodeId:state.selectedNodeId,selectedScreenId:state.selectedScreenId,focusedFindingId:state.focusedFindingId,diagnosticTargetIds:state.diagnosticTargetIds,screenScrolls:state.screenScrolls,stageScroll:state.stageScroll}))}
function token(path){if(typeof path!=='string'||!path.startsWith('$'))return path;let value=ir.tokens;for(const part of path.slice(1).split('.'))value=value?.[part];return value??path}
function cssValue(value,unit='px'){value=token(value);if(typeof value==='number')return `${value}${unit}`;if(value==='fill')return '100%';if(value==='hug')return 'fit-content';return value??''}
function styleFor(node){const l=node.layout||{},s=node.style||{},out={};const raw=(key,value)=>{if(value!=null)out[key]=token(value)};const length=(key,value)=>{if(value!=null)out[key]=cssValue(value)};const direction=l.direction||((['container','list','card'].includes(node.type))?'column':null);if(direction){out.display='flex';if(['row','column'].includes(direction))out.flexDirection=direction;if(direction==='grid'){out.display='grid';const columns=l.columns??2;out.gridTemplateColumns=typeof columns==='number'?`repeat(${columns},minmax(0,1fr))`:token(columns);if(l.rows!=null)out.gridTemplateRows=token(l.rows)}if(direction==='overlay'){out.position='relative';out.display='block'}}length('gap',l.gap);length('rowGap',l.rowGap);length('columnGap',l.columnGap);length('padding',l.padding);length('margin',l.margin);if(l.paddingHorizontal!=null){length('paddingLeft',l.paddingHorizontal);length('paddingRight',l.paddingHorizontal)}if(l.paddingVertical!=null){length('paddingTop',l.paddingVertical);length('paddingBottom',l.paddingVertical)}if(l.marginHorizontal!=null){length('marginLeft',l.marginHorizontal);length('marginRight',l.marginHorizontal)}if(l.marginVertical!=null){length('marginTop',l.marginVertical);length('marginBottom',l.marginVertical)}for(const side of ['Top','Right','Bottom','Left']){length(`padding${side}`,l[`padding${side}`]);length(`margin${side}`,l[`margin${side}`])}for(const key of ['width','height','minWidth','maxWidth','minHeight','maxHeight','top','right','bottom','left','flexBasis'])length(key,l[key]);for(const key of ['position','display','overflow','overflowX','overflowY','alignSelf','order','zIndex','aspectRatio'])raw(key,l[key]);raw('flexGrow',l.grow);raw('flexShrink',l.shrink);raw('flexWrap',l.wrap===true?'wrap':l.wrap);if(l.align)out.alignItems=({start:'flex-start',end:'flex-end',center:'center',stretch:'stretch',baseline:'baseline'}[l.align]||l.align);if(l.justify)out.justifyContent=({start:'flex-start',end:'flex-end',between:'space-between',around:'space-around',evenly:'space-evenly',center:'center'}[l.justify]||l.justify);const lengths={borderWidth:'borderWidth',borderTopWidth:'borderTopWidth',borderRightWidth:'borderRightWidth',borderBottomWidth:'borderBottomWidth',borderLeftWidth:'borderLeftWidth',radius:'borderRadius',radiusTopLeft:'borderTopLeftRadius',radiusTopRight:'borderTopRightRadius',radiusBottomRight:'borderBottomRightRadius',radiusBottomLeft:'borderBottomLeftRadius',fontSize:'fontSize',lineHeight:'lineHeight',letterSpacing:'letterSpacing',outlineWidth:'outlineWidth'};const raws={background:'background',backgroundColor:'backgroundColor',backgroundImage:'backgroundImage',color:'color',border:'border',borderColor:'borderColor',borderTopColor:'borderTopColor',borderRightColor:'borderRightColor',borderBottomColor:'borderBottomColor',borderLeftColor:'borderLeftColor',borderStyle:'borderStyle',outlineColor:'outlineColor',outlineStyle:'outlineStyle',opacity:'opacity',fontFamily:'fontFamily',fontWeight:'fontWeight',fontStyle:'fontStyle',textAlign:'textAlign',textDecoration:'textDecoration',textTransform:'textTransform',whiteSpace:'whiteSpace',overflowWrap:'overflowWrap',textOverflow:'textOverflow',objectFit:'objectFit',objectPosition:'objectPosition',boxShadow:'boxShadow',filter:'filter',backdropFilter:'backdropFilter',transform:'transform',transformOrigin:'transformOrigin',cursor:'cursor',visibility:'visibility'};for(const [key,cssKey] of Object.entries(lengths))length(cssKey,s[key]);for(const [key,cssKey] of Object.entries(raws))raw(cssKey,s[key]);if(s.shadow!=null)raw('boxShadow',s.shadow);if(s.placeholderColor!=null)raw('--placeholder-color',s.placeholderColor);const typo=token(s.typography);if(typo&&typeof typo==='object'){for(const key of ['fontSize','lineHeight','letterSpacing'])length(key,typo[key]);for(const key of ['fontFamily','fontWeight','fontStyle','textTransform'])raw(key,typo[key])}if(s.css&&typeof s.css==='object')for(const [key,value] of Object.entries(s.css))if(/^(--[a-z0-9-]+|[a-zA-Z][a-zA-Z0-9-]*)$/.test(key))out[key]=token(value);return Object.entries(out).filter(([,v])=>v!==''&&v!=null).map(([k,v])=>`${k.replace(/[A-Z]/g,m=>'-'+m.toLowerCase())}:${v}`).join(';')}
function versionChain(versionId){const chain=[],seen=new Set();let current=versionById[versionId];while(current&&!seen.has(current.id)){seen.add(current.id);chain.unshift(current);current=current.parent?versionById[current.parent]:null}return chain}
function versionOverride(nodeId,versionId){let result={};for(const version of versionChain(versionId)){const change=version.nodeOverrides?.[nodeId];if(change)result={...result,...change,layout:{...(result.layout||{}),...(change.layout||{})},style:{...(result.style||{}),...(change.style||{})}}}return result}
function effectiveNode(id,versionId=state.activeVersion){const base=nodes[id];if(!base)return null;const change=versionOverride(id,versionId);let result={...base,...change,layout:{...(base.layout||{}),...(change.layout||{})},style:{...(base.style||{}),...(change.style||{})}};const variant=result.states?.[state.nodeStates[id]];if(variant)result={...result,...variant,layout:{...(result.layout||{}),...(variant.layout||{})},style:{...(result.style||{}),...(variant.style||{})}};return result}
function changedInVersion(id,versionId){return versionChain(versionId).some(version=>version.kind!=='baseline'&&version.nodeOverrides?.[id])}
function provenance(id,node,versionId){const src=node.source||{},action=node.action||{},semantics=node.semantics||{},standard=node.standardRef||Object.entries(node.standardRefs||{}).map(([platform,ref])=>`${platform}:${ref}`).join(', '),accessible=semantics.label&&['button','input'].includes(node.type)?`aria-label="${esc(semantics.label)}"`:'';return `${accessible} data-node-id="${esc(id)}" data-version-id="${esc(versionId)}" data-changed="${changedInVersion(id,versionId)}" data-source-file="${esc(src.file||'')}" data-source-line="${esc(src.line||'')}" data-source-symbol="${esc(src.symbol||'')}" data-component="${esc(node.component||'')}" data-component-ref="${esc(node.componentRef||'')}" data-confidence="${esc(node.confidence||'approximate')}" data-standard-ref="${esc(standard)}" data-decision-id="${esc(node.decisionId||'')}" data-semantic-role="${esc(semantics.role||'')}" data-semantic-label="${esc(semantics.label||'')}" data-target-size="${esc(typeof semantics.targetSize==='object'?`${semantics.targetSize.width||'?'}×${semantics.targetSize.height||'?'}`:(semantics.targetSize||''))}" data-action="${esc(action.type||'')}" data-target="${esc(action.target||'')}" data-action-state="${esc(action.state||'')}" data-action-off-state="${esc(action.offState||'')}"`}
function renderNode(id,stack=[],versionId=state.activeVersion){const n=effectiveNode(id,versionId);if(!n)return `<div class="ui-custom">Missing node ${esc(id)}</div>`;if(stack.includes(id))return `<div class="ui-custom">Circular node ${esc(id)}</div>`;const style=styleFor(n),p=provenance(id,n,versionId),children=(n.children||[]).map(child=>renderNode(child,[...stack,id],versionId)).join('');switch(n.type){case'text':return `<div class="ui-node ui-text" ${p} style="${esc(style)}">${esc(n.text||'')}</div>`;case'button':return `<button type="button" class="ui-node ui-button" ${p} ${n.disabled?'disabled':''} style="${esc(style)}">${children||esc(n.text||n.component||'')}</button>`;case'input':return `<input class="ui-node ui-input" ${p} type="${esc(n.inputType||'text')}" value="${esc(n.value||'')}" placeholder="${esc(n.placeholder||'')}" ${n.disabled?'disabled':''} style="${esc(style)}">`;case'image':return n.resolvedAsset?`<img class="ui-node ui-image" ${p} src="${n.resolvedAsset}" alt="${esc(n.alt||'')}" style="${esc(style)}">`:`<div class="ui-node ui-custom" ${p}>Asset unavailable: ${esc(n.asset||'')}</div>`;case'icon':return n.resolvedAsset?`<img class="ui-node ui-icon" ${p} src="${n.resolvedAsset}" alt="${esc(n.alt||'')}" style="${esc(style)}">`:`<span class="ui-node ui-icon" ${p} style="${esc(style)}">${esc(n.iconName||'◇')}</span>`;case'spacer':return `<div class="ui-node ui-spacer" ${p} style="${esc(style)}"></div>`;case'custom':return `<div class="ui-node ui-custom" ${p} style="${esc(style)}">${esc(n.text||n.component||'Unsupported UI')}</div>`;case'card':return `<div class="ui-node ui-card" ${p} style="${esc(style)}">${children}</div>`;case'list':return `<div class="ui-node ui-list" ${p} style="${esc(style)}">${children}</div>`;default:return `<div class="ui-node ui-container" ${p} style="${esc(style)}">${children}</div>`}}
const vp=ir.viewport||{width:390,height:844,device:'phone'};function currentFromLocation(){const id=new URL(location.href).searchParams.get('screen');return screens.some(s=>s.id===id)?id:screens[0]?.id}function viewFromLocation(){const view=new URL(location.href).searchParams.get('view');return ['overview','prototype','single','compare'].includes(view)?view:'overview'}function viewportFor(screen){return {...vp,...(screen?.viewport||{})}}function writeLocation(push=true){const u=new URL(location.href);u.searchParams.set('view',state.view);if(state.screen)u.searchParams.set('screen',state.screen);const payload={view:state.view,screen:state.screen};push?history.pushState(payload,'',u):history.replaceState(payload,'',u)}
function deviceMarkup(screen,extraClass='',versionId=state.activeVersion){const screenVp=viewportFor(screen);return `<div class="device ${esc(extraClass)}" data-width="${esc(screenVp.width)}" data-height="${esc(screenVp.height)}" data-device="${esc(screenVp.device||'phone')}" data-frame="${screenVp.frame===true}" data-background="${esc(screenVp.background||'')}"><div class="device-content">${renderNode(screen.root,[],versionId)}</div></div>`}
function configureDevice(device){device.style.width=`${device.dataset.width}px`;device.style.height=`${device.dataset.height}px`;device.classList.add(device.dataset.device==='desktop'?'desktop':'phone');if(device.dataset.frame==='true')device.classList.add('framed');device.querySelector('.device-content').style.background=token(device.dataset.background)||'transparent'}
function overviewMarkup(){const stage=$('.stage'),canvasWidth=Math.max(320,(stage?.clientWidth||1200)-56);return `<div class="overview-canvas-shell"><div class="overview-canvas" style="width:${canvasWidth}px"><div class="overview-grid">${screens.map(screen=>{const screenVp=viewportFor(screen),scale=screenVp.device==='desktop'?0.2:0.52;return `<article class="screen-card" data-screen-card="${esc(screen.id)}" style="width:${screenVp.width*scale}px"><header class="screen-card-header"><span class="screen-card-title">${esc(screen.name)}</span><button type="button" class="screen-card-open" data-open-screen="${esc(screen.id)}">Открыть</button></header><div class="overview-viewport" style="width:${screenVp.width*scale}px;height:${screenVp.height*scale}px">${deviceMarkup(screen,'overview-device',state.activeVersion).replace('class="device overview-device"',`class="device overview-device" style="transform:scale(${scale})"`)}</div></article>`}).join('')}</div></div></div>`}
function compareMarkup(screen){const screenVp=viewportFor(screen),beforeId=versionById[state.compareBaseVersion]?state.compareBaseVersion:baselineVersion,afterId=versionById[state.compareTargetVersion]?state.compareTargetVersion:state.activeVersion,before=versionById[beforeId]||versions[0],after=versionById[afterId]||versions.at(-1);if(state.compareMode==='overlay')return `<div class="compare-overlay-wrap"><div class="compare-label">${esc(before.label||before.id)} ↔ ${esc(after.label||after.id)}</div><div class="compare-overlay" style="width:${screenVp.width}px;height:${screenVp.height}px;--overlay-width:${state.overlayPosition}%"><div class="before-layer">${deviceMarkup(screen,'',beforeId)}</div><div class="after-layer">${deviceMarkup(screen,'',afterId)}</div></div><input class="compare-overlay-slider" type="range" min="0" max="100" value="${state.overlayPosition}" aria-label="Before and after overlay"></div>`;return `<div class="compare-grid"><article class="compare-panel"><div class="compare-label">${esc(before.label||before.id)}</div>${deviceMarkup(screen,'',beforeId)}</article><article class="compare-panel"><div class="compare-label">${esc(after.label||after.id)}</div>${deviceMarkup(screen,'',afterId)}</article></div>`}
const treePaths={};
function inferredScreenTree(){const groups=new Map();for(const screen of screens){const routePart=String(screen.route||'').split(/[\/#]/).filter(Boolean)[0],key=screen.group||routePart||String(screen.id).split('-')[0]||'screens';if(!groups.has(key))groups.set(key,{id:`group-${key}`,label:key.charAt(0).toUpperCase()+key.slice(1),children:[]});groups.get(key).children.push({screenId:screen.id})}return [...groups.values()]}
function treeCount(items){return (items||[]).reduce((sum,item)=>sum+(item.screenId||item.screen?1:treeCount(item.children)),0)}
function treeMarkup(items,path=[],depth=0){return (items||[]).map(item=>{const screenId=item.screenId||item.screen;if(screenId){const screen=screens.find(value=>value.id===screenId);if(!screen)return '';const nextPath=[...path,item.label||screen.name];treePaths[screenId]=nextPath;return `<button type="button" class="screen-link" data-screen="${esc(screenId)}" aria-current="false" style="padding-left:${7+depth*6}px"><span>${esc(item.label||screen.name)}</span></button>`}const label=item.label||item.name||item.id||'Group',nextPath=[...path,label],children=item.children||[];return `<details class="screen-tree-group" data-tree-id="${esc(item.id||label)}" open><summary>${esc(label)}<span class="tree-count">${treeCount(children)}</span></summary><div class="screen-tree-children">${treeMarkup(children,nextPath,depth+1)}</div></details>`}).join('')}
function renderScreenTree(){for(const key of Object.keys(treePaths))delete treePaths[key];$('.screen-list').innerHTML=treeMarkup(Array.isArray(ir.screenTree)&&ir.screenTree.length?ir.screenTree:inferredScreenTree());document.querySelectorAll('.screen-link').forEach(button=>{button.addEventListener('click',()=>setScreen(button.dataset.screen,'single'));button.addEventListener('mouseenter',()=>previewNavigationTarget(button.dataset.screen,true));button.addEventListener('mouseleave',()=>previewNavigationTarget(button.dataset.screen,false));button.addEventListener('focus',()=>previewNavigationTarget(button.dataset.screen,true));button.addEventListener('blur',()=>previewNavigationTarget(button.dataset.screen,false))})}
function filterScreenTree(query){const value=String(query||'').trim().toLocaleLowerCase();document.querySelectorAll('.screen-link').forEach(button=>{button.hidden=Boolean(value)&&!button.textContent.toLocaleLowerCase().includes(value)});const groups=[...document.querySelectorAll('.screen-tree-group')].reverse();for(const group of groups){const visible=Boolean(group.querySelector('.screen-link:not([hidden]),.screen-tree-group:not([hidden])'));group.hidden=Boolean(value)&&!visible;if(value&&visible)group.open=true}}
function updateTreeSelection(screenId){document.querySelectorAll('.screen-link').forEach(button=>button.setAttribute('aria-current',String(button.dataset.screen===screenId)));const active=document.querySelector(`.screen-link[data-screen="${CSS.escape(screenId||'')}"]`);let parent=active?.parentElement;while(parent){if(parent.matches?.('details'))parent.open=true;parent=parent.parentElement}}
function renderInspectorTabs(){document.querySelectorAll('[data-inspector-tab]').forEach(button=>button.setAttribute('aria-pressed',String(state.inspectorOpen&&button.dataset.inspectorTab===state.inspectorTab)));document.querySelectorAll('[data-inspector-pane]').forEach(pane=>pane.hidden=pane.dataset.inspectorPane!==state.inspectorTab)}
function setInspectorTab(tab,open=true){if(!['inspect','review','comments'].includes(tab))return;state.inspectorTab=tab;if(open){state.inspectorOpen=true;if(innerWidth<=980)state.sidebarOpen=false}persist();applyPanelState();renderInspectorTabs()}
function reviewScopeScreens(){if(state.reviewScope==='current'){const current=screens.find(item=>item.id===state.screen)||screens[0];return current?[current]:[]}return screens}
function nodeIdsForScreen(screen){const result=[],seen=new Set(),walk=id=>{if(!id||seen.has(id)||!nodes[id])return;seen.add(id);result.push(id);for(const child of nodes[id].children||[])walk(child)};walk(screen?.root);return result}
function stateVariantCases(targetScreens=reviewScopeScreens()){const result=[];for(const screen of targetScreens)for(const nodeId of nodeIdsForScreen(screen)){const variants=nodes[nodeId]?.states;if(!variants||typeof variants!=='object')continue;for(const stateName of Object.keys(variants))result.push({screenId:screen.id,nodeId,stateName})}return result}
function renderReviewSections(){document.querySelectorAll('[data-review-section]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.reviewSection===state.reviewSection)));document.querySelectorAll('[data-review-workspace]').forEach(section=>section.hidden=section.dataset.reviewWorkspace!==state.reviewSection);renderReviewNextAction()}
function setReviewSection(section){if(!['summary','problems','changes'].includes(section))return;state.reviewSection=section;persist();renderReviewSections();document.querySelector('[data-inspector-pane="review"]')?.scrollTo({top:0,behavior:'smooth'})}
function diagnosticProfileLabel(profile){return profile.viewport==='current'?profile.label:`${profile.viewport?.width||'?'}×${profile.viewport?.height||'?'}`}
function renderCoverage(){const body=$('.coverage-body'),status=$('.coverage-status');if(!body)return;const targetScreens=reviewScopeScreens(),profiles=diagnosticProfiles(),variants=stateVariantCases(targetScreens),checks=state.diagnostics?.checks||[],stateChecks=checks.filter(item=>item.scenarioId==='state-matrix'),flowChecks=checks.filter(item=>item.scenarioId==='navigation-flow'),testedStates=new Set(stateChecks.filter(item=>item.metrics?.stateNodeId).map(item=>`${item.screenId}:${item.metrics.stateNodeId}:${item.metrics.stateName}:${item.metrics.profileId}`)),expectedStates=variants.length*profiles.length,missingStates=Math.max(0,expectedStates-testedStates.size),actionable=checks.filter(item=>item.result!=='pass').length;status.textContent=state.diagnosticsRunning?'проверяется':state.diagnostics?'готово':'не запускалось';const screenRows=targetScreens.map(screen=>{const screenChecks=checks.filter(item=>item.screenId===screen.id),screenVariants=variants.filter(item=>item.screenId===screen.id).length*profiles.length,screenTested=new Set(stateChecks.filter(item=>item.screenId===screen.id&&item.metrics?.stateNodeId).map(item=>`${item.metrics.stateNodeId}:${item.metrics.stateName}:${item.metrics.profileId}`)).size;return `<div class="coverage-row"><span>${esc(screen.name)}</span><span class="coverage-cell ${screenChecks.length?'pass':'gap'}">${screenChecks.length}</span><span class="coverage-cell ${screenVariants===screenTested?'pass':'gap'}">${screenTested}/${screenVariants}</span><span class="coverage-cell ${screenChecks.some(item=>item.result!=='pass')?'gap':'pass'}">${screenChecks.filter(item=>item.result!=='pass').length}</span></div>`}).join('');const gapText=!state.diagnostics?'Покрытие станет измеримым после запуска.':missingStates?`Не проверено вариантов состояния: ${missingStates}. Полное покрытие не заявляется.`:`Проверены все объявленные варианты состояний в выбранной области. Переходов проверено: ${flowChecks.length}.`;body.innerHTML=`<div class="coverage-grid"><div class="coverage-metric"><b>${targetScreens.length}</b><span>экранов в области</span></div><div class="coverage-metric"><b>${profiles.length}</b><span>реальных viewport-профиля</span></div><div class="coverage-metric"><b>${checks.length}</b><span>выполнено проверок</span></div><div class="coverage-metric"><b>${actionable}</b><span>непрошедших результатов</span></div></div><div class="coverage-gaps ${state.diagnostics&&!missingStates?'pass':''}">${gapText}</div><div class="coverage-matrix"><div class="coverage-row header"><span>Экран</span><span>Тесты</span><span>Сост.</span><span>Пробл.</span></div>${screenRows}</div>`}
function renderReviewHistory(){const list=$('.review-history-list'),name=$('.review-session-name');if(name)name.value=state.reviewSessionName;if(!list)return;const stored=state.reviewRuns.slice(-6).reverse(),runs=stored.length?stored:(state.diagnostics?[{sessionName:state.reviewSessionName,scopeLabel:state.diagnostics.scope==='current'?'Текущий экран':'Все экраны',issues:groupDiagnosticChecks((state.diagnostics.checks||[]).filter(item=>item.result!=='pass')).length,checks:state.diagnostics.checks?.length||0,stateCases:(state.diagnostics.checks||[]).filter(item=>item.scenarioId==='state-matrix').length,createdAt:state.diagnostics.completedAt}]:[]);list.innerHTML=runs.length?runs.map((run,index)=>{const previous=runs[index+1],delta=previous?run.issues-previous.issues:null;return `<div class="review-history-item"><span>${esc(run.sessionName||state.reviewSessionName||'Ревью')} · ${esc(run.scopeLabel||run.scope||'Все экраны')}</span><b>${run.issues} проблем${delta==null?'':` · ${delta>0?'+':''}${delta}`}</b><small>${new Date(run.createdAt).toLocaleString()} · ${run.checks} проверок · ${run.stateCases||0} состояний</small></div>`}).join(''):'<div class="panel-empty compact"><strong>Запусков пока нет</strong><span>История появится после первой проверки.</span></div>'}
function applyPanelState(){const app=$('.review-app');app.classList.toggle('sidebar-hidden',!state.sidebarOpen);app.classList.toggle('inspector-hidden',!state.inspectorOpen);app.style.setProperty('--left-panel',state.sidebarOpen?`${state.leftWidth}px`:'0px');app.style.setProperty('--left-grip',state.sidebarOpen?'4px':'0px');app.style.setProperty('--right-panel',state.inspectorOpen?`${state.rightWidth}px`:'0px');app.style.setProperty('--right-grip',state.inspectorOpen?'4px':'0px');document.querySelectorAll('.sidebar-toggle').forEach(button=>{button.setAttribute('aria-pressed',String(state.sidebarOpen));button.title=state.sidebarOpen?'Скрыть панель экранов':'Показать панель экранов'});document.querySelectorAll('.inspector-toggle').forEach(button=>{button.setAttribute('aria-pressed',String(state.inspectorOpen));button.title=state.inspectorOpen?'Скрыть правую панель':'Показать правую панель'});renderInspectorTabs()}
function bindResizer(handle){const side=handle.dataset.resize;const minimum=side==='left'?190:280,maximum=side==='left'?420:560;const update=value=>{if(side==='left')state.leftWidth=Math.max(minimum,Math.min(maximum,value));else state.rightWidth=Math.max(minimum,Math.min(maximum,value));applyPanelState()};handle.addEventListener('pointerdown',event=>{event.preventDefault();handle.setPointerCapture(event.pointerId);const startX=event.clientX,start=side==='left'?state.leftWidth:state.rightWidth;$('.review-app').classList.add('resizing');const move=moveEvent=>update(start+(side==='left'?moveEvent.clientX-startX:startX-moveEvent.clientX));const stop=()=>{handle.removeEventListener('pointermove',move);$('.review-app').classList.remove('resizing');persist();renderView()};handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',stop,{once:true});handle.addEventListener('pointercancel',stop,{once:true})});handle.addEventListener('dblclick',()=>{update(side==='left'?244:324);persist();renderView()});handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const direction=event.key==='ArrowRight'?1:-1;update((side==='left'?state.leftWidth:state.rightWidth)+(side==='left'?direction:-direction)*10);persist();renderView()})}
function clampZoom(value){return Math.max(.2,Math.min(2,Math.round(value*20)/20))}
function applyZoom(screen){const stage=$('.stage'),label=$('.zoom-label');if(!stage||!screen)return;const screenVp=viewportFor(screen),overviewCanvas=stage.querySelector('.overview-canvas');let zoom=state.zoom;if(state.zoomMode==='fit'){if(state.view==='overview'&&overviewCanvas){zoom=clampZoom(Math.min(1,(stage.clientWidth-56)/overviewCanvas.scrollWidth,(stage.clientHeight-56)/overviewCanvas.scrollHeight))}else if(state.view!=='overview'){const horizontalScreens=state.view==='compare'&&state.compareMode==='split'?2:1;zoom=clampZoom(Math.min(1,(stage.clientWidth-72)/(screenVp.width*horizontalScreens+Math.max(0,horizontalScreens-1)*28),(stage.clientHeight-72)/screenVp.height))}}state.computedZoom=zoom;if(state.view==='overview'&&overviewCanvas){const shell=overviewCanvas.closest('.overview-canvas-shell');overviewCanvas.style.transform=`scale(${zoom})`;if(shell){shell.style.width=`${Math.ceil(overviewCanvas.scrollWidth*zoom)}px`;shell.style.height=`${Math.ceil(overviewCanvas.scrollHeight*zoom)}px`}}else if(state.view==='compare'){const target=state.compareMode==='split'?$('.compare-grid'):$('.compare-overlay-wrap');if(target)target.style.zoom=zoom}else{const device=stage.querySelector(':scope>.device');if(device)device.style.zoom=zoom}if(label)label.textContent=`${Math.round(zoom*100)}%`}
function setZoom(value){state.zoomMode='manual';state.zoom=clampZoom(value);persist();const screen=screens.find(item=>item.id===state.screen)||screens[0];applyZoom(screen)}
function handleZoomWheel(event){if(event.target.closest('.device-content')&&!event.ctrlKey&&!event.metaKey)return;event.preventDefault();setZoom(state.computedZoom+(event.deltaY<0?.1:-.1))}
function captureViewContext(stage){if(!stage)return;state.stageScroll={left:stage.scrollLeft,top:stage.scrollTop};const previousScreen=stage.dataset.renderedScreen,content=stage.querySelector('.device-content');if(previousScreen&&content)state.screenScrolls[previousScreen]={left:content.scrollLeft,top:content.scrollTop};stage.onscroll=null;if(content)content.onscroll=null}
function restoreViewContext(stage,screen){stage.dataset.renderedScreen=screen?.id||'';const selected=state.selectedScreenId===screen?.id&&state.selectedNodeId?stage.querySelector(`[data-node-id="${CSS.escape(state.selectedNodeId)}"]`):null;selectNode(selected,false);const focused=findings.find(item=>item.id===state.focusedFindingId);if(focused?.screenId===screen?.id&&focused.nodeId)stage.querySelectorAll(`[data-node-id="${CSS.escape(focused.nodeId)}"]`).forEach(node=>node.dataset.findingSeverity=focused.severity||'medium');for(const id of state.diagnosticTargetIds)stage.querySelectorAll(`[data-node-id="${CSS.escape(id)}"]`).forEach(node=>node.dataset.diagnosticTarget='true');const stageScroll={...state.stageScroll},savedScroll={...(state.screenScrolls[screen?.id]||{})};requestAnimationFrame(()=>{stage.scrollLeft=stageScroll.left||0;stage.scrollTop=stageScroll.top||0;const content=stage.querySelector('.device-content');if(content){content.scrollLeft=savedScroll.left||0;content.scrollTop=savedScroll.top||0}stage.onscroll=()=>{state.stageScroll={left:stage.scrollLeft,top:stage.scrollTop}};if(content)content.onscroll=()=>{state.screenScrolls[screen.id]={left:content.scrollLeft,top:content.scrollTop}}})}
function renderView(){const screen=screens.find(item=>item.id===state.screen)||screens[0];state.screen=screen?.id;const app=$('.review-app'),stage=$('.stage');captureViewContext(stage);app.dataset.view=state.view;document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.view===state.view)));document.querySelectorAll('[data-compare-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.compareMode===state.compareMode)));updateTreeSelection(state.screen);$('.screen-title').textContent=state.view==='overview'?`Все экраны · ${screens.length}`:(treePaths[state.screen]||[screen?.name||'']).join(' / ');const modeCopy={overview:['Макеты · переходы выключены','overview'],prototype:['Прототип · переходы работают','prototype'],single:['Экран · переходы выключены','single'],compare:['Сравнение · переходы выключены','compare']}[state.view];const modeStatus=$('.mode-status');modeStatus.textContent=modeCopy[0];modeStatus.className=`mode-status ${modeCopy[1]}`;stage.className=`stage ${state.view}${state.interaction==='inspect'?' inspect-mode':''}${state.interaction==='comment'?' comment-mode':''}`;stage.innerHTML=state.view==='overview'?overviewMarkup():(state.view==='compare'&&screen?compareMarkup(screen):(screen?deviceMarkup(screen):'<div class="empty">Нет экранов</div>'));document.querySelectorAll('.device').forEach(configureDevice);applyZoom(screen);stage.onwheel=handleZoomWheel;bindNodes();document.querySelectorAll('[data-open-screen]').forEach(button=>button.addEventListener('click',()=>setScreen(button.dataset.openScreen,'single')));const slider=$('.compare-overlay-slider');if(slider)slider.addEventListener('input',()=>{state.overlayPosition=Number(slider.value);$('.compare-overlay').style.setProperty('--overlay-width',`${state.overlayPosition}%`);persist()});restoreViewContext(stage,screen);renderFindings();renderQueue();renderDiagnostics();renderRevisionNotice();applyPanelState()}
function setView(view,push=true){if(!['overview','prototype','single','compare'].includes(view))return;state.view=view;writeLocation(push);renderView()}function setScreen(id,view='single',push=true){if(!screens.some(screen=>screen.id===id))return;state.screen=id;state.view=view;writeLocation(push);renderView()}function navigate(id,push=true){setScreen(id,'prototype',push)}
let toastTimer;function showToast(message){const toast=$('.workbench-toast');toast.textContent=message;toast.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('visible'),2600)}
function closeWorkbenchMenus(except=null){document.querySelectorAll('.menu[open]').forEach(menu=>{if(menu!==except)menu.removeAttribute('open')})}
function bindWorkbenchMenus(){document.querySelectorAll('.menu').forEach(menu=>{menu.addEventListener('toggle',()=>{if(menu.open)closeWorkbenchMenus(menu)});menu.querySelectorAll('.menu-popover button').forEach(button=>button.addEventListener('click',()=>closeWorkbenchMenus()))});document.addEventListener('pointerdown',event=>{if(!event.target.closest?.('.menu'))closeWorkbenchMenus()});document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;const openMenu=document.querySelector('.menu[open]');if(!openMenu)return;closeWorkbenchMenus();openMenu.querySelector('summary')?.focus()})}
function applyAction(el,event){const type=el.dataset.action,target=el.dataset.target;if(!type||state.view==='overview'||state.view==='compare')return;if(type==='navigate'){event.preventDefault();event.stopPropagation();if(state.view==='prototype')navigate(target);else showToast('Переходы выключены. Выберите режим «Прототип».');return}if(type==='back'){event.preventDefault();event.stopPropagation();history.back();return}if(type==='set-node-state'){event.preventDefault();event.stopPropagation();state.nodeStates[target]=el.dataset.actionState;renderView();return}if(type==='toggle-node-state'||type==='toggle'){event.preventDefault();event.stopPropagation();state.nodeStates[target]=state.nodeStates[target]===el.dataset.actionState?(el.dataset.actionOffState||'default'):el.dataset.actionState;renderView();return}if(type==='reset-state'){event.preventDefault();event.stopPropagation();state.nodeStates={};renderView()}}
function previewNavigationTarget(screenId,visible){document.querySelectorAll('.screen-link[data-navigation-preview=true]').forEach(item=>item.removeAttribute('data-navigation-preview'));const label=$('.navigation-preview-label');if(!visible||!screens.some(screen=>screen.id===screenId)){label.classList.remove('visible');label.textContent='';return}const target=document.querySelector(`.screen-link[data-screen="${CSS.escape(screenId)}"]`);if(target){target.dataset.navigationPreview='true';let parent=target.parentElement;while(parent){if(parent.matches?.('details'))parent.open=true;parent=parent.parentElement}}label.textContent=`Откроется: ${(treePaths[screenId]||[screenId]).join(' / ')}`;label.classList.add('visible')}
function bindNodes(){document.querySelectorAll('.ui-node').forEach(el=>{el.addEventListener('click',event=>{if(['inspect','comment'].includes(state.interaction)){event.preventDefault();event.stopPropagation();selectNode(el);return}applyAction(el,event)});if(el.dataset.action==='navigate'){el.addEventListener('mouseenter',()=>previewNavigationTarget(el.dataset.target,true));el.addEventListener('mouseleave',()=>previewNavigationTarget(el.dataset.target,false));el.addEventListener('focus',()=>previewNavigationTarget(el.dataset.target,true));el.addEventListener('blur',()=>previewNavigationTarget(el.dataset.target,false))}})}
function inspectorMarkup(el){if(!el)return `<div class="panel-empty">${iconMarkup('inspect')}<strong>Выберите элемент</strong><span>Свойства, источник и стандарт появятся здесь.</span></div>`;const c=el.dataset.confidence||'approximate';return `<dl class="inspect-table"><dt>Узел</dt><dd>${esc(el.dataset.nodeId)}</dd><dt>Версия</dt><dd>${esc(el.dataset.versionId)}</dd><dt>Компонент</dt><dd>${esc(el.dataset.component||'—')}</dd><dt>Каталог</dt><dd>${esc(el.dataset.componentRef||'—')}</dd><dt>Источник</dt><dd>${esc(el.dataset.sourceFile||'—')}${el.dataset.sourceLine?':'+esc(el.dataset.sourceLine):''}</dd><dt>Символ</dt><dd>${esc(el.dataset.sourceSymbol||'—')}</dd><dt>Стандарт</dt><dd>${esc(el.dataset.standardRef||'—')}</dd><dt>Решение</dt><dd>${esc(el.dataset.decisionId||'—')}</dd><dt>Семантика</dt><dd>${esc(el.dataset.semanticRole||'—')}${el.dataset.semanticLabel?' · '+esc(el.dataset.semanticLabel):''}</dd><dt>Цель</dt><dd>${esc(el.dataset.targetSize||'—')}</dd><dt>Точность</dt><dd><span class="confidence ${esc(c)}">${esc(c)}</span></dd></dl>`}
function commentComposerMarkup(el){if(!el)return `<div class="panel-empty compact">${iconMarkup('comment')}<strong>Выберите элемент</strong><span>Комментарий будет привязан к выбранному узлу.</span></div>`;return `<form class="comment-form"><div class="comment-target">${esc(treePaths[state.screen]?.join(' / ')||state.screen)} · ${esc(el.dataset.nodeId)}</div><textarea name="comment" required placeholder="Что нужно изменить?"></textarea><div class="comment-form-row"><select name="priority"><option value="medium">Средний приоритет</option><option value="high">Высокий приоритет</option><option value="low">Низкий приоритет</option></select><button type="submit">Добавить</button></div></form>`}
function bindCommentForm(form,el){if(!form||!el)return;form.addEventListener('submit',event=>{event.preventDefault();const data=new FormData(form),text=String(data.get('comment')||'').trim();if(!text)return;const id=`annotation-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;state.annotations.push({id,screenId:state.screen,nodeId:el.dataset.nodeId,versionId:el.dataset.versionId||state.activeVersion,text,priority:data.get('priority')||'medium',status:'new',source:{file:el.dataset.sourceFile||'',line:Number(el.dataset.sourceLine)||null,symbol:el.dataset.sourceSymbol||''},createdAt:new Date().toISOString()});persist();form.reset();renderQueue();showToast('Комментарий добавлен')})}
function selectNode(el,remember=true){document.querySelectorAll('[data-selected=true]').forEach(n=>n.removeAttribute('data-selected'));document.querySelectorAll('[data-finding-severity]').forEach(n=>n.removeAttribute('data-finding-severity'));state.selected=el;if(remember){state.selectedNodeId=el?.dataset.nodeId||null;state.selectedScreenId=el?state.screen:null;if(state.interaction==='inspect')setInspectorTab('inspect');if(state.interaction==='comment')setInspectorTab('comments');persist()}if(el)el.dataset.selected='true';$('.inspect-body').innerHTML=inspectorMarkup(el);const composer=$('.comment-composer');if(composer){composer.innerHTML=commentComposerMarkup(el);bindCommentForm(composer.querySelector('.comment-form'),el)}}
const findingRank={blocker:4,high:3,medium:2,low:1};
function addFindingBadges(){document.querySelectorAll('.screen-issue-count').forEach(item=>item.remove());const byScreen=new Map();for(const item of findings){const current=byScreen.get(item.screenId)||{count:0,severity:'low'};current.count+=1;if((findingRank[item.severity]||0)>(findingRank[current.severity]||0))current.severity=item.severity;byScreen.set(item.screenId,current)}for(const [screenId,data] of byScreen){const target=document.querySelector(`.screen-link[data-screen="${CSS.escape(screenId)}"]`);if(!target)continue;const badge=document.createElement('span');badge.className='screen-issue-count';badge.dataset.severity=data.severity;badge.textContent=String(data.count);badge.title=`Замечаний: ${data.count}`;target.append(badge)}}
function setFindingDecision(id,decision){state.findingDecisions[id]=decision;persist();renderFindings()}
function selectedFindings(){return findings.filter(item=>state.findingDecisions[item.id]==='accepted')}
function renderRevisionNotice(){const badge=$('.revision-badge'),notice=$('.revision-notice');if(badge)badge.textContent=reviewRevision.split('-').at(-1).slice(0,6);if(notice)notice.hidden=!state.staleReview}
function migrateReviewState(){const old=state.staleReview;if(!old)return;const compatibleRuntime=(old.runtimeFindings||[]).filter(item=>item?.id&&screens.some(screen=>screen.id===item.screenId)&&(!item.nodeId||nodes[item.nodeId])).map(item=>({...item,instances:(item.instances||[]).filter(id=>nodes[id])}));state.runtimeFindings=compatibleRuntime;const validIds=new Set(findings.map(item=>item.id));state.findingDecisions=Object.fromEntries(Object.entries(old.findingDecisions||{}).filter(([id])=>validIds.has(id)));const annotations=(old.annotations||[]).filter(item=>(!item.screenId||screens.some(screen=>screen.id===item.screenId))&&(!item.nodeId||nodes[item.nodeId])&&(!item.versionId||versionById[item.versionId]));const annotationIds=new Set(state.annotations.map(item=>item.id));for(const item of annotations)if(!annotationIds.has(item.id))state.annotations.push(item);if(old.selectedNodeId&&nodes[old.selectedNodeId]&&screens.some(screen=>screen.id===old.selectedScreenId)){state.selectedNodeId=old.selectedNodeId;state.selectedScreenId=old.selectedScreenId}const total=(old.annotations||[]).length+Object.keys(old.findingDecisions||{}).length+(old.runtimeFindings||[]).length,migrated=annotations.length+Object.keys(state.findingDecisions).length+compatibleRuntime.length;state.staleReview=null;persist();renderView();showToast(`Перенесено ${migrated}; без привязки осталось ${Math.max(0,total-migrated)}`)}
function discardReviewState(){state.staleReview=null;persist();renderRevisionNotice();showToast('Начато чистое ревью текущей версии')}
function approveActiveVersion(){if(versionById[state.activeVersion]?.kind!=='proposal')return;state.versionDecision='accepted';persist();renderQueue();renderFixQueue();showToast('Вариант принят')}
function rejectActiveVersion(){if(versionById[state.activeVersion]?.kind!=='proposal')return;state.versionDecision='rejected';persist();renderQueue();renderFixQueue();showToast('Вариант отправлен на доработку')}
function prepareSourceHandoff(){if(versionById[state.activeVersion]?.kind!=='proposal'||state.versionDecision!=='accepted')return;state.sourcePreparedVersionId=state.activeVersion;persist();renderFixQueue();downloadJson('ui-source-change-request.json',sourceRequestPayload());showToast('Подготовлен план внедрения; исходный код не изменён')}
function codexTaskContext(kind){const selected=selectedFindings(),openAnnotations=state.annotations.filter(item=>!['resolved','rejected'].includes(item.status||'new')).slice(0,30).map(item=>({id:item.id,screenId:item.screenId,nodeId:item.nodeId,versionId:item.versionId,text:item.text,priority:item.priority,status:item.status}));return {type:'ui-code-preview-codex-handoff',version:1,kind,reviewRevision,project:ir.project?.name||'Project',artifactDir:previewContext.artifactDir||'',scope:state.reviewScope,screenIds:reviewScopeScreens().map(item=>item.id),activeVersion:state.activeVersion,baselineVersion,acceptedFindingIds:selected.map(item=>item.id),annotations:openAnnotations,variantCount:2,sourceChangeAllowed:false}}
function codexTaskDescriptor(kind='expert'){const artifactDir=String(previewContext.artifactDir||'').trim(),context=codexTaskContext(kind);if(!artifactDir)return {supported:false,kind,error:'Каталог макета не записан в HTML'};if(kind==='proposal'&&!context.acceptedFindingIds.length)return {supported:false,kind,error:'Сначала выберите проблемы для исправления'};const task=kind==='proposal'?'Создай два осмысленно различающихся варианта исправления только для выбранных проблем.':'Проведи глубокое UI/UX-ревью собранных макетов и создай исправленные Before/After варианты для обоснованных проблем.';const prompt=`Используй $ui-code-preview. В рабочем каталоге находятся ui-ir.json и ui-preview.html. ${task}\n\nКонтекст handoff:\n${JSON.stringify(context)}\n\nОбязательный результат:\n1. Прочитай ui-ir.json и повтори нужные детерминированные проверки, чтобы восстановить runtime-проблемы по стабильным ID.\n2. Не изменяй исходный проект и immutable baseline. Работай только с файлами макета в текущем каталоге.\n3. Добавь экспертные findings и sparse proposal-версии в ui-ir.json; сохрани устойчивые ID и привязки к экранам/узлам.\n4. Для выбранных проблем создай до двух вариантов только при реальном UX-компромиссе; иначе один сдержанный вариант.\n5. Пересобери ui-preview.html, выполни strict coverage/platform validation и headless smoke.\n6. В финале перечисли созданные версии и попроси вернуться в макет и нажать «Обновить макет».`;const params=new URLSearchParams({prompt,path:artifactDir});return {supported:true,kind,path:artifactDir,prompt,url:`codex://new?${params.toString()}`,context}}
function openCodexTask(kind){const descriptor=codexTaskDescriptor(kind);if(!descriptor.supported){showToast(descriptor.error);if(kind==='proposal')downloadJson('ui-fix-request.json',fixRequestPayload());else if(state.diagnostics)downloadJson('ui-expert-review-request.json',expertReviewRequestPayload());return}state.codexHandoff={kind,status:'prepared',createdAt:new Date().toISOString(),acceptedFindingIds:descriptor.context.acceptedFindingIds,screenIds:descriptor.context.screenIds,artifactDir:descriptor.path};persist();renderCodexHandoff();renderReviewNextAction();showToast('Задача подготовлена в Codex — отправьте запрос');location.href=descriptor.url}
async function copyCodexTask(){const kind=state.codexHandoff?.kind||'expert',descriptor=codexTaskDescriptor(kind);if(!descriptor.supported){showToast(descriptor.error);return}try{await navigator.clipboard.writeText(descriptor.prompt);showToast('Запрос для Codex скопирован')}catch(_){showToast('Не удалось скопировать запрос')}}
function refreshPreview(){location.reload()}
function renderCodexHandoff(){const panel=$('.codex-handoff-panel'),status=$('.codex-handoff-status'),meta=$('.codex-handoff-meta');if(!panel||!status||!meta)return;const value=state.codexHandoff;panel.hidden=!value;if(!value)return;status.textContent=value.kind==='proposal'?'Задача на вариант открыта':'Задача на AI-ревью открыта';meta.textContent=`${new Date(value.createdAt).toLocaleString()} · отправьте подготовленный запрос в Codex. После завершения вернитесь сюда и обновите макет.`}
function renderFixQueue(){const selected=selectedFindings(),stats=$('.fix-queue-stats'),copy=$('.copy-fix-request');document.querySelectorAll('.fix-queue-count').forEach(count=>count.textContent=String(selected.length));if(!stats)return;const ready=selected.filter(item=>item.proposalVersionId).length,needed=selected.length-ready,activeProposal=versionById[state.activeVersion]?.kind==='proposal',approved=activeProposal&&state.versionDecision==='accepted',prepared=approved&&state.sourcePreparedVersionId===state.activeVersion;stats.innerHTML=selected.length?`<span class="fix-queue-stat">Выбрано ${selected.length}</span><span class="fix-queue-stat">Готово ${ready}</span><span class="fix-queue-stat">Нужен вариант ${needed}</span>`:'<span class="fix-queue-stat">Выберите проблемы во вкладке «Проблемы»</span>';if(copy){copy.disabled=!selected.length;copy.innerHTML=`${iconMarkup('copy')}<span>${selected.length?`Скопировать · ${selected.length}`:'Скопировать задание'}</span>`}const phase=prepared?4:approved?3:activeProposal?2:selected.length?1:0;document.querySelectorAll('.review-phase').forEach((item,index)=>{item.classList.toggle('complete',index<phase);item.classList.toggle('active',index===phase)});renderReviewNextAction()}
function renderReviewNextAction(){const button=$('.review-next-action'),status=$('.review-context-status'),reject=$('.review-reject-action');if(!button||!status)return;const selected=selectedFindings(),activeProposal=versionById[state.activeVersion]?.kind==='proposal',approved=activeProposal&&state.versionDecision==='accepted',prepared=approved&&state.sourcePreparedVersionId===state.activeVersion,needsProposal=selected.some(item=>!item.proposalVersionId),waitingProposal=state.codexHandoff?.kind==='proposal'&&state.codexHandoff.status==='prepared'&&!activeProposal;button.disabled=state.diagnosticsRunning;reject.hidden=!activeProposal||approved;reject.onclick=rejectActiveVersion;if(state.diagnosticsRunning){button.dataset.action='wait';button.textContent='Проверяем макеты…';status.textContent=state.diagnosticsProgress||'Выполняются сценарии'}else if(waitingProposal){button.dataset.action='refresh';button.textContent='Обновить макет';status.textContent='После завершения задачи Codex загрузите пересобранный вариант'}else if(!state.diagnostics){button.dataset.action='run';button.textContent='Запустить ревью';status.textContent='Первый шаг — проверить выбранную область'}else if(!selected.length){button.dataset.action='problems';button.textContent='Выбрать проблемы';status.textContent='Откройте проблемы и отметьте нужные исправления'}else if(!activeProposal||needsProposal){button.dataset.action='proposal';button.textContent=`Создать вариант · ${selected.length}`;status.textContent='Откроется задача Codex с каталогом макета; исходный код не изменится'}else if(!approved){button.dataset.action='approve';button.textContent='Принять вариант';status.textContent='Сравните Before/After перед принятием'}else if(!prepared){button.dataset.action='source';button.textContent='Подготовить внедрение';status.textContent='Будет создан план изменений без правки исходного кода'}else{button.dataset.action='export';button.textContent='Экспортировать ревью';status.textContent='Ревью и план внедрения подготовлены'}}
function handleReviewNextAction(){const action=$('.review-next-action')?.dataset.action;if(action==='run')runAutomatedReview();else if(action==='problems')setReviewSection('problems');else if(action==='proposal'){setReviewSection('changes');openCodexTask('proposal')}else if(action==='refresh')refreshPreview();else if(action==='approve')approveActiveVersion();else if(action==='source')prepareSourceHandoff();else if(action==='export')downloadFeedback()}
function focusFinding(id,compare=false){const item=findings.find(value=>value.id===id);if(!item)return;setInspectorTab('review');state.reviewSection=compare?'changes':'problems';renderReviewSections();state.focusedFindingId=id;state.diagnosticTargetIds=[];if(compare&&item.proposalVersionId&&versionById[item.proposalVersionId]){state.activeVersion=item.proposalVersionId;state.compareTargetVersion=item.proposalVersionId;versionSelect.value=state.activeVersion;renderCompareVersionOptions();persist();setScreen(item.screenId,'compare');showToast('Открыто сравнение исправления');return}persist();setScreen(item.screenId,'single');requestAnimationFrame(()=>{const element=item.nodeId?document.querySelector(`[data-node-id="${CSS.escape(item.nodeId)}"]`):null;if(!element){showToast('Открыт экран замечания; точный элемент не указан');return}element.dataset.findingSeverity=item.severity||'medium';element.scrollIntoView({block:'center',inline:'center'});showToast('Показан проблемный элемент')})}
function auditFindingIds(item){return [...new Set((Array.isArray(item.findingIds)?item.findingIds:[]).filter(id=>findings.some(finding=>finding.id===id)))]}
function auditLinksMarkup(item){const ids=auditFindingIds(item);if(!ids.length)return '<span class="audit-depth-unlinked">Нет отдельной карточки исправления</span>';const ready=ids.filter(id=>findings.find(finding=>finding.id===id)?.proposalVersionId).length,encoded=esc(ids.join(','));return `<div class="audit-depth-links"><button type="button" class="audit-depth-action primary" data-audit-findings="${encoded}">Показать проблемы · ${ids.length}</button><button type="button" class="audit-depth-action" data-accept-findings="${encoded}">Все в исправление</button>${ready?`<span class="audit-depth-unlinked">До/после готово: ${ready}</span>`:''}</div>`}
function auditDepthMarkup(){const checks=Array.isArray(expertAudit.interactionChecks)?expertAudit.interactionChecks:[],layouts=Array.isArray(expertAudit.layoutChecks)?expertAudit.layoutChecks:[],ux=Array.isArray(expertAudit.uxAssessment)?expertAudit.uxAssessment:[];const item=(value,label,statusAttr='result')=>`<li class="audit-depth-item" data-${statusAttr}="${esc(value[statusAttr]||'not-run')}"><div class="audit-depth-title"><b>${esc(label)}</b><span>${esc(value[statusAttr]||'not-run')}</span></div><div>${esc(value.observed||value.observation||value.expected||'')}</div>${auditLinksMarkup(value)}</li>`;const checkMarkup=checks.length?`<details class="audit-depth"><summary>Проверки взаимодействий · ${checks.length}</summary><ul class="audit-depth-list">${checks.map(value=>item(value,value.id||'сценарий')).join('')}</ul></details>`:'';const layoutMarkup=layouts.length?`<details class="audit-depth"><summary>Типографика и геометрия · ${layouts.length}</summary><ul class="audit-depth-list">${layouts.map(value=>item(value,value.kind||'layout')).join('')}</ul></details>`:'';const uxMarkup=ux.length?`<details class="audit-depth"><summary>Отдельный UX-аудит · ${ux.length}</summary><ul class="audit-depth-list">${ux.map(value=>item(value,value.lens||'UX','status')).join('')}</ul></details>`:'';return checkMarkup+layoutMarkup+uxMarkup}
const nextPaintIn=win=>new Promise(resolve=>win.requestAnimationFrame(()=>win.requestAnimationFrame(resolve)));const nextPaint=()=>nextPaintIn(window);
function diagnosticProfiles(){return diagnosticsConfig.profiles?.length?diagnosticsConfig.profiles:[{id:'current',label:'Текущее окно',viewport:'current',zoomLevels:[.2,1,2]}]}
async function createDiagnosticContext(profile){if(profile.viewport==='current'||!profile.viewport?.width||!profile.viewport?.height)return {win:window,doc:document,cleanup(){}};const frame=document.createElement('iframe');frame.setAttribute('aria-hidden','true');frame.tabIndex=-1;Object.assign(frame.style,{position:'fixed',left:'-20000px',top:'0',width:`${profile.viewport.width}px`,height:`${profile.viewport.height}px`,border:'0',opacity:'0',pointerEvents:'none',zIndex:'-1'});const source='<!doctype html>'+document.documentElement.outerHTML;const loaded=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(`Не удалось открыть sandbox ${profile.label}`)),10000);frame.addEventListener('load',()=>{clearTimeout(timer);resolve()},{once:true})});frame.srcdoc=source;document.body.append(frame);await loaded;await nextPaintIn(frame.contentWindow);if(!frame.contentWindow?.__uiPreviewDiagnostics)throw new Error(`Диагностический API недоступен в профиле ${profile.label}`);return {win:frame.contentWindow,doc:frame.contentDocument,cleanup(){frame.remove()}}}
async function withDiagnosticProfile(profile,task){const context=await createDiagnosticContext(profile);try{return await task(context)}finally{context.cleanup()}}
function diagnosticsScenario(kind){return (diagnosticsConfig.scenarios||[]).find(item=>item.kind===kind)}
function diagnosticCheck(results,scenarioId,result,title,message,metrics={},screenId=null,severity='medium'){if(screenId&&state.reviewScope==='current'&&screenId!==state.screen)return;results.push({id:`runtime-${scenarioId}-${results.length+1}`,scenarioId,result,severity,title,message,metrics,screenId,createdAt:new Date().toISOString()})}
function rectOverlap(a,b,tolerance=1){const width=Math.min(a.right,b.right)-Math.max(a.left,b.left),height=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);return width>tolerance&&height>tolerance?Math.round(width*height):0}
function nodeLabel(el){return el.dataset?.nodeId||el.getAttribute('aria-label')||el.textContent?.trim().slice(0,40)||el.tagName.toLowerCase()}
function visibleElement(el){const style=el.ownerDocument.defaultView.getComputedStyle(el),rect=el.getBoundingClientRect();return style.display!=='none'&&style.visibility!=='hidden'&&Number(style.opacity)!==0&&rect.width>0&&rect.height>0}
function accessibleName(el){const doc=el.ownerDocument,labelled=el.getAttribute('aria-labelledby');if(labelled){const value=labelled.split(/\s+/).map(id=>doc.getElementById(id)?.textContent?.trim()||'').filter(Boolean).join(' ');if(value)return value}const own=el.getAttribute('aria-label')||el.getAttribute('title');if(own?.trim())return own.trim();if(el.labels?.length)return [...el.labels].map(label=>label.textContent?.trim()||'').filter(Boolean).join(' ');if(el.tagName==='INPUT'||el.tagName==='TEXTAREA'||el.tagName==='SELECT')return '';return el.textContent?.replace(/\s+/g,' ').trim()||''}
function textLineCount(el){if(!el.textContent?.trim())return 0;const range=el.ownerDocument.createRange();range.selectNodeContents(el);const baselines=[];for(const rect of range.getClientRects()){if(rect.width<.5||rect.height<.5)continue;if(!baselines.some(bottom=>Math.abs(bottom-rect.bottom)<2.5))baselines.push(rect.bottom)}return baselines.length}
function compactList(items,limit=5){const labels=items.slice(0,limit).map(nodeLabel);return labels.join(', ')+(items.length>limit?` +${items.length-limit}`:'')}
function setDiagnosticsProgress(message){state.diagnosticsProgress=message;renderDiagnostics();renderReviewLauncher()}
function diagnosticNodeIds(item){const values=[],push=value=>{if(Array.isArray(value))value.forEach(push);else if(typeof value==='string'&&nodes[value])values.push(value)};for(const key of ['overlaps','overflow','multiline','smallTargets','paddingVariance','unnamed','symbolic'])push(item.metrics?.[key]);return [...new Set(values)]}
function diagnosticFindingId(checkId){return `runtime-finding-${checkId}`}
function diagnosticFindingData(check){const id=diagnosticFindingId(check.id),screenId=screens.some(screen=>screen.id===check.screenId)?check.screenId:(state.screen||screens[0]?.id),nodeIds=diagnosticNodeIds(check);return {id,title:`Диагностика: ${check.title}`,category:'runtime-diagnostic',severity:['high','medium','low'].includes(check.severity)?check.severity:'medium',confidence:'high',screenId,nodeId:nodeIds[0]||null,observation:check.message,impact:'Измеренная ошибка может нарушать читаемость, управление или устойчивость макета в проверенном состоянии.',recommendation:'Исправить перечисленные узлы и повторять автоматическую проверку до результата pass.',evidence:[{type:'heuristic',ref:`runtime-diagnostics.${check.scenarioId}`,note:`Автоматически измерено ${check.createdAt||'в текущем прогоне'}.`}],effort:'medium',noProposalReason:'Нужна новая proposal-версия по результату runtime-диагностики.',status:'open',runtimeDiagnosticId:check.id,instances:nodeIds}}
function diagnosticGroupKey(check){return `${check.scenarioId}:${check.screenId||'workbench'}`}
function groupDiagnosticChecks(checks){const groups=new Map();for(const check of checks){const key=diagnosticGroupKey(check);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(check)}return [...groups.values()]}
function diagnosticGroupData(checks){const first=checks[0],screenId=screens.some(screen=>screen.id===first.screenId)?first.screenId:(state.screen||screens[0]?.id),scenario=(diagnosticsConfig.scenarios||[]).find(item=>item.id===first.scenarioId),nodeIds=[...new Set(checks.flatMap(diagnosticNodeIds))],rank={high:3,medium:2,low:1},severity=checks.reduce((best,item)=>(rank[item.severity]||0)>(rank[best]||0)?item.severity:best,'low'),id=`runtime-group-${revisionHash(diagnosticGroupKey(first))}`;return {id,title:`Автопроверка: ${scenario?.label||first.title}${first.screenId?` · ${screens.find(item=>item.id===first.screenId)?.name||first.screenId}`:''}`,category:'runtime-diagnostic',severity,confidence:'high',screenId,nodeId:nodeIds[0]||null,observation:`Непрошедших проверок в группе: ${checks.length}. ${checks.slice(0,3).map(item=>item.message).join(' ')}`,impact:'Повторяющаяся измеренная ошибка может нарушать читаемость, управление или устойчивость макета в нескольких состояниях.',recommendation:'Исправить общую причину для перечисленных состояний и повторять автоматическую проверку до результата pass.',evidence:checks.slice(0,12).map(item=>({type:'heuristic',ref:`runtime-diagnostics.${item.id}`,note:item.message})),effort:checks.length>4?'large':'medium',noProposalReason:'Нужна новая proposal-версия по результату runtime-диагностики.',status:'open',systemic:checks.length>1,runtimeDiagnosticId:first.id,runtimeDiagnosticIds:checks.map(item=>item.id),instances:nodeIds}}
function createDiagnosticFinding(check,accept=false){setInspectorTab('review');const id=diagnosticFindingId(check.id),existing=findings.find(item=>item.id===id);if(!existing){const screenId=screens.some(screen=>screen.id===check.screenId)?check.screenId:(state.screen||screens[0]?.id),nodeIds=diagnosticNodeIds(check);state.runtimeFindings.push({id,title:`Диагностика: ${check.title}`,category:'runtime-diagnostic',severity:['high','medium','low'].includes(check.severity)?check.severity:'medium',confidence:'high',screenId,nodeId:nodeIds[0]||null,observation:check.message,impact:'Измеренная ошибка может нарушать читаемость, управление или устойчивость макета в проверенном состоянии.',recommendation:'Исправить перечисленные узлы и повторять автоматическую проверку до результата pass.',evidence:[{type:'heuristic',ref:`runtime-diagnostics.${check.scenarioId}`,note:`Автоматически измерено ${check.createdAt||'в текущем прогоне'}.`}],effort:'medium',noProposalReason:'Нужна новая proposal-версия по результату runtime-диагностики.',status:'open',runtimeDiagnosticId:check.id,instances:nodeIds})}if(accept)state.findingDecisions[id]='accepted';state.findingFocus=[id];state.findingFilter='linked';persist();renderFindings();renderDiagnostics();$('.automated-review')?.scrollIntoView({block:'start',behavior:'smooth'});showToast(accept?'Проблема добавлена в исправление':'Создана карточка проблемы')}
function renderReviewLauncher(){const root=$('.review-launcher'),button=$('.run-review'),handoffs=document.querySelectorAll('.export-review-request'),codexButtons=document.querySelectorAll('.open-codex-review'),status=$('.review-launcher-status'),meta=$('.review-launcher-meta'),scope=$('.review-scope-select');if(!root||!button||!status)return;const report=state.diagnostics,counts=report?.summary||{},actionable=(report?.checks||[]).filter(item=>item.result!=='pass'),groups=groupDiagnosticChecks(actionable),targetScreens=reviewScopeScreens(),variants=stateVariantCases(targetScreens);root.dataset.state=state.diagnosticsRunning?'running':report?'complete':'idle';button.disabled=state.diagnosticsRunning;button.innerHTML=state.diagnosticsRunning?`${iconMarkup('activity')}<span>Проверяем макеты…</span>`:`${iconMarkup('activity')}<span>${report?'Проверить снова':'Запустить ревью'}</span>`;for(const handoff of handoffs)handoff.disabled=state.diagnosticsRunning||!report;for(const codexButton of codexButtons)codexButton.disabled=state.diagnosticsRunning||!report;if(scope){scope.value=state.reviewScope;scope.disabled=state.diagnosticsRunning}if(meta)meta.textContent=report?`${report.screenIds?.length||targetScreens.length} экранов · ${report.profiles?.length||diagnosticProfiles().length} профиля · ${report.checks?.length||0} проверок`:`${targetScreens.length} экранов · ${diagnosticProfiles().length} профиля · ${variants.length} вариантов состояния`;status.textContent=state.diagnosticsRunning?(state.diagnosticsProgress||'Подготовка сценариев…'):report?(groups.length?`Найдено групп проблем: ${groups.length}. Перейдите в «Проблемы».`:`Проверка пройдена: ${counts.pass||0}, проблем не найдено.`):'Проверим переходы, состояния, масштаб, геометрию, контраст, клавиатуру и доступность.';renderCoverage();renderCodexHandoff()}
async function runAutomatedReview(){if(state.diagnosticsRunning)return;setInspectorTab('review');state.reviewSection='summary';renderReviewSections();state.findingFocus=[];await runDiagnostics();const actionable=(state.diagnostics?.checks||[]).filter(item=>item.result!=='pass'),groups=groupDiagnosticChecks(actionable),ids=[];for(const checks of groups){const data=diagnosticGroupData(checks),existing=state.runtimeFindings.find(item=>item.id===data.id);if(existing)Object.assign(existing,data);else state.runtimeFindings.push(data);ids.push(data.id)}const stateCases=(state.diagnostics?.checks||[]).filter(item=>item.scenarioId==='state-matrix'&&item.metrics?.stateNodeId).length;state.reviewRuns.push({id:`run-${Date.now()}`,createdAt:new Date().toISOString(),sessionName:state.reviewSessionName,scope:state.reviewScope,scopeLabel:state.reviewScope==='all'?'Все экраны':screens.find(item=>item.id===state.screen)?.name||'Текущий экран',screenIds:state.diagnostics?.screenIds||[],checks:state.diagnostics?.checks?.length||0,stateCases,issues:ids.length,summary:state.diagnostics?.summary||{}});state.reviewRuns=state.reviewRuns.slice(-20);state.findingFocus=ids;state.findingFilter=ids.length?'linked':'all';state.reviewSection=ids.length?'problems':'summary';persist();renderFindings();renderDiagnostics();renderReviewLauncher();renderReviewHistory();renderReviewSections();showToast(ids.length?`Ревью завершено: групп проблем ${ids.length}`:'Ревью завершено: проблем не найдено')}
function focusDiagnostic(check){const ids=diagnosticNodeIds(check);state.diagnosticTargetIds=ids;if(check.screenId&&screens.some(screen=>screen.id===check.screenId))setScreen(check.screenId,'single');else renderView();requestAnimationFrame(()=>{for(const id of ids)document.querySelectorAll(`[data-node-id="${CSS.escape(id)}"]`).forEach(node=>node.dataset.diagnosticTarget='true');document.querySelector('[data-diagnostic-target=true]')?.scrollIntoView({block:'center',inline:'center'});persist();showToast(ids.length?`Подсвечено элементов: ${ids.length}`:'Для проверки нет точной привязки к узлу')})}
function renderDiagnostics(){const status=$('.diagnostics-status'),progress=$('.diagnostics-progress'),summary=$('.diagnostics-summary'),list=$('.diagnostics-results'),run=$('.run-diagnostics'),clear=$('.clear-diagnostics'),reportNode=$('#runtime-diagnostics-report');if(!status||!list)return;document.documentElement.dataset.diagnosticsStatus=state.diagnosticsRunning?'running':state.diagnostics?'complete':'idle';if(reportNode)reportNode.textContent=JSON.stringify(state.diagnostics);run.disabled=state.diagnosticsRunning;clear.disabled=state.diagnosticsRunning;progress.textContent=state.diagnosticsProgress||'';status.className='diagnostics-status';if(state.diagnosticsRunning){status.textContent='выполняется';status.classList.add('running')}else if(!state.diagnostics){status.textContent='не запускалась'}else{const failed=state.diagnostics.summary?.fail||0;status.textContent=failed?`ошибок ${failed}`:'пройдено';status.classList.add(failed?'fail':'pass')}if(!state.diagnostics){summary.innerHTML='';list.innerHTML='<p class="diagnostics-empty">Проверка ещё не запускалась.</p>';return}const counts=state.diagnostics.summary||{};summary.innerHTML=`<span class="diagnostics-count">Пройдено ${counts.pass||0}</span><span class="diagnostics-count">Предупреждения ${counts.warning||0}</span><span class="diagnostics-count">Ошибки ${counts.fail||0}</span>`;list.innerHTML=(state.diagnostics.checks||[]).map(item=>{const actionable=item.result!=='pass',created=findings.some(finding=>finding.runtimeDiagnosticId===item.id||finding.runtimeDiagnosticIds?.includes(item.id)),targets=diagnosticNodeIds(item).length;return `<article class="diagnostic-card" data-result="${esc(item.result)}"><b>${esc(item.title)}</b><div>${esc(item.message)}</div><div class="diagnostic-meta">${esc(item.screenId||'workbench')} · ${esc(item.result)} · ${esc(item.severity)}${targets?` · узлов ${targets}`:''}</div>${actionable?`<div class="diagnostic-card-actions">${targets?`<button type="button" class="diagnostic-card-action" data-focus-diagnostic="${esc(item.id)}">${iconMarkup('inspect')}Показать</button>`:''}<button type="button" class="diagnostic-card-action" data-create-diagnostic="${esc(item.id)}" ${created?'disabled':''}>${created?'Создано':'Создать проблему'}</button><button type="button" class="diagnostic-card-action primary" data-accept-diagnostic="${esc(item.id)}">${iconMarkup('check')}В исправление</button></div>`:''}</article>`}).join('')||'<p class="diagnostics-empty">Нет результатов.</p>';list.querySelectorAll('[data-focus-diagnostic]').forEach(button=>button.addEventListener('click',()=>{const item=state.diagnostics.checks.find(check=>check.id===button.dataset.focusDiagnostic);if(item)focusDiagnostic(item)}));list.querySelectorAll('[data-create-diagnostic]').forEach(button=>button.addEventListener('click',()=>{const item=state.diagnostics.checks.find(check=>check.id===button.dataset.createDiagnostic);if(item)createDiagnosticFinding(item)}));list.querySelectorAll('[data-accept-diagnostic]').forEach(button=>button.addEventListener('click',()=>{const item=state.diagnostics.checks.find(check=>check.id===button.dataset.acceptDiagnostic);if(item)createDiagnosticFinding(item,true)}))}
async function runZoomResetDiagnostic(results,scenario){state.view='overview';state.zoomMode='manual';state.zoom=.65;renderView();await nextPaint();setZoom(1);await nextPaint();const canvas=$('.overview-canvas'),label=$('.zoom-label')?.textContent?.trim(),transform=canvas?.style.transform||'';const ok=label==='100%'&&Math.abs(state.computedZoom-1)<.001&&/scale\(1\)/.test(transform);diagnosticCheck(results,scenario.id,ok?'pass':'fail','Сброс масштаба',ok?'Холст и индикатор синхронно вернулись к 100%.':`Состояния расходятся: label=${label||'—'}, zoom=${state.computedZoom}, transform=${transform||'—'}.`,{label,computedZoom:state.computedZoom,transform},null,ok?'low':'high')}
async function runOverviewGeometryDiagnostic(results,scenario){for(const profile of diagnosticProfiles())await withDiagnosticProfile(profile,async({win,doc})=>{const api=win.__uiPreviewDiagnostics;api.apply({view:'overview',zoom:1});await nextPaintIn(win);let baseline=null,maxDrift=0,overlaps=0,shellMismatch=0,labelMismatch=0;for(const rawZoom of profile.zoomLevels||[.2,1,2]){const zoom=clampZoom(Number(rawZoom)||1);api.apply({view:'overview',zoom});await nextPaintIn(win);const canvas=doc.querySelector('.overview-canvas'),shell=doc.querySelector('.overview-canvas-shell'),cards=[...doc.querySelectorAll('.screen-card')];if(!canvas||!shell)continue;const canvasRect=canvas.getBoundingClientRect(),positions=cards.map(card=>{const rect=card.getBoundingClientRect();return {id:card.dataset.screenCard,left:(rect.left-canvasRect.left)/zoom,top:(rect.top-canvasRect.top)/zoom,width:rect.width/zoom,height:rect.height/zoom,rect}});if(!baseline)baseline=positions;else for(const item of positions){const first=baseline.find(value=>value.id===item.id);if(first)maxDrift=Math.max(maxDrift,Math.abs(first.left-item.left),Math.abs(first.top-item.top),Math.abs(first.width-item.width),Math.abs(first.height-item.height))}for(let i=0;i<positions.length;i++)for(let j=i+1;j<positions.length;j++)if(rectOverlap(positions[i].rect,positions[j].rect)>0)overlaps+=1;const expectedWidth=Math.ceil(canvas.scrollWidth*zoom),expectedHeight=Math.ceil(canvas.scrollHeight*zoom);if(Math.abs(parseFloat(shell.style.width||'0')-expectedWidth)>2||Math.abs(parseFloat(shell.style.height||'0')-expectedHeight)>2)shellMismatch+=1;if(doc.querySelector('.zoom-label')?.textContent?.trim()!==`${Math.round(zoom*100)}%`)labelMismatch+=1}const ok=overlaps===0&&maxDrift<=1.5&&shellMismatch===0&&labelMismatch===0;diagnosticCheck(results,scenario.id,ok?'pass':'fail',`Геометрия обзора · ${profile.label}`,ok?'Карточки сохраняют координаты, не пересекаются, а оболочка масштабируется вместе с холстом.':`Пересечения: ${overlaps}; дрейф: ${maxDrift.toFixed(1)}px; ошибки оболочки: ${shellMismatch}; индикатора: ${labelMismatch}.`,{profileId:profile.id,viewport:profile.viewport,zoomLevels:profile.zoomLevels,overlaps,maxDrift,shellMismatch,labelMismatch,stage:{width:doc.querySelector('.stage')?.clientWidth||0,height:doc.querySelector('.stage')?.clientHeight||0}},null,ok?'low':'high')})}
async function runMenuDiagnostic(results,scenario){closeWorkbenchMenus();let exclusivityFailures=0;const menus=[...document.querySelectorAll('.menu')];for(const menu of menus){menu.querySelector('summary')?.click();await nextPaint();if(document.querySelectorAll('.menu[open]').length!==1||!menu.open)exclusivityFailures+=1}document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await nextPaint();const escapeOpen=document.querySelectorAll('.menu[open]').length;menus[0]?.querySelector('summary')?.click();await nextPaint();$('.stage')?.dispatchEvent(new Event('pointerdown',{bubbles:true}));await nextPaint();const outsideOpen=document.querySelectorAll('.menu[open]').length;menus[0]?.querySelector('summary')?.click();await nextPaint();menus[0]?.querySelector('.menu-popover button')?.click();await nextPaint();const actionOpen=document.querySelectorAll('.menu[open]').length;const ok=exclusivityFailures===0&&escapeOpen===0&&outsideOpen===0&&actionOpen===0;diagnosticCheck(results,scenario.id,ok?'pass':'fail','Состояния верхнего меню',ok?'Открыто не больше одного меню; Escape, внешний клик и выбор команды закрывают меню.':`Сбои: эксклюзивность ${exclusivityFailures}, Escape ${escapeOpen}, внешний клик ${outsideOpen}, команда ${actionOpen}.`,{menus:menus.length,exclusivityFailures,escapeOpen,outsideOpen,actionOpen},null,ok?'low':'high');closeWorkbenchMenus()}
function inspectLayoutRoot(root,screen){const view=root.ownerDocument.defaultView,overlaps=[],overflow=[],multiline=[],smallTargets=[],paddingVariance=[];const containers=[...root.querySelectorAll('.ui-container,.ui-card,.ui-list')];for(const parent of containers){const children=[...parent.children].filter(child=>child.classList.contains('ui-node')&&visibleElement(child)&&!['absolute','fixed'].includes(view.getComputedStyle(child).position));for(let i=0;i<children.length;i++)for(let j=i+1;j<children.length;j++){const area=rectOverlap(children[i].getBoundingClientRect(),children[j].getBoundingClientRect(),1);if(area>2)overlaps.push([children[i],children[j],area])}const buttons=children.filter(child=>child.matches('.ui-button'));if(buttons.length>1){const measures=buttons.map(button=>{const style=view.getComputedStyle(button);return {button,height:button.offsetHeight,pt:parseFloat(style.paddingTop)||0,pb:parseFloat(style.paddingBottom)||0}}),heights=measures.map(value=>value.height),vertical=measures.map(value=>value.pt+value.pb);if(Math.max(...heights)-Math.min(...heights)>1||Math.max(...vertical)-Math.min(...vertical)>1)paddingVariance.push(...buttons)}}for(const el of root.querySelectorAll('.ui-text,.ui-button')){if(!visibleElement(el))continue;const style=view.getComputedStyle(el),clipsX=el.scrollWidth>el.clientWidth+1&&!['auto','scroll'].includes(style.overflowX),clipsY=el.scrollHeight>el.clientHeight+1&&!['auto','scroll'].includes(style.overflowY);if(clipsX||clipsY)overflow.push(el);if(el.matches('.ui-button')&&el.offsetHeight<=44&&textLineCount(el)>1)multiline.push(el)}const screenVp=viewportFor(screen),minimum=screenVp.device==='phone'?44:32;for(const el of root.querySelectorAll('.ui-button,.ui-input,[data-action]')){if(!visibleElement(el))continue;const rect=el.getBoundingClientRect();if(rect.width+1<minimum||rect.height+1<minimum)smallTargets.push(el)}return {overlaps,overflow,multiline,smallTargets,paddingVariance,minimum}}
function inspectWorkbenchGeometry(doc=document){const controls=[...doc.querySelectorAll('.canvas-tools button,.menu-bar summary,.header-panel-button,.rail-button')].filter(visibleElement),multiline=controls.filter(control=>(control.textContent?.trim().length||0)>2&&textLineCount(control)>1),small=controls.filter(control=>{const rect=control.getBoundingClientRect();return rect.width<28||rect.height<28}),groups=[...doc.querySelectorAll('.mode-switch,.interaction-switch')],misaligned=[];for(const group of groups){const items=[...group.querySelectorAll(':scope>button')].filter(visibleElement);if(items.length<2)continue;const rects=items.map(item=>item.getBoundingClientRect()),tops=rects.map(rect=>rect.top),heights=rects.map(rect=>rect.height);if(Math.max(...tops)-Math.min(...tops)>1||Math.max(...heights)-Math.min(...heights)>1)misaligned.push(...items)}return {multiline,small,misaligned}}
async function runLayoutDiagnostic(results,scenario){for(const profile of diagnosticProfiles())await withDiagnosticProfile(profile,async({win,doc})=>{const api=win.__uiPreviewDiagnostics;for(const screen of screens){api.apply({view:'single',screen:screen.id,zoom:1});await nextPaintIn(win);const root=doc.querySelector('.stage>.device .device-content');if(!root){diagnosticCheck(results,scenario.id,'fail',`Макет · ${screen.name} · ${profile.label}`,'Корневой контейнер экрана не найден.',{profileId:profile.id,viewport:profile.viewport},screen.id,'high');continue}const report=inspectLayoutRoot(root,screen),fail=report.overlaps.length||report.overflow.length||report.multiline.length,warning=report.smallTargets.length||report.paddingVariance.length,result=fail?'fail':warning?'warning':'pass';diagnosticCheck(results,scenario.id,result,`Макет · ${screen.name} · ${profile.label}`,result==='pass'?'Пересечений, обрезки, случайных переносов и нестабильных целей не найдено.':`Пересечения ${report.overlaps.length}; обрезка ${report.overflow.length}; переносы в компактных кнопках ${report.multiline.length}; малые цели ${report.smallTargets.length}; разный padding/высота ${report.paddingVariance.length}.`,{profileId:profile.id,viewport:profile.viewport,overlaps:report.overlaps.map(pair=>pair.slice(0,2).map(nodeLabel)),overflow:report.overflow.map(nodeLabel),multiline:report.multiline.map(nodeLabel),smallTargets:report.smallTargets.map(nodeLabel),paddingVariance:report.paddingVariance.map(nodeLabel),minimumTarget:report.minimum},screen.id,fail?'high':'medium')}const chrome=inspectWorkbenchGeometry(doc),chromeFail=chrome.multiline.length||chrome.misaligned.length,result=chromeFail?'fail':chrome.small.length?'warning':'pass';diagnosticCheck(results,scenario.id,result,`Геометрия панели инструментов · ${profile.label}`,result==='pass'?'Контролы выровнены, подписи не переносятся, минимальные размеры соблюдены.':`Переносы ${chrome.multiline.length}; смещение уровней ${chrome.misaligned.length}; цели меньше 28px ${chrome.small.length}.`,{profileId:profile.id,viewport:profile.viewport,multiline:chrome.multiline.map(nodeLabel),misaligned:chrome.misaligned.map(nodeLabel),small:chrome.small.map(nodeLabel)},null,chromeFail?'high':'medium')})}
async function runAccessibilityDiagnostic(results,scenario){for(const profile of diagnosticProfiles())await withDiagnosticProfile(profile,async({win,doc})=>{const api=win.__uiPreviewDiagnostics;for(const screen of screens){api.apply({view:'single',screen:screen.id,zoom:1});await nextPaintIn(win);const root=doc.querySelector('.stage>.device .device-content');if(!root)continue;const candidates=[...root.querySelectorAll('button,input,select,textarea,[role="button"],[data-action]')].filter(visibleElement),unnamed=[],symbolic=[];for(const el of candidates){const name=accessibleName(el);if(!name)unnamed.push(el);else if(!el.getAttribute('aria-label')&&!el.getAttribute('title')&&/^[\s‹›⌗+−×✓↺⇩{}◫⌖▶◇·]+$/u.test(name))symbolic.push(el)}const fail=unnamed.length||symbolic.length;diagnosticCheck(results,scenario.id,fail?'fail':'pass',`Доступные имена · ${screen.name} · ${profile.label}`,fail?`Без имени: ${compactList(unnamed)}; только неоднозначный символ: ${compactList(symbolic)}.`:'Интерактивные элементы имеют понятные доступные имена.',{profileId:profile.id,viewport:profile.viewport,candidates:candidates.length,unnamed:unnamed.map(nodeLabel),symbolic:symbolic.map(nodeLabel)},screen.id,fail?'high':'low')}})}
async function runStateMatrixDiagnostic(results,scenario){const cases=stateVariantCases();for(const profile of diagnosticProfiles())await withDiagnosticProfile(profile,async({win,doc})=>{const api=win.__uiPreviewDiagnostics;for(const item of cases){const screen=screens.find(value=>value.id===item.screenId);if(!screen)continue;api.apply({view:'single',screen:screen.id,zoom:1,nodeStates:{[item.nodeId]:item.stateName}});await nextPaintIn(win);const root=doc.querySelector('.stage>.device .device-content');if(!root){diagnosticCheck(results,scenario.id,'fail',`Состояние · ${screen.name} · ${item.stateName}`,'Корневой контейнер не найден.',{profileId:profile.id,stateNodeId:item.nodeId,stateName:item.stateName},screen.id,'high');continue}const report=inspectLayoutRoot(root,screen),fail=report.overlaps.length||report.overflow.length||report.multiline.length,warning=report.smallTargets.length||report.paddingVariance.length,result=fail?'fail':warning?'warning':'pass';diagnosticCheck(results,scenario.id,result,`Состояние · ${screen.name} · ${item.nodeId}:${item.stateName} · ${profile.label}`,result==='pass'?'Объявленный вариант состояния сохраняет геометрию и доступность целей.':`Пересечения ${report.overlaps.length}; обрезка ${report.overflow.length}; переносы ${report.multiline.length}; малые цели ${report.smallTargets.length}; нестабильные размеры ${report.paddingVariance.length}.`,{profileId:profile.id,viewport:profile.viewport,stateNodeId:item.nodeId,stateName:item.stateName,overlaps:report.overlaps.map(pair=>pair.slice(0,2).map(nodeLabel)),overflow:report.overflow.map(nodeLabel),multiline:report.multiline.map(nodeLabel),smallTargets:report.smallTargets.map(nodeLabel),paddingVariance:report.paddingVariance.map(nodeLabel)},screen.id,fail?'high':warning?'medium':'low')}})}
function runNavigationFlowDiagnostic(results,scenario){const targetScreens=reviewScopeScreens(),targetIds=new Set(targetScreens.map(item=>item.id)),edges=[],invalid=[];for(const screen of targetScreens)for(const nodeId of nodeIdsForScreen(screen)){const action=nodes[nodeId]?.action;if(action?.type!=='navigate')continue;const edge={from:screen.id,to:action.target,nodeId};edges.push(edge);if(!screens.some(item=>item.id===action.target))invalid.push(edge)}const start=targetScreens[0]?.id,visited=new Set(start?[start]:[]),queue=start?[start]:[];while(queue.length){const from=queue.shift();for(const edge of edges.filter(item=>item.from===from)){if(!targetIds.has(edge.to)||visited.has(edge.to))continue;visited.add(edge.to);queue.push(edge.to)}}const unreachable=targetScreens.filter(item=>!visited.has(item.id)).map(item=>item.id),result=invalid.length?'fail':unreachable.length?'warning':'pass';diagnosticCheck(results,scenario.id,result,'Граф пользовательских переходов',result==='pass'?`Все ${targetScreens.length} экранов достижимы по объявленным переходам.`:`Некорректных целей: ${invalid.length}; недостижимых экранов в области: ${unreachable.length}.`,{edges,invalid,unreachable,startScreenId:start,scope:state.reviewScope},null,invalid.length?'high':unreachable.length?'medium':'low')}
function parseRgb(value){const match=String(value||'').match(/rgba?\((\d+(?:\.\d+)?)[, ]+(\d+(?:\.\d+)?)[, ]+(\d+(?:\.\d+)?)(?:[, /]+([\d.]+))?/);return match?{r:Number(match[1]),g:Number(match[2]),b:Number(match[3]),a:match[4]==null?1:Number(match[4])}:null}
function relativeLuminance(color){const channel=value=>{value/=255;return value<=.03928?value/12.92:Math.pow((value+.055)/1.055,2.4)};return .2126*channel(color.r)+.7152*channel(color.g)+.0722*channel(color.b)}
function contrastRatio(a,b){const first=relativeLuminance(a),second=relativeLuminance(b);return (Math.max(first,second)+.05)/(Math.min(first,second)+.05)}
function elementBackground(el){let current=el;while(current){const color=parseRgb(current.ownerDocument.defaultView.getComputedStyle(current).backgroundColor);if(color&&color.a>.01)return color;current=current.parentElement}return {r:255,g:255,b:255,a:1}}
async function runContrastFocusDiagnostic(results,scenario){for(const profile of diagnosticProfiles())await withDiagnosticProfile(profile,async({win,doc})=>{const api=win.__uiPreviewDiagnostics;for(const screen of reviewScopeScreens()){api.apply({view:'single',screen:screen.id,zoom:1,nodeStates:{}});await nextPaintIn(win);const root=doc.querySelector('.stage>.device .device-content');if(!root)continue;const lowContrast=[];for(const el of root.querySelectorAll('.ui-text,.ui-button,.ui-input')){if(!visibleElement(el)||!el.textContent?.trim()&&el.tagName!=='INPUT')continue;const style=win.getComputedStyle(el),foreground=parseRgb(style.color),background=elementBackground(el);if(!foreground)continue;const ratio=contrastRatio(foreground,background),large=parseFloat(style.fontSize)>=18||(parseFloat(style.fontSize)>=14&&Number(style.fontWeight)>=700),minimum=large?3:4.5;if(ratio+0.05<minimum)lowContrast.push(`${nodeLabel(el)}:${ratio.toFixed(2)}`)}const controls=[...root.querySelectorAll('button,input,select,textarea,[data-action]')].filter(visibleElement),untabbable=controls.filter(el=>el.tabIndex<0&&!el.disabled),fail=lowContrast.length||untabbable.length;diagnosticCheck(results,scenario.id,fail?'fail':'pass',`Контраст и клавиатура · ${screen.name} · ${profile.label}`,fail?`Недостаточный контраст: ${lowContrast.slice(0,5).join(', ')||'0'}; недоступны по Tab: ${compactList(untabbable)||'0'}.`:'Текст проходит вычисляемый контраст, интерактивные элементы доступны по Tab.',{profileId:profile.id,viewport:profile.viewport,lowContrast,untabbable:untabbable.map(nodeLabel),controls:controls.length},screen.id,fail?'high':'low')}})}
async function runDiagnostics(){if(state.diagnosticsRunning)return;const snapshot={interaction:state.interaction,view:state.view,screen:state.screen,nodeStates:{...state.nodeStates},activeVersion:state.activeVersion,compareMode:state.compareMode,overlayPosition:state.overlayPosition,zoomMode:state.zoomMode,zoom:state.zoom,selectedNodeId:state.selectedNodeId,selectedScreenId:state.selectedScreenId,focusedFindingId:state.focusedFindingId,diagnosticTargetIds:[...state.diagnosticTargetIds],screenScrolls:JSON.parse(JSON.stringify(state.screenScrolls)),stageScroll:{...state.stageScroll}};const startedAt=new Date().toISOString(),results=[];state.diagnosticsRunning=true;state.diagnosticsProgress='Подготовка сценариев…';renderDiagnostics();renderCoverage();try{for(const scenario of diagnosticsConfig.scenarios||[]){setDiagnosticsProgress(`Проверка: ${scenario.label}`);try{if(scenario.kind==='zoom-reset')await runZoomResetDiagnostic(results,scenario);else if(scenario.kind==='overview-geometry')await runOverviewGeometryDiagnostic(results,scenario);else if(scenario.kind==='menu-exclusivity')await runMenuDiagnostic(results,scenario);else if(scenario.kind==='layout-integrity')await runLayoutDiagnostic(results,scenario);else if(scenario.kind==='accessibility-basics')await runAccessibilityDiagnostic(results,scenario);else if(scenario.kind==='state-matrix')await runStateMatrixDiagnostic(results,scenario);else if(scenario.kind==='navigation-flow')runNavigationFlowDiagnostic(results,scenario);else if(scenario.kind==='contrast-focus')await runContrastFocusDiagnostic(results,scenario)}catch(error){diagnosticCheck(results,scenario.id,'fail',scenario.label,`Сценарий завершился ошибкой: ${error?.message||error}.`,{stack:String(error?.stack||'')},null,'high')}}}finally{Object.assign(state,snapshot);state.diagnosticsRunning=false;state.diagnosticsProgress='';state.diagnostics={version:2,status:'complete',startedAt,completedAt:new Date().toISOString(),activeVersion:state.activeVersion,scope:state.reviewScope,screenIds:reviewScopeScreens().map(item=>item.id),profiles:diagnosticsConfig.profiles||[],scenarios:diagnosticsConfig.scenarios||[],summary:{pass:results.filter(item=>item.result==='pass').length,warning:results.filter(item=>item.result==='warning').length,fail:results.filter(item=>item.result==='fail').length},checks:results};writeLocation(false);renderView();persist();renderDiagnostics();renderCoverage();showToast(`Диагностика завершена: ошибок ${state.diagnostics.summary.fail}, предупреждений ${state.diagnostics.summary.warning}`)}}
function showAuditFindings(ids){state.findingFocus=ids.filter(id=>findings.some(item=>item.id===id));state.findingFilter='linked';persist();renderFindings();$('.automated-review')?.scrollIntoView({block:'start',behavior:'smooth'})}
function acceptFindings(ids){for(const id of ids)if(findings.some(item=>item.id===id))state.findingDecisions[id]='accepted';persist();renderFindings();renderFixQueue();showToast(`В исправление добавлено: ${ids.length}`)}
function clearFindingFocus(){state.findingFocus=[];state.findingFilter='all';persist();renderFindings()}
function renderFindings(){const summary=$('.audit-summary'),list=$('.finding-list'),filters=$('.finding-filters'),context=$('.finding-context');document.querySelectorAll('.finding-total').forEach(total=>total.textContent=String(findings.length));if(!list)return;addFindingBadges();if(!findings.length){summary.innerHTML='<span>Проблем пока нет.</span>';filters.hidden=true;context.hidden=true;list.innerHTML='';renderFixQueue();return}filters.hidden=false;const counts={blocker:0,high:0,medium:0,low:0};for(const item of findings)counts[item.severity]=(counts[item.severity]||0)+1;const gaps=Array.isArray(expertAudit.validationGaps)?expertAudit.validationGaps:[];summary.innerHTML=`<div>${esc(expertAudit.summary||'Ревью завершено.')}</div><div class="audit-counts"><span class="audit-count">Блокеры ${counts.blocker}</span><span class="audit-count">Высокие ${counts.high}</span><span class="audit-count">Средние ${counts.medium}</span><span class="audit-count">Низкие ${counts.low}</span></div>${auditDepthMarkup()}${gaps.length?`<details class="audit-gaps"><summary>Нужно проверить · ${gaps.length}</summary><ul>${gaps.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></details>`:''}`;summary.querySelectorAll('[data-audit-findings]').forEach(button=>button.addEventListener('click',()=>showAuditFindings(button.dataset.auditFindings.split(',').filter(Boolean))));summary.querySelectorAll('[data-accept-findings]').forEach(button=>button.addEventListener('click',()=>acceptFindings(button.dataset.acceptFindings.split(',').filter(Boolean))));const focused=state.findingFocus.filter(id=>findings.some(item=>item.id===id));context.hidden=!focused.length;if(focused.length)context.innerHTML=`<span>Выбранный блок · ${focused.length}</span><button type="button">Сбросить</button>`;context.querySelector('button')?.addEventListener('click',clearFindingFocus);document.querySelectorAll('.finding-filter').forEach(button=>button.setAttribute('aria-pressed',String(!focused.length&&button.dataset.findingFilter===state.findingFilter)));let visible;if(focused.length)visible=findings.filter(item=>focused.includes(item.id));else if(state.findingFilter==='accepted')visible=findings.filter(item=>state.findingDecisions[item.id]==='accepted');else if(state.findingFilter==='all')visible=[...findings];else visible=findings.filter(item=>item.severity===state.findingFilter);const decisionLabels={pending:'Не выбрано',accepted:'В исправление',rejected:'Не исправлять',deferred:'Отложено'};list.innerHTML=visible.length?[...visible].sort((a,b)=>(findingRank[b.severity]||0)-(findingRank[a.severity]||0)).map(item=>{const decision=state.findingDecisions[item.id]||'pending',evidence=Array.isArray(item.evidence)?item.evidence:[],hasProposal=Boolean(item.proposalVersionId);return `<article class="finding-card" data-severity="${esc(item.severity)}" data-decision="${esc(decision)}"><div class="finding-card-header"><h3 class="finding-title">${esc(item.title)}</h3><span class="finding-severity">${esc(item.severity)}</span></div><div class="finding-meta">${esc(item.category)} · ${esc(item.confidence)} · ${esc(item.effort)}</div><span class="finding-decision-label">${esc(decisionLabels[decision]||decision)}</span><p class="finding-observation">${esc(item.observation)}</p><details class="finding-details"><summary>Влияние и решение</summary><p class="finding-impact"><b>Влияние:</b> ${esc(item.impact)}</p><p class="finding-recommendation"><b>Изменить:</b> ${esc(item.recommendation)}</p><div class="finding-proposal-note">${hasProposal?'Вариант готов для сравнения.':'Требуется новый вариант макета.'}</div><details class="finding-evidence"><summary>Основания · ${evidence.length}</summary><ul>${evidence.map(value=>`<li><b>${esc(value.ref)}</b> — ${esc(value.note)}</li>`).join('')}</ul></details></details><div class="finding-actions"><button type="button" class="finding-action" data-focus-finding="${esc(item.id)}">${iconMarkup('inspect')}Показать</button>${hasProposal?`<button type="button" class="finding-action primary" data-compare-finding="${esc(item.id)}">${iconMarkup('compare')}Сравнить</button>`:''}<button type="button" class="finding-action" data-finding-toggle="accepted" data-finding="${esc(item.id)}" aria-pressed="${decision==='accepted'}">${iconMarkup('check')}В исправление</button><button type="button" class="finding-action" data-finding-decision="rejected" data-finding="${esc(item.id)}" aria-pressed="${decision==='rejected'}">Не исправлять</button><button type="button" class="finding-action" data-finding-decision="deferred" data-finding="${esc(item.id)}" aria-pressed="${decision==='deferred'}">Позже</button></div></article>`}).join(''):'<div class="panel-empty compact"><strong>Здесь пока пусто</strong><span>Измените фильтр или выберите другой блок аудита.</span></div>';list.querySelectorAll('[data-focus-finding]').forEach(button=>button.addEventListener('click',()=>focusFinding(button.dataset.focusFinding)));list.querySelectorAll('[data-compare-finding]').forEach(button=>button.addEventListener('click',()=>focusFinding(button.dataset.compareFinding,true)));list.querySelectorAll('[data-finding-toggle]').forEach(button=>button.addEventListener('click',()=>setFindingDecision(button.dataset.finding,state.findingDecisions[button.dataset.finding]==='accepted'?'pending':'accepted')));list.querySelectorAll('[data-finding-decision]').forEach(button=>button.addEventListener('click',()=>setFindingDecision(button.dataset.finding,button.dataset.findingDecision)));renderFixQueue()}
function findingOrigin(item){if(item.runtimeDiagnosticId||item.runtimeDiagnosticIds?.length)return 'runtime';if(item.systemic)return 'systemic';return 'expert'}
function populateFindingScreenFilter(){const select=$('.finding-screen-select');if(!select)return;const current=state.findingScreen,available=[...new Set(findings.map(item=>item.screenId).filter(Boolean))];select.innerHTML='<option value="all">Все экраны</option>'+available.map(id=>`<option value="${esc(id)}">${esc(screens.find(item=>item.id===id)?.name||id)}</option>`).join('');select.value=available.includes(current)?current:'all';if(select.value!==current)state.findingScreen='all'}
function applyFindingExtraFilters(){populateFindingScreenFilter();const source=$('.finding-source-select'),screen=$('.finding-screen-select');if(source)source.value=state.findingSource;if(screen)screen.value=state.findingScreen;for(const card of document.querySelectorAll('.finding-card')){const id=card.querySelector('[data-finding]')?.dataset.finding||card.querySelector('[data-focus-finding]')?.dataset.focusFinding,item=findings.find(value=>value.id===id);if(!item)continue;const origin=findingOrigin(item),sourceMatch=state.findingSource==='all'||state.findingSource===origin||(state.findingSource==='systemic'&&item.systemic),screenMatch=state.findingScreen==='all'||item.screenId===state.findingScreen;card.hidden=!(sourceMatch&&screenMatch);card.dataset.origin=origin;const meta=card.querySelector('.finding-meta');if(meta&&!meta.querySelector('.finding-origin'))meta.insertAdjacentHTML('afterbegin',`<span class="finding-origin">${origin==='runtime'?'Автопроверка':origin==='systemic'?'Системная':'Эксперт'} · </span>`)}renderReviewNextAction()}
function visibleFindingIds(){return [...document.querySelectorAll('.finding-card:not([hidden])')].map(card=>card.querySelector('[data-finding]')?.dataset.finding).filter(Boolean)}
function acceptVisibleFindings(){const ids=visibleFindingIds();for(const id of ids)state.findingDecisions[id]='accepted';persist();renderFindings();showToast(`В исправление добавлено: ${ids.length}`)}
function clearVisibleFindingDecisions(){for(const id of visibleFindingIds())state.findingDecisions[id]='pending';persist();renderFindings();showToast('Выбор видимых проблем снят')}
function setAnnotationStatus(id,status){const item=state.annotations.find(a=>a.id===id);if(!item)return;item.status=status;item.updatedAt=new Date().toISOString();persist();renderQueue()}
function focusAnnotation(id){const item=state.annotations.find(a=>a.id===id);if(!item)return;setInspectorTab('comments');setScreen(item.screenId,'single');requestAnimationFrame(()=>{const el=document.querySelector(`[data-node-id="${CSS.escape(item.nodeId)}"]`);if(el){state.interaction='comment';syncInteractionButtons();selectNode(el);el.scrollIntoView({block:'center',inline:'center'})}})}
function renderQueue(){const list=$('.annotation-list'),decision=$('.review-decision');document.querySelectorAll('.annotation-total').forEach(total=>total.textContent=String(state.annotations.length));if(!list)return;const decisions={pending:'Решение по версии не принято',accepted:'Версия принята',rejected:'Версия требует доработки'};decision.textContent=decisions[state.versionDecision]||state.versionDecision;decision.className=`review-decision ${state.versionDecision}`;list.innerHTML=state.annotations.length?state.annotations.map(item=>`<article class="annotation-card" data-status="${esc(item.status||'new')}"><div class="annotation-meta"><span>${esc(item.priority||'medium')}</span><span>${esc(item.status||'new')}</span></div><p class="annotation-text">${esc(item.text)}</p><button class="annotation-target" data-focus-annotation="${esc(item.id)}">${esc(item.screenId||'экран')} · ${esc(item.nodeId||'общее')}</button><div class="annotation-controls"><button class="annotation-status" data-annotation="${esc(item.id)}" data-status="in-progress">В работе</button><button class="annotation-status" data-annotation="${esc(item.id)}" data-status="accepted">Принять</button><button class="annotation-status" data-annotation="${esc(item.id)}" data-status="rejected">Отклонить</button><button class="annotation-status" data-annotation="${esc(item.id)}" data-status="resolved">Решено</button></div></article>`).join(''):'<div class="panel-empty compact"><strong>Комментариев нет</strong><span>Выберите инструмент комментариев и нажмите элемент на холсте.</span></div>';list.querySelectorAll('[data-annotation]').forEach(button=>button.addEventListener('click',()=>setAnnotationStatus(button.dataset.annotation,button.dataset.status)));list.querySelectorAll('[data-focus-annotation]').forEach(button=>button.addEventListener('click',()=>focusAnnotation(button.dataset.focusAnnotation)))}
function feedbackPayload(){return {version:2,sessionId:review.sessionId||'default',revision:reviewRevision,baselineVersion,activeVersion:state.activeVersion,versionDecision:state.versionDecision,findingDecisions:state.findingDecisions,runtimeFindings:state.runtimeFindings,annotations:state.annotations,diagnostics:state.diagnostics,reviewRuns:state.reviewRuns,importedReview:state.importedReview,exportedAt:new Date().toISOString()}}
function fixRequestPayload(){const selected=selectedFindings();return {version:2,type:'ui-code-preview-fix-request',sessionId:review.sessionId||'default',revision:reviewRevision,project:ir.project?.name||'Project',baselineVersion,activeVersion:state.activeVersion,variantCount:2,acceptedFindingIds:selected.map(item=>item.id),existingProposalVersionIds:[...new Set(selected.map(item=>item.proposalVersionId).filter(Boolean))],findings:selected.map(item=>({id:item.id,title:item.title,category:item.category,severity:item.severity,screenId:item.screenId,nodeId:item.nodeId||null,observation:item.observation,impact:item.impact,recommendation:item.recommendation,effort:item.effort,proposalVersionId:item.proposalVersionId||null,decisionId:item.decisionId||null,runtimeDiagnosticId:item.runtimeDiagnosticId||null})),requestedAction:'Merge this review state into the IR, create up to two meaningfully different sparse HTML proposal versions for accepted findings, preserve the immutable baseline, rerun deterministic checks, render Before/After, and do not modify application source.',reviewFeedback:feedbackPayload(),createdAt:new Date().toISOString()}}
function sourceRequestPayload(){return {version:1,type:'ui-code-preview-source-request',sessionId:review.sessionId||'default',revision:reviewRevision,project:ir.project?.name||'Project',approvedVersionId:state.activeVersion,versionDecision:state.versionDecision,requiresExplicitSourceApproval:true,requestedAction:'Prepare a source-code implementation plan for the approved UI proposal. Do not modify source until the user explicitly approves the listed files and diff.',reviewFeedback:feedbackPayload(),createdAt:new Date().toISOString()}}
function expertReviewRequestPayload(){return {version:3,type:'ui-code-preview-expert-review-request',sessionId:review.sessionId||'default',revision:reviewRevision,project:ir.project?.name||'Project',activeVersion:state.activeVersion,scope:state.reviewScope,screenIds:reviewScopeScreens().map(screen=>screen.id),variantCount:2,requestedAction:'Perform a deep evidence-based UI and UX review of every included screen, declared state, navigation flow, and platform constraint. Reconcile runtime diagnostics with existing findings, group systemic causes, and return up to two meaningfully different corrected Before/After proposal versions without changing application source.',expectedResult:{type:'ui-code-preview-expert-review-result',requestRevision:reviewRevision,fields:['summary','findings','versions','resolvedFindingIds'],sourceChangeAllowed:false},runtimeDiagnostics:state.diagnostics,reviewRuns:state.reviewRuns,existingFindings:findings.map(item=>({...item,decision:state.findingDecisions[item.id]||'pending'})),uiIr:ir,createdAt:new Date().toISOString()}}
function renderCompareVersionOptions(){for(const select of document.querySelectorAll('.compare-version-select')){const value=select.classList.contains('compare-base-select')?state.compareBaseVersion:state.compareTargetVersion;select.innerHTML=versions.map(version=>`<option value="${esc(version.id)}">${esc(version.label||version.id)}</option>`).join('');select.value=versionById[value]?value:(select.classList.contains('compare-base-select')?baselineVersion:state.activeVersion)}}
function addVersionToWorkbench(version){if(!version?.id||versionById[version.id])return false;const parent=version.parent||baselineVersion;if(parent&&!versionById[parent])throw new Error(`Неизвестная родительская версия: ${parent}`);const normalized={...version,parent,kind:version.kind||'proposal',status:version.status||'proposal',nodeOverrides:version.nodeOverrides||{}};versions.push(normalized);versionById[normalized.id]=normalized;const option=document.createElement('option');option.value=normalized.id;option.textContent=normalized.label||normalized.id;versionSelect.append(option);renderCompareVersionOptions();return true}
function importExpertReviewData(payload){if(!payload||typeof payload!=='object')throw new Error('JSON не содержит объект результата');const incomingIr=payload.uiIr||payload.result?.uiIr||(payload.screens&&payload.nodes?payload:null),incomingReview=incomingIr?.review||payload.review||payload.result?.review||{},requestRevision=payload.requestRevision||payload.result?.requestRevision;if(requestRevision&&requestRevision!==reviewRevision)throw new Error('Результат создан для другой ревизии макета');const projectName=incomingIr?.project?.name||payload.project;if(projectName&&ir.project?.name&&projectName!==ir.project.name)throw new Error('Результат относится к другому проекту');if(incomingIr?.nodes)Object.assign(nodes,incomingIr.nodes);const incomingVersions=payload.versions||payload.result?.versions||incomingReview.versions||[],incomingFindings=payload.findings||payload.result?.findings||incomingReview.audit?.findings||[];let addedVersions=0,addedFindings=0,updatedFindings=0;for(const version of incomingVersions)if(addVersionToWorkbench(version))addedVersions+=1;for(const finding of incomingFindings){if(!finding?.id||!finding.title||!finding.screenId)continue;const existing=findings.find(item=>item.id===finding.id);if(existing){Object.assign(existing,finding,{origin:'expert-import'});updatedFindings+=1}else{state.runtimeFindings.push({...finding,origin:'expert-import'});addedFindings+=1}}for(const id of payload.resolvedFindingIds||payload.result?.resolvedFindingIds||[])if(findings.some(item=>item.id===id))state.findingDecisions[id]='resolved';const latestProposal=[...versions].reverse().find(item=>item.kind==='proposal'&&incomingVersions.some(value=>value.id===item.id));if(latestProposal){state.activeVersion=latestProposal.id;state.compareTargetVersion=latestProposal.id;versionSelect.value=latestProposal.id;state.versionDecision='pending';renderCompareVersionOptions()}state.importedReview={type:payload.type||'ui-code-preview-expert-review-result',summary:payload.summary||payload.result?.summary||incomingReview.audit?.summary||'Результат импортирован',addedVersions,addedFindings,updatedFindings,importedAt:new Date().toISOString(),requestRevision:requestRevision||null};state.reviewRuns.push({id:`import-${Date.now()}`,createdAt:new Date().toISOString(),sessionName:state.reviewSessionName,scope:state.reviewScope,scopeLabel:'Импорт Codex',screenIds:reviewScopeScreens().map(item=>item.id),checks:state.diagnostics?.checks?.length||0,stateCases:(state.diagnostics?.checks||[]).filter(item=>item.scenarioId==='state-matrix').length,issues:incomingFindings.length,summary:{imported:true}});state.reviewRuns=state.reviewRuns.slice(-20);persist();renderView();renderReviewHistory();renderImportStatus();setReviewSection('changes');showToast(`Импортировано: вариантов ${addedVersions}, проблем ${addedFindings}, обновлено ${updatedFindings}`)}
async function importExpertReviewFile(file){if(!file)return;const status=$('.import-review-status');try{if(status)status.textContent='Проверяем файл…';const payload=JSON.parse(await file.text());importExpertReviewData(payload)}catch(error){if(status)status.textContent=error?.message||String(error);showToast(`Импорт не выполнен: ${error?.message||error}`)}}
function renderImportStatus(){const badge=$('.import-review-badge'),status=$('.import-review-status'),value=state.importedReview;if(badge)badge.textContent=value?'импортирован':'не импортирован';if(status)status.textContent=value?`${value.summary} · вариантов ${value.addedVersions}, новых проблем ${value.addedFindings}, обновлено ${value.updatedFindings}`:''}
function downloadJson(filename,payload){const blob=new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function downloadFeedback(){const blob=new Blob([JSON.stringify(feedbackPayload(),null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='ui-review-feedback.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function syncInteractionButtons(){document.querySelectorAll('[data-interaction]').forEach(item=>item.setAttribute('aria-pressed',String(item.dataset.interaction===state.interaction)))}
function syncRailBadges(){document.querySelectorAll('.rail-badge').forEach(badge=>badge.hidden=badge.textContent.trim()==='0')}
const railBadgeObserver=new MutationObserver(syncRailBadges);document.querySelectorAll('.rail-badge').forEach(badge=>railBadgeObserver.observe(badge,{childList:true,characterData:true,subtree:true}));syncRailBadges();
window.__uiPreviewDiagnostics={apply(options={}){if(options.view)state.view=options.view;if(options.screen&&screens.some(screen=>screen.id===options.screen))state.screen=options.screen;if(options.nodeStates&&typeof options.nodeStates==='object')state.nodeStates={...options.nodeStates};if(options.zoom!==undefined){state.zoomMode='manual';state.zoom=clampZoom(Number(options.zoom)||1)}renderView()},report(){return state.diagnostics},codexHandoff(kind='expert'){return codexTaskDescriptor(kind)}};
renderScreenTree();bindWorkbenchMenus();$('.screen-search')?.addEventListener('input',event=>filterScreenTree(event.currentTarget.value));document.querySelectorAll('[data-inspector-tab]').forEach(button=>button.addEventListener('click',()=>setInspectorTab(button.dataset.inspectorTab)));document.querySelectorAll('[data-interaction]').forEach(button=>button.addEventListener('click',()=>{state.interaction=button.dataset.interaction;if(state.interaction==='inspect')setInspectorTab('inspect');if(state.interaction==='comment')setInspectorTab('comments');syncInteractionButtons();renderView()}));document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{closeWorkbenchMenus();setView(button.dataset.view)}));document.querySelectorAll('[data-compare-mode]').forEach(button=>button.addEventListener('click',()=>{state.compareMode=button.dataset.compareMode;persist();setView('compare')}));document.querySelectorAll('[data-finding-filter]').forEach(button=>button.addEventListener('click',()=>{state.findingFocus=[];state.findingFilter=button.dataset.findingFilter;persist();renderFindings()}));document.querySelectorAll('.sidebar-toggle').forEach(button=>button.addEventListener('click',()=>{const opening=!state.sidebarOpen;state.sidebarOpen=opening;if(opening&&innerWidth<=980)state.inspectorOpen=false;persist();applyPanelState();requestAnimationFrame(()=>renderView())}));document.querySelectorAll('.inspector-toggle').forEach(button=>button.addEventListener('click',()=>{const opening=!state.inspectorOpen;state.inspectorOpen=opening;if(opening&&innerWidth<=980)state.sidebarOpen=false;persist();applyPanelState();requestAnimationFrame(()=>renderView())}));document.querySelectorAll('.panel-resizer').forEach(bindResizer);
document.querySelectorAll('[data-zoom=out]').forEach(button=>button.addEventListener('click',()=>setZoom(state.computedZoom-.1)));document.querySelectorAll('[data-zoom=in]').forEach(button=>button.addEventListener('click',()=>setZoom(state.computedZoom+.1)));document.querySelectorAll('[data-zoom=reset]').forEach(button=>button.addEventListener('click',()=>setZoom(1)));document.querySelectorAll('[data-zoom=fit]').forEach(button=>button.addEventListener('click',()=>{state.zoomMode='fit';persist();closeWorkbenchMenus();renderView()}));
const versionSelect=$('.version-select');for(const version of versions){const option=document.createElement('option');option.value=version.id;option.textContent=version.label||version.id;option.selected=version.id===state.activeVersion;versionSelect.append(option)}versionSelect.addEventListener('change',()=>{state.activeVersion=versionSelect.value;state.compareTargetVersion=state.activeVersion;persist();renderCompareVersionOptions();renderView()});renderCompareVersionOptions();$('.compare-base-select')?.addEventListener('change',event=>{state.compareBaseVersion=event.currentTarget.value;persist();renderView()});$('.compare-target-select')?.addEventListener('change',event=>{state.compareTargetVersion=event.currentTarget.value;state.activeVersion=event.currentTarget.value;versionSelect.value=state.activeVersion;persist();renderView()});
document.querySelectorAll('[data-version-decision=accepted]').forEach(button=>button.addEventListener('click',()=>{state.versionDecision='accepted';persist();renderQueue();renderFixQueue();showToast('Версия отмечена как принята')}));document.querySelectorAll('[data-version-decision=rejected]').forEach(button=>button.addEventListener('click',()=>{state.versionDecision='rejected';persist();renderQueue();renderFixQueue();showToast('Версия отправлена на доработку')}));document.querySelectorAll('.export-feedback').forEach(button=>button.addEventListener('click',downloadFeedback));document.querySelectorAll('.copy-feedback').forEach(button=>button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(feedbackPayload(),null,2));showToast('JSON скопирован')}catch(_){showToast('Не удалось скопировать JSON — используйте экспорт')}}));
$('.run-diagnostics')?.addEventListener('click',runAutomatedReview);$('.clear-diagnostics')?.addEventListener('click',()=>{state.diagnostics=null;state.diagnosticsProgress='';persist();renderDiagnostics();renderReviewLauncher();renderCoverage();renderReviewNextAction();showToast('Результаты диагностики очищены')});
$('.run-review')?.addEventListener('click',runAutomatedReview);document.querySelectorAll('.open-codex-review').forEach(button=>button.addEventListener('click',()=>{if(state.diagnostics)openCodexTask('expert')}));document.querySelectorAll('.export-review-request').forEach(button=>button.addEventListener('click',()=>{if(!state.diagnostics)return;downloadJson('ui-expert-review-request.json',expertReviewRequestPayload());showToast('JSON-задание для AI-ревью скачано')}));
$('.export-fix-request')?.addEventListener('click',()=>{if(!selectedFindings().length)return;downloadJson('ui-fix-request.json',fixRequestPayload());showToast('Задание для Codex подготовлено')});$('.copy-fix-request')?.addEventListener('click',async()=>{if(!selectedFindings().length)return;try{await navigator.clipboard.writeText(JSON.stringify(fixRequestPayload(),null,2));showToast('Задание для Codex скопировано')}catch(_){showToast('Не удалось скопировать — используйте загрузку файла')}});
$('.prepare-source-request')?.addEventListener('click',()=>{if(versionById[state.activeVersion]?.kind!=='proposal'||state.versionDecision!=='accepted')return;state.sourcePreparedVersionId=state.activeVersion;persist();renderFixQueue();downloadJson('ui-source-change-request.json',sourceRequestPayload());showToast('Подготовлен запрос на внедрение; изменение кода ещё не разрешено')});
$('.migrate-review-state')?.addEventListener('click',migrateReviewState);$('.discard-review-state')?.addEventListener('click',discardReviewState);
$('.open-fix-queue')?.addEventListener('click',()=>{setInspectorTab('review');setReviewSection('changes');const panel=$('.fix-queue');if(panel)panel.open=true;closeWorkbenchMenus()});
$('.open-diagnostics')?.addEventListener('click',()=>{setInspectorTab('review');setReviewSection('summary');const panel=$('.runtime-diagnostics');if(panel)panel.open=true;closeWorkbenchMenus()});
document.querySelectorAll('[data-review-section]').forEach(button=>button.addEventListener('click',()=>setReviewSection(button.dataset.reviewSection)));$('.review-scope-select')?.addEventListener('change',event=>{state.reviewScope=event.currentTarget.value;state.diagnostics=null;state.codexHandoff=null;persist();renderReviewLauncher();renderCoverage();renderReviewNextAction()});$('.finding-source-select')?.addEventListener('change',event=>{state.findingSource=event.currentTarget.value;persist();applyFindingExtraFilters()});$('.finding-screen-select')?.addEventListener('change',event=>{state.findingScreen=event.currentTarget.value;persist();applyFindingExtraFilters()});$('.accept-visible-findings')?.addEventListener('click',acceptVisibleFindings);$('.clear-finding-decisions')?.addEventListener('click',clearVisibleFindingDecisions);$('.history-clear')?.addEventListener('click',()=>{state.reviewRuns=[];persist();renderReviewHistory();showToast('История запусков очищена')});$('.review-next-action')?.addEventListener('click',handleReviewNextAction);$('.review-reject-action')?.addEventListener('click',rejectActiveVersion);$('.copy-codex-task')?.addEventListener('click',copyCodexTask);$('.refresh-preview')?.addEventListener('click',refreshPreview);$('.import-review-result')?.addEventListener('click',()=>$('.import-review-file')?.click());$('.import-review-file')?.addEventListener('change',event=>{const file=event.currentTarget.files?.[0];importExpertReviewFile(file);event.currentTarget.value=''});const findingListObserver=new MutationObserver(applyFindingExtraFilters);if($('.finding-list'))findingListObserver.observe($('.finding-list'),{childList:true});
$('.review-session-name')?.addEventListener('change',event=>{state.reviewSessionName=event.currentTarget.value.trim()||review.sessionId||'Ревью';persist();renderReviewHistory()});
renderReviewLauncher();renderReviewSections();renderCoverage();renderReviewHistory();renderImportStatus();renderCodexHandoff();
addEventListener('popstate',()=>{state.screen=currentFromLocation();state.view=viewFromLocation();renderView()});addEventListener('resize',()=>{if(innerWidth<=980&&state.sidebarOpen&&state.inspectorOpen){state.sidebarOpen=false;persist();applyPanelState();renderView()}});addEventListener('beforeunload',persist);if(innerWidth<=980&&state.sidebarOpen&&state.inspectorOpen)state.sidebarOpen=false;state.screen=currentFromLocation();state.view=viewFromLocation();writeLocation(false);syncInteractionButtons();renderView();if(new URL(location.href).searchParams.get('diagnostics')==='run')setTimeout(runDiagnostics,0);
"""


ICON_SPRITE = """
<svg class="icon-sprite" aria-hidden="true" focusable="false">
  <symbol id="icon-logo" viewBox="0 0 16 16"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><path d="M11.5 9v5M9 11.5h5"/></symbol>
  <symbol id="icon-screens" viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="9" rx="1.5"/><path d="M5 14h6M8 11.5V14"/></symbol>
  <symbol id="icon-grid" viewBox="0 0 16 16"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></symbol>
  <symbol id="icon-play" viewBox="0 0 16 16"><path d="m5 3 8 5-8 5V3Z"/></symbol>
  <symbol id="icon-frame" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/><path d="M5 2.5v11M11 2.5v11"/></symbol>
  <symbol id="icon-compare" viewBox="0 0 16 16"><rect x="2" y="2.5" width="5" height="11" rx="1"/><rect x="9" y="2.5" width="5" height="11" rx="1"/></symbol>
  <symbol id="icon-pointer" viewBox="0 0 16 16"><path d="m3 2 8.5 7H7.8L6 13.5 3 2Z"/></symbol>
  <symbol id="icon-inspect" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2"/></symbol>
  <symbol id="icon-comment" viewBox="0 0 16 16"><path d="M3 2.5h10a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H7l-3.5 2v-2H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1Z"/></symbol>
  <symbol id="icon-review" viewBox="0 0 16 16"><path d="M3 2.5h10v11H3z"/><path d="m5 6 1.2 1.2L8.5 5M5 10h6"/></symbol>
  <symbol id="icon-search" viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></symbol>
  <symbol id="icon-chevron-left" viewBox="0 0 16 16"><path d="m10 3-5 5 5 5"/></symbol>
  <symbol id="icon-chevron-right" viewBox="0 0 16 16"><path d="m6 3 5 5-5 5"/></symbol>
  <symbol id="icon-panel-left" viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M6 2.5v11"/></symbol>
  <symbol id="icon-panel-right" viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M10 2.5v11"/></symbol>
  <symbol id="icon-minus" viewBox="0 0 16 16"><path d="M3 8h10"/></symbol>
  <symbol id="icon-plus" viewBox="0 0 16 16"><path d="M3 8h10M8 3v10"/></symbol>
  <symbol id="icon-fit" viewBox="0 0 16 16"><path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4"/></symbol>
  <symbol id="icon-more" viewBox="0 0 16 16"><circle cx="3" cy="8" r="1"/><circle cx="8" cy="8" r="1"/><circle cx="13" cy="8" r="1"/></symbol>
  <symbol id="icon-activity" viewBox="0 0 16 16"><path d="M2 8h3l1.5-4 3 8L11 8h3"/></symbol>
  <symbol id="icon-check" viewBox="0 0 16 16"><path d="m3 8 3 3 7-7"/></symbol>
  <symbol id="icon-close" viewBox="0 0 16 16"><path d="m4 4 8 8M12 4l-8 8"/></symbol>
  <symbol id="icon-download" viewBox="0 0 16 16"><path d="M8 2v8M5 7l3 3 3-3M3 13h10"/></symbol>
<symbol id="icon-copy" viewBox="0 0 16 16"><rect x="5" y="5" width="8" height="8" rx="1"/><path d="M3 10H2V3a1 1 0 0 1 1-1h7v1"/></symbol>
<symbol id="icon-external" viewBox="0 0 16 16"><path d="M9 2h5v5M14 2 8 8"/><path d="M7 3H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V9"/></symbol>
<symbol id="icon-back" viewBox="0 0 16 16"><path d="M6.5 3 2 7.5 6.5 12M2.5 7.5H10a4 4 0 0 1 4 4"/></symbol>
</svg>
"""


def icon(name: str, class_name: str = "icon") -> str:
    return f'<svg class="{class_name}" aria-hidden="true"><use href="#icon-{name}"></use></svg>'


def render_html(ir: dict[str, Any], artifact_dir: Path | None = None) -> str:
    project = ir.get("project", {})
    screens = ir.get("screens", [])
    warnings = ir.get("warnings", [])
    audit = ir.get("fidelityAudit", {})
    font_faces: list[str] = []
    for font in ir.get("fonts", []):
        if not font.get("resolvedAsset") or not font.get("family"):
            continue
        family = str(font["family"]).replace("\\", "\\\\").replace("'", "\\'")
        weight = html.escape(str(font.get("weight", "400")), quote=True)
        font_style = html.escape(str(font.get("style", "normal")), quote=True)
        font_faces.append(
            f"@font-face{{font-family:'{family}';src:url('{font['resolvedAsset']}');"
            f"font-weight:{weight};font-style:{font_style};font-display:block}}"
        )
    font_css = "".join(font_faces)
    encoded_ir = json.dumps(ir, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    encoded_context = json.dumps(
        {"artifactDir": str(artifact_dir.resolve()) if artifact_dir else ""},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    screen_buttons = "".join(
        f'<button type="button" class="screen-link" data-screen="{html.escape(str(screen["id"]))}" aria-current="false">{html.escape(str(screen["name"]))}</button>'
        for screen in screens
    )
    warning_markup = ""
    if warnings:
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
        warning_markup = f'<details class="warning-panel"><summary>Warnings ({len(warnings)})</summary><ul>{items}</ul></details>'
    origin_label = "Source mapping" if audit.get("designMode") == "reconstruct" else "Decision evidence"
    origin_value = audit.get("sourceCoverage", 0) if audit.get("designMode") == "reconstruct" else audit.get("evidenceCoverage", 0)
    standards_markup = "" if audit.get("designMode") == "reconstruct" else (
        f'Standards: {audit.get("standardCoverage", 0):.0%} · Semantics: {audit.get("semanticCoverage", 0):.0%} · '
        f'Targets: {audit.get("targetCoverage", 0):.0%} · Contrast: {audit.get("contrastCoverage", 0):.0%} · '
        f'States: {audit.get("stateCoverage", 0):.0%}<br>'
    )
    audit_markup = (
        f'<details class="audit-panel"><summary>Проверка покрытия</summary><p class="audit">Mode: {html.escape(str(audit.get("designMode", "reconstruct")))}<br>'
        f'{origin_label}: {origin_value:.0%} · '
        f'Appearance: {audit.get("appearanceCoverage", 0):.0%} · '
        f'High confidence: {audit.get("highConfidenceCoverage", 0):.0%} · '
        f'Components: {audit.get("componentCoverage", 1):.0%} ({audit.get("catalogComponents", 0)} catalogued)<br>'
        f'{standards_markup}'
        f'Screens: {audit.get("screenCoverage", 0):.0%} · Routes: {audit.get("routeCoverage", 0):.0%} · '
        f'Menu targets: {audit.get("navigationCoverage", 1):.0%} · '
        f'Navigation actions: {audit.get("navigationActions", 0)}</p></details>'
    )
    title = f'{project.get("name", "Project")} UI Preview'
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{font_css}{CSS}{VIEW_CSS}{REVIEW_CSS}</style>
</head>
<body>
{ICON_SPRITE}
<div class="review-app">
  <nav class="workbench-rail" aria-label="Разделы рабочего пространства">
    <button type="button" class="rail-button sidebar-toggle" data-rail-panel="screens" aria-pressed="true" aria-label="Экраны" title="Экраны">{icon("screens")}</button>
    <div class="rail-divider"></div>
    <button type="button" class="rail-button" data-inspector-tab="inspect" aria-pressed="false" aria-label="Свойства выбранного элемента" title="Свойства">{icon("inspect")}</button>
    <button type="button" class="rail-button" data-inspector-tab="review" aria-pressed="true" aria-label="Ревью и исправления" title="Ревью">{icon("review")}<span class="rail-badge finding-total">0</span></button>
    <button type="button" class="rail-button" data-inspector-tab="comments" aria-pressed="false" aria-label="Комментарии" title="Комментарии">{icon("comment")}<span class="rail-badge annotation-total">0</span></button>
    <div class="rail-spacer"></div>
    <button type="button" class="rail-button inspector-toggle" aria-pressed="true" aria-label="Скрыть или показать правую панель" title="Правая панель">{icon("panel-right")}</button>
  </nav>
  <aside class="sidebar">
    <header class="side-panel-header"><div><span class="panel-kicker">Навигация</span><h1 class="side-panel-title">Экраны</h1></div><button type="button" class="panel-close sidebar-toggle" aria-label="Скрыть панель экранов" title="Скрыть панель">{icon("chevron-left")}</button></header>
    <div class="sidebar-project" title="{html.escape(str(project.get('name', 'Project')))}">{html.escape(str(project.get("name", "Project")))}</div>
    <label class="tree-search">{icon("search")}<input type="search" class="screen-search" placeholder="Найти экран" aria-label="Найти экран"></label>
    <nav class="screen-list" aria-label="Иерархия экранов"></nav>
    <footer class="sidebar-meta">{audit_markup}{warning_markup}</footer>
  </aside>
  <div class="panel-resizer left-resizer" data-resize="left" role="separator" aria-label="Изменить ширину дерева экранов" aria-orientation="vertical" tabindex="0"></div>
  <main class="workspace">
    <header class="workbench-header">
      <div class="menu-bar">
        <div class="app-mark">{icon("logo", "app-logo")}<span>UI Preview</span><span class="revision-badge" title="Ревизия макета"></span></div>
        <div class="menu-strip" aria-label="Главное меню">
          <details class="menu"><summary>Файл</summary><div class="menu-popover">
            <button type="button" class="export-feedback">Экспорт ревью</button><button type="button" class="copy-feedback">Копировать JSON</button>
          </div></details>
          <details class="menu"><summary>Вид</summary><div class="menu-popover">
            <button type="button" data-view="overview">Все экраны</button><button type="button" data-view="prototype">Прототип</button><button type="button" data-view="single">Один экран</button><button type="button" data-view="compare">Сравнение версий</button>
            <button type="button" class="sidebar-toggle" aria-pressed="true">Дерево экранов</button><button type="button" class="inspector-toggle" aria-pressed="true">Инспектор и ревью</button><button type="button" data-zoom="fit">Вписать макет в окно</button>
          </div></details>
          <details class="menu"><summary>Ревью</summary><div class="menu-popover">
            <button type="button" class="open-fix-queue">Подготовить исправления…</button><button type="button" class="open-diagnostics">Диагностика макета…</button><button type="button" data-version-decision="accepted">Принять версию</button><button type="button" data-version-decision="rejected">Запросить изменения</button><button type="button" class="export-feedback">Экспорт комментариев</button><button type="button" class="copy-feedback">Копировать JSON</button>
          </div></details>
        </div>
        <div class="screen-context"><div class="screen-title"></div><span class="navigation-preview-label" aria-live="polite"></span></div>
        <div class="menu-spacer"></div>
        <select class="version-select" aria-label="Активная версия макета"></select>
        <div class="mode-status" aria-live="polite">Макеты · переходы выключены</div>
        <button type="button" class="header-panel-button inspector-toggle" aria-pressed="true" aria-label="Скрыть или показать правую панель" title="Правая панель">{icon("panel-right")}</button>
      </div>
    </header>
    <section class="stage" aria-label="UI preview"></section>
    <div class="canvas-tools" aria-label="Инструменты холста">
      <div class="mode-switch" aria-label="Режим просмотра">
        <button type="button" class="mode-button" data-view="overview" aria-pressed="true" aria-label="Все экраны" title="Все экраны">{icon("grid")}<span class="button-label">Макеты</span></button>
        <button type="button" class="mode-button" data-view="prototype" aria-pressed="false" aria-label="Интерактивный прототип" title="Интерактивный прототип">{icon("play")}<span class="button-label">Прототип</span></button>
        <button type="button" class="mode-button" data-view="single" aria-pressed="false" aria-label="Один экран" title="Один экран">{icon("frame")}<span class="button-label">Экран</span></button>
        <button type="button" class="mode-button" data-view="compare" aria-pressed="false" aria-label="Сравнение версий" title="Сравнение версий">{icon("compare")}<span class="button-label">Сравнить</span></button>
      </div>
      <span class="tool-divider"></span>
      <div class="interaction-switch" aria-label="Инструмент">
        <button type="button" class="interaction-button" data-interaction="interact" aria-pressed="true" aria-label="Взаимодействовать с макетом" title="Взаимодействовать">{icon("pointer")}<span class="button-label">Клики</span></button>
        <button type="button" class="interaction-button" data-interaction="inspect" aria-pressed="false" aria-label="Инспектировать элемент" title="Инспектировать">{icon("inspect")}<span class="button-label">Свойства</span></button>
        <button type="button" class="interaction-button" data-interaction="comment" aria-pressed="false" aria-label="Добавить комментарий" title="Комментарий">{icon("comment")}<span class="button-label">Комментарий</span></button>
      </div>
    </div>
    <div class="compare-controls" aria-label="Режим сравнения"><select class="compare-version-select compare-base-select" aria-label="Первая версия"></select><span class="compare-version-arrow">→</span><select class="compare-version-select compare-target-select" aria-label="Вторая версия"></select><button type="button" class="compare-button" data-compare-mode="split">Рядом</button><button type="button" class="compare-button" data-compare-mode="overlay">Наложение</button></div>
    <div class="floating-zoom" aria-label="Масштаб макета" title="Колесо мыши масштабирует холст; двойной клик по разделителю сбрасывает ширину панели">
      <button type="button" class="zoom-button" data-zoom="out" aria-label="Уменьшить масштаб" title="Уменьшить">{icon("minus")}</button><button type="button" class="zoom-button zoom-label" data-zoom="reset" aria-label="Масштаб 100%" title="Сбросить масштаб">100%</button><button type="button" class="zoom-button" data-zoom="in" aria-label="Увеличить масштаб" title="Увеличить">{icon("plus")}</button><button type="button" class="zoom-button" data-zoom="fit" aria-label="Вписать макет" title="Вписать макет">{icon("fit")}</button>
    </div>
    <div class="workbench-toast" role="status" aria-live="polite"></div>
  </main>
  <div class="panel-resizer right-resizer" data-resize="right" role="separator" aria-label="Изменить ширину панели ревью" aria-orientation="vertical" tabindex="0"></div>
  <aside class="inspector">
    <header class="inspector-header">
      <nav class="inspector-tabs" aria-label="Правая панель">
        <button type="button" class="inspector-tab" data-inspector-tab="inspect" aria-pressed="false">Свойства</button>
        <button type="button" class="inspector-tab" data-inspector-tab="review" aria-pressed="true">Ревью <span class="finding-total">0</span></button>
        <button type="button" class="inspector-tab" data-inspector-tab="comments" aria-pressed="false">Комментарии <span class="annotation-total">0</span></button>
      </nav>
      <button type="button" class="panel-close inspector-toggle" aria-label="Скрыть правую панель" title="Скрыть панель">{icon("chevron-right")}</button>
    </header>
    <section class="inspector-pane" data-inspector-pane="inspect" hidden>
      <div class="pane-heading"><div><span class="panel-kicker">Выбранный элемент</span><h2>Свойства</h2></div></div>
      <div class="inspect-body"><div class="panel-empty">{icon("inspect", "empty-icon")}<strong>Выберите элемент</strong><span>Переключитесь на «Свойства» и нажмите элемент на холсте.</span></div></div>
    </section>
    <section class="inspector-pane" data-inspector-pane="review">
      <nav class="review-subtabs" aria-label="Разделы ревью"><button type="button" class="review-subtab" data-review-section="summary" aria-pressed="true">Сводка</button><button type="button" class="review-subtab" data-review-section="problems" aria-pressed="false">Проблемы <span class="review-subtab-count finding-total">0</span></button><button type="button" class="review-subtab" data-review-section="changes" aria-pressed="false">Изменения <span class="review-subtab-count fix-queue-count">0</span></button></nav>
      <div class="revision-notice" hidden><b>Доступна новая ревизия</b><div>Перенесите совместимые решения или начните чистое ревью.</div><div class="revision-notice-actions"><button type="button" class="migrate-review-state">Перенести</button><button type="button" class="discard-review-state">Сбросить</button></div></div>
      <section class="review-workspace" data-review-workspace="summary">
        <section class="review-launcher" data-state="idle" aria-label="Запуск ревью макетов">
          <div class="review-launcher-head"><span class="review-launcher-icon">{icon("activity")}</span><div><h2 class="review-launcher-title">Ревью макетов</h2><p class="review-launcher-meta"></p></div></div>
          <div class="review-scope-row"><span class="review-scope-label">Область проверки</span><select class="review-scope-select" aria-label="Область ревью"><option value="all">Все экраны</option><option value="current">Текущий экран</option></select></div>
          <div class="review-launcher-status" role="status" aria-live="polite"></div><div class="review-launcher-progress" aria-hidden="true"></div>
          <div class="review-launcher-actions with-handoff"><button type="button" class="review-launcher-action primary run-review">{icon("activity")}<span>Запустить ревью</span></button><button type="button" class="review-launcher-action open-codex-review" disabled>{icon("external")}<span>Открыть AI-ревью в Codex</span></button><button type="button" class="review-launcher-action icon-only export-review-request" disabled aria-label="Скачать JSON-задание" title="Скачать JSON-задание">{icon("download")}</button></div>
        </section>
        <section class="coverage-panel" aria-label="Покрытие ревью"><div class="coverage-head"><h3>Покрытие</h3><span class="coverage-status"></span></div><div class="coverage-body"></div></section>
        <section class="review-history" aria-label="История ревью"><div class="history-head"><h3>История запусков</h3><button type="button" class="history-clear">Очистить</button></div><input class="review-session-name" aria-label="Название сессии ревью" placeholder="Название сессии"><div class="review-history-list"></div></section>
        <details class="panel-section runtime-diagnostics">
          <summary><span>Технические результаты</span><span class="diagnostics-status">не запускалась</span></summary>
          <div class="diagnostics-body"><div class="diagnostics-actions"><button type="button" class="diagnostics-action primary run-diagnostics">{icon("activity")}Запустить</button><button type="button" class="diagnostics-action clear-diagnostics">Очистить</button></div><div class="diagnostics-progress" role="status" aria-live="polite"></div><div class="diagnostics-summary"></div><div class="diagnostics-results"></div></div>
        </details>
      </section>
      <section class="review-workspace automated-review" data-review-workspace="problems" aria-label="Проблемы" hidden>
        <div class="review-section-heading"><h2>Проблемы</h2><span class="finding-total">0</span></div><div class="audit-summary"></div>
        <div class="finding-toolbar"><select class="finding-select finding-source-select" aria-label="Источник проблемы"><option value="all">Все источники</option><option value="expert">Экспертный аудит</option><option value="runtime">Автопроверка</option><option value="systemic">Системные</option></select><select class="finding-select finding-screen-select" aria-label="Экран"><option value="all">Все экраны</option></select></div>
        <div class="finding-filters" aria-label="Фильтр замечаний"><button type="button" class="finding-filter" data-finding-filter="all" aria-pressed="true">Все</button><button type="button" class="finding-filter" data-finding-filter="accepted" aria-pressed="false">Выбрано</button><button type="button" class="finding-filter" data-finding-filter="blocker" aria-pressed="false">Блокеры</button><button type="button" class="finding-filter" data-finding-filter="high" aria-pressed="false">Высокие</button><button type="button" class="finding-filter" data-finding-filter="medium" aria-pressed="false">Средние</button><button type="button" class="finding-filter" data-finding-filter="low" aria-pressed="false">Низкие</button></div>
        <div class="finding-bulk"><button type="button" class="accept-visible-findings">Все видимые в исправление</button><button type="button" class="clear-finding-decisions">Снять выбор</button></div><div class="finding-context" hidden></div><div class="finding-list"></div>
      </section>
      <section class="review-workspace" data-review-workspace="changes" aria-label="Изменения" hidden>
        <details class="fix-queue" open><summary><span>План исправлений</span><span class="fix-queue-count">0</span></summary><div class="fix-queue-body"><div class="review-phases"><span class="review-phase" data-phase="findings">Проблемы</span><span class="review-phase" data-phase="selected">Выбрано</span><span class="review-phase" data-phase="proposal">Вариант</span><span class="review-phase" data-phase="approved">Принято</span><span class="review-phase" data-phase="source">Проект</span></div><div class="fix-queue-stats"></div><div class="fix-queue-actions"><button type="button" class="fix-queue-action copy-fix-request" disabled>{icon("copy")}Скопировать задание</button></div></div></details>
        <section class="codex-handoff-panel" hidden><div class="codex-handoff-head">{icon("external")}<span class="codex-handoff-status"></span></div><p class="codex-handoff-meta"></p><div class="codex-handoff-actions"><button type="button" class="codex-handoff-action copy-codex-task">Скопировать запрос</button><button type="button" class="codex-handoff-action refresh-preview">Обновить макет</button></div></section>
        <section class="import-review-panel"><div class="import-review-head"><h3>Результат Codex</h3><span class="import-review-badge">не импортирован</span></div><p class="import-review-copy">Задача Codex может пересобрать файлы макета напрямую. Ручной импорт JSON остаётся резервным способом.</p><div class="import-review-actions"><button type="button" class="import-review-action import-review-result">Импортировать JSON</button><button type="button" class="import-review-action export-review-request" disabled>Скачать задание</button></div><input type="file" class="import-review-file" accept="application/json,.json" hidden><div class="import-review-status" role="status"></div></section>
        <div class="review-decision">Ожидает решения</div>
      </section>
      <footer class="review-context-footer"><div class="review-context-status"></div><div class="review-context-actions"><button type="button" class="review-next-action">Запустить ревью</button><button type="button" class="review-secondary-action review-reject-action" hidden>На доработку</button><button type="button" class="review-secondary-action icon-only export-feedback" aria-label="Экспортировать ревью" title="Экспортировать">{icon("download")}</button></div></footer>
    </section>
    <section class="inspector-pane" data-inspector-pane="comments" hidden>
      <div class="pane-heading"><div><span class="panel-kicker">Обратная связь</span><h2>Комментарии</h2></div><span class="annotation-total">0</span></div>
      <div class="comment-composer"><div class="panel-empty compact">{icon("comment", "empty-icon")}<strong>Выберите элемент</strong><span>Комментарий будет привязан к выбранному узлу.</span></div></div>
      <div class="annotation-list"></div>
    </section>
  </aside>
</div>
<script id="ui-preview-context" type="application/json">{encoded_context}</script>
<script id="ui-ir-data" type="application/json">{encoded_ir}</script>
<script id="runtime-diagnostics-report" type="application/json">null</script>
<script>{JS}</script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render ui-ir.json to a standalone interactive HTML preview.")
    parser.add_argument("ir", type=Path, help="Path to ui-ir.json")
    parser.add_argument("--output", type=Path, required=True, help="Output HTML path")
    parser.add_argument("--allow-draft", action="store_true", help="Render inventory or incomplete IR for diagnostics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ir = json.loads(args.ir.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read IR: {exc}", file=sys.stderr)
        return 2
    errors = validate(ir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    audit = fidelity_audit(ir)
    if audit["status"] == "blocked" and not args.allow_draft:
        print("Preview blocked by fidelity audit:", file=sys.stderr)
        for reason in audit["reasons"]:
            print(f"- {reason}", file=sys.stderr)
        print("Translate the discovered UI from source or pass --allow-draft for diagnostics only.", file=sys.stderr)
        return 3
    ir["fidelityAudit"] = audit
    if audit["reasons"]:
        ir.setdefault("warnings", []).extend(audit["reasons"])
    rendered_ir = resolve_assets(ir)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(rendered_ir, output.parent), encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
