#!/usr/bin/env python3
"""Bounded agent context and safe sparse patches for UI Design Workbench IR."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


CONTEXT_TYPE = "ui-design-workbench-scoped-context"
PATCH_TYPE = "ui-design-workbench-ir-patch"
FORMAT_VERSION = 1
TOKEN_REF = re.compile(r"\$([A-Za-z0-9_.-]+)")


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def estimate_tokens(value: Any) -> int:
    """Return a conservative, dependency-free estimate for routing/budget metadata."""
    return max(1, (len(_compact(value).encode("utf-8")) + 3) // 4)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _ordered_findings(ir: dict[str, Any]) -> list[dict[str, Any]]:
    findings = ir.get("review", {}).get("audit", {}).get("findings", [])
    return [item for item in findings if isinstance(item, dict) and item.get("id")]


def _resolve_screens(ir: dict[str, Any], queries: list[str]) -> list[dict[str, Any]]:
    screens = [item for item in ir.get("screens", []) if isinstance(item, dict)]
    if not queries:
        return []
    normalized = {item.strip().lower() for item in queries if item.strip()}
    selected = [
        screen for screen in screens
        if str(screen.get("id", "")).lower() in normalized
        or str(screen.get("name", "")).lower() in normalized
    ]
    missing = normalized - {
        value
        for item in selected
        for value in (str(item.get("id", "")).lower(), str(item.get("name", "")).lower())
    }
    if missing:
        raise ValueError("Unknown screen(s): " + ", ".join(sorted(missing)))
    return selected


def _resolve_findings(ir: dict[str, Any], identifiers: list[str]) -> list[dict[str, Any]]:
    findings = _ordered_findings(ir)
    by_id = {str(item["id"]): item for item in findings}
    by_number = {str(index): item for index, item in enumerate(findings, 1)}
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for identifier in identifiers:
        item = by_id.get(identifier) or by_number.get(identifier)
        if item and item not in selected:
            selected.append(item)
        elif not item:
            missing.append(identifier)
    if missing:
        raise ValueError("Unknown finding(s): " + ", ".join(missing))
    return selected


def _node_ids_for_scope(
    ir: dict[str, Any], screens: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> set[str]:
    nodes = ir.get("nodes", {}) if isinstance(ir.get("nodes"), dict) else {}
    selected: set[str] = set()
    parents: dict[str, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for child in node.get("children", []):
            parents[str(child)] = str(node_id)

    def descendants(node_id: str) -> None:
        if node_id in selected or node_id not in nodes:
            return
        selected.add(node_id)
        node = nodes[node_id]
        if isinstance(node, dict):
            for child in node.get("children", []):
                descendants(str(child))

    for screen in screens:
        descendants(str(screen.get("root", "")))
    for finding in findings:
        node_id = str(finding.get("nodeId") or "")
        if node_id:
            descendants(node_id)
            while node_id in parents:
                node_id = parents[node_id]
                selected.add(node_id)
    return selected


def _source_files(items: list[dict[str, Any]]) -> list[str]:
    files: set[str] = set()
    for item in items:
        source = item.get("source")
        if isinstance(source, dict) and source.get("file"):
            files.add(str(source["file"]))
        for evidence in item.get("evidence", []):
            if isinstance(evidence, dict) and evidence.get("ref"):
                files.add(str(evidence["ref"]).split("#", 1)[0])
    return sorted(files)


def _token_refs(value: Any) -> set[str]:
    return set(TOKEN_REF.findall(_compact(value)))


def _lookup_token(tokens: dict[str, Any], path: str) -> Any:
    current: Any = tokens
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _set_token(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = path.split(".")
    for segment in parts[:-1]:
        current = current.setdefault(segment, {})
    current[parts[-1]] = copy.deepcopy(value)


def _relevant_tokens(ir: dict[str, Any], selected_nodes: dict[str, Any]) -> dict[str, Any]:
    tokens = ir.get("tokens", {}) if isinstance(ir.get("tokens"), dict) else {}
    return _select_tokens(tokens, _token_refs(selected_nodes))


def _select_tokens(tokens: dict[str, Any], refs: set[str]) -> dict[str, Any]:
    pending = list(refs)
    seen: set[str] = set()
    result: dict[str, Any] = {}
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        value = _lookup_token(tokens, ref)
        if value is None:
            continue
        _set_token(result, ref, value)
        pending.extend(_token_refs(value) - seen)
    return result


def _relevant_themes(ir: dict[str, Any], selected_nodes: dict[str, Any], node_ids: set[str]) -> dict[str, Any]:
    themes = ir.get("themes", {}) if isinstance(ir.get("themes"), dict) else {}
    refs = _token_refs(selected_nodes)
    items: list[dict[str, Any]] = []
    for item in themes.get("items", []) if isinstance(themes.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        selected = {key: copy.deepcopy(value) for key, value in item.items() if key in {"id", "label", "kind", "sourceRefs"}}
        token_overrides = item.get("tokenOverrides", {}) if isinstance(item.get("tokenOverrides"), dict) else {}
        node_overrides = item.get("nodeOverrides", {}) if isinstance(item.get("nodeOverrides"), dict) else {}
        relevant_tokens = _select_tokens(token_overrides, refs)
        relevant_nodes = {key: copy.deepcopy(value) for key, value in node_overrides.items() if str(key) in node_ids}
        if relevant_tokens:
            selected["tokenOverrides"] = relevant_tokens
        if relevant_nodes:
            selected["nodeOverrides"] = relevant_nodes
        items.append(selected)
    return {"defaultThemeId": themes.get("defaultThemeId"), "items": items}


def _relevant_fixtures(ir: dict[str, Any], screens: list[dict[str, Any]]) -> dict[str, Any]:
    fixtures = ir.get("scenarioFixtures", {}) if isinstance(ir.get("scenarioFixtures"), dict) else {}
    refs = {
        str(scenario.get("fixtureRef"))
        for screen in screens
        for scenario in screen.get("scenarios", [])
        if isinstance(scenario, dict) and scenario.get("fixtureRef")
    }
    return {key: copy.deepcopy(value) for key, value in fixtures.items() if str(key) in refs}


def _relevant_navigation(ir: dict[str, Any], screen_ids: set[str]) -> dict[str, Any]:
    graph = ir.get("navigationGraph", {}) if isinstance(ir.get("navigationGraph"), dict) else {}
    edges = [
        copy.deepcopy(item) for item in graph.get("edges", [])
        if isinstance(item, dict) and (str(item.get("from")) in screen_ids or str(item.get("to")) in screen_ids)
    ]
    targets = [
        copy.deepcopy(item) for item in graph.get("navigationTargets", [])
        if isinstance(item, dict) and any(str(item.get(key)) in screen_ids for key in ("screenId", "from", "to", "target"))
    ]
    return {"edges": edges, "navigationTargets": targets}


def _relevant_components(ir: dict[str, Any], nodes: dict[str, Any]) -> list[Any]:
    refs = {str(node.get("componentRef")) for node in nodes.values() if isinstance(node, dict) and node.get("componentRef")}
    catalog = ir.get("componentCatalog", [])
    if isinstance(catalog, dict):
        return [{"id": key, **copy.deepcopy(value)} if isinstance(value, dict) else {"id": key, "value": value} for key, value in catalog.items() if str(key) in refs]
    return [copy.deepcopy(item) for item in catalog if isinstance(item, dict) and str(item.get("id")) in refs]


def _relevant_versions(ir: dict[str, Any], node_ids: set[str], finding_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    versions = ir.get("review", {}).get("versions", [])
    for version in versions if isinstance(versions, list) else []:
        if not isinstance(version, dict):
            continue
        covered = set(map(str, version.get("findingIds", []))) | set(map(str, version.get("resolvedFindingIds", [])))
        overrides = version.get("nodeOverrides", {}) if isinstance(version.get("nodeOverrides"), dict) else {}
        relevant_overrides = {key: copy.deepcopy(value) for key, value in overrides.items() if str(key) in node_ids}
        if covered.intersection(finding_ids) or relevant_overrides:
            sparse = {key: copy.deepcopy(value) for key, value in version.items() if key != "nodeOverrides"}
            sparse["nodeOverrides"] = relevant_overrides
            result.append(sparse)
    return result


def _compact_finding(item: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id", "title", "severity", "category", "screenId", "nodeId", "reviewVersionId",
        "observation", "impact", "recommendation", "confidence", "sourceTarget",
        "runtimeDiagnosticId", "verification", "proposalVersionId", "status",
    }
    return {key: copy.deepcopy(value) for key, value in item.items() if key in keep}


def _scope_catalog(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "screens": [
            {key: item.get(key) for key in ("id", "name", "platform", "route", "fragment") if item.get(key) is not None}
            for item in ir.get("screens", []) if isinstance(item, dict)
        ],
        "findings": [
            {key: item.get(key) for key in ("id", "title", "severity", "screenId", "nodeId") if item.get(key) is not None}
            for item in _ordered_findings(ir)
        ],
    }


def build_scoped_context(
    ir: dict[str, Any],
    *,
    screen_ids: list[str] | None = None,
    finding_ids: list[str] | None = None,
    token_budget: int = 4000,
    ui_ir_file: str | None = None,
) -> dict[str, Any]:
    """Build a structurally complete scope. It never cuts a selected node subtree."""
    screen_ids = screen_ids or []
    finding_ids = finding_ids or []
    findings = _resolve_findings(ir, finding_ids)
    inferred_screens = [str(item.get("screenId")) for item in findings if item.get("screenId")]
    screens = _resolve_screens(ir, list(dict.fromkeys([*screen_ids, *inferred_screens])))
    node_ids = _node_ids_for_scope(ir, screens, findings)
    all_nodes = ir.get("nodes", {}) if isinstance(ir.get("nodes"), dict) else {}
    nodes = {node_id: copy.deepcopy(all_nodes[node_id]) for node_id in all_nodes if node_id in node_ids}
    review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
    project = ir.get("project", {}) if isinstance(ir.get("project"), dict) else {}
    payload: dict[str, Any] = {
        "type": CONTEXT_TYPE,
        "version": FORMAT_VERSION,
        "project": {key: project.get(key) for key in ("name", "root") if project.get(key) is not None},
        "target": {
            "uiIrFile": ui_ir_file,
            "baselineHash": review.get("baselineHash"),
            "reviewRevision": review.get("revision"),
            "baselineVersion": review.get("baselineVersion"),
        },
        "scope": {
            "screenIds": [str(item.get("id")) for item in screens],
            "findingIds": [str(item.get("id")) for item in findings],
            "nodeIds": list(nodes),
        },
        "screens": copy.deepcopy(screens),
        "nodes": nodes,
        "findings": [_compact_finding(item) for item in findings],
        "versions": _relevant_versions(ir, node_ids, {str(item.get("id")) for item in findings}),
        "tokens": _relevant_tokens(ir, nodes),
        "themes": _relevant_themes(ir, nodes, node_ids),
        "scenarioFixtures": _relevant_fixtures(ir, screens),
        "navigation": _relevant_navigation(ir, {str(item.get("id")) for item in screens}),
        "components": _relevant_components(ir, nodes),
        "platforms": copy.deepcopy(ir.get("platforms", [])),
        "sourceFiles": _source_files([*screens, *nodes.values(), *findings]),
        "patchContract": {
            "type": PATCH_TYPE,
            "version": FORMAT_VERSION,
            "allowedOperations": ["upsert-findings", "upsert-versions", "merge-annotations", "record-verifications"],
            "forbidden": ["baseline screens", "baseline nodes", "baseline tokens", "baseline themes", "application source"],
        },
    }
    if not screens and not findings:
        payload["catalog"] = _scope_catalog(ir)
        payload["next"] = "Request one screen or a small finding set; do not read the full ui-ir.json."
    requested = max(256, int(token_budget))
    estimated = estimate_tokens(payload)
    payload["contextBudget"] = {
        "requestedTokens": requested,
        "estimatedTokens": estimated,
        "withinBudget": estimated <= requested,
        "structuralTruncation": False,
        "recommendation": None if estimated <= requested else "Narrow screenIds/findingIds; selected structure was preserved intact.",
    }
    return payload


def write_scoped_context(
    ir_path: Path,
    output: Path,
    *,
    screen_ids: list[str] | None = None,
    finding_ids: list[str] | None = None,
    token_budget: int = 4000,
) -> dict[str, Any]:
    ir_path = ir_path.resolve()
    payload = build_scoped_context(
        read_json(ir_path), screen_ids=screen_ids, finding_ids=finding_ids,
        token_budget=token_budget, ui_ir_file=str(ir_path),
    )
    write_json(output.resolve(), payload)
    return payload


def patch_template(ir: dict[str, Any], ui_ir_file: str, context_file: str | None = None) -> dict[str, Any]:
    review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
    return {
        "type": PATCH_TYPE,
        "version": FORMAT_VERSION,
        "target": {
            "uiIrFile": ui_ir_file,
            "project": ir.get("project", {}).get("name"),
            "baselineHash": review.get("baselineHash"),
            "reviewRevision": review.get("revision"),
        },
        "contextFile": context_file,
        "operations": [],
    }


def validate_patch(ir: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if patch.get("type") != PATCH_TYPE or patch.get("version") != FORMAT_VERSION:
        errors.append("Unsupported ui-ir.patch.json format")
    target = patch.get("target", {}) if isinstance(patch.get("target"), dict) else {}
    review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
    project = ir.get("project", {}) if isinstance(ir.get("project"), dict) else {}
    for label, expected, actual in (
        ("project", target.get("project"), project.get("name")),
        ("baselineHash", target.get("baselineHash"), review.get("baselineHash")),
        ("reviewRevision", target.get("reviewRevision"), review.get("revision")),
    ):
        if expected is not None and expected != actual:
            errors.append(f"Patch {label} does not match target IR")
    allowed = {"upsert-findings", "upsert-versions", "merge-annotations", "record-verifications"}
    operations = patch.get("operations")
    if not isinstance(operations, list):
        errors.append("Patch operations must be an array")
        return errors
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("op") not in allowed:
            errors.append(f"Unsupported operation at index {index}")
            continue
        if operation.get("op") in {"upsert-findings", "upsert-versions", "merge-annotations", "record-verifications"} and not isinstance(operation.get("value"), list):
            errors.append(f"Operation {index} value must be an array")
        if operation.get("op") == "upsert-versions":
            for version in operation.get("value", []):
                if not isinstance(version, dict) or version.get("kind") != "proposal" or not version.get("id"):
                    errors.append("Only named sparse proposal versions may be upserted")
                if isinstance(version, dict) and any(key in version for key in ("screens", "nodes", "tokens", "themes")):
                    errors.append("Proposal operation cannot replace baseline collections")
    return errors


def apply_patch(ir: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    errors = validate_patch(ir, patch)
    if errors:
        raise ValueError("; ".join(errors))
    result = copy.deepcopy(ir)
    review = result.setdefault("review", {})
    audit = review.setdefault("audit", {})
    for operation in patch.get("operations", []):
        op = operation["op"]
        values = operation["value"]
        if op == "upsert-findings":
            existing = {str(item.get("id")): item for item in audit.setdefault("findings", []) if isinstance(item, dict) and item.get("id")}
            for item in values:
                if not isinstance(item, dict) or not item.get("id"):
                    raise ValueError("Every finding must have a stable id")
                existing[str(item["id"])] = copy.deepcopy(item)
            audit["findings"] = list(existing.values())
        elif op == "upsert-versions":
            existing = {str(item.get("id")): item for item in review.setdefault("versions", []) if isinstance(item, dict) and item.get("id")}
            for item in values:
                existing[str(item["id"])] = copy.deepcopy(item)
            review["versions"] = list(existing.values())
        elif op == "merge-annotations":
            existing = {str(item.get("id")): item for item in review.setdefault("annotations", []) if isinstance(item, dict) and item.get("id")}
            for item in values:
                if not isinstance(item, dict) or not item.get("id"):
                    raise ValueError("Every annotation must have a stable id")
                existing[str(item["id"])] = copy.deepcopy(item)
            review["annotations"] = list(existing.values())
        elif op == "record-verifications":
            findings = {str(item.get("id")): item for item in audit.setdefault("findings", []) if isinstance(item, dict) and item.get("id")}
            for item in values:
                finding_id = str(item.get("findingId") or "") if isinstance(item, dict) else ""
                if finding_id not in findings or not isinstance(item.get("verification"), dict):
                    raise ValueError(f"Invalid verification record for finding: {finding_id or '<missing>'}")
                findings[finding_id]["verification"] = copy.deepcopy(item["verification"])
    return result


def apply_patch_file(ir_path: Path, patch_path: Path, output: Path) -> dict[str, Any]:
    ir_path, patch_path, output = ir_path.resolve(), patch_path.resolve(), output.resolve()
    source = read_json(ir_path)
    patched = apply_patch(source, read_json(patch_path))
    write_json(output, patched)
    return {
        "version": 1,
        "status": "applied",
        "irFile": str(output),
        "patchFile": str(patch_path),
        "baselineUnchanged": hashlib.sha256(_compact({key: source.get(key) for key in ("screens", "nodes", "tokens", "themes", "scenarioFixtures")}).encode()).hexdigest()
        == hashlib.sha256(_compact({key: patched.get(key) for key in ("screens", "nodes", "tokens", "themes", "scenarioFixtures")}).encode()).hexdigest(),
    }
