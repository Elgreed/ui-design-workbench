#!/usr/bin/env python3
"""Deterministic fidelity primitives shared by scanners, adapters and CLI gates."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


FIDELITY_SCHEMA_VERSION = "0.3"
CONFIDENCE_LEVELS = {"exact", "high", "approximate", "unsupported"}
NODE_TYPES = {"container", "card", "text", "button", "input", "image", "icon", "spacer", "divider", "list", "custom"}
BASELINE_FIELDS = ("screens", "screenTree", "nodes", "tokens", "themes", "scenarioFixtures")
VISUAL_PREFIXES = ("layout.", "style.", "text", "asset", "component", "action")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(*parts: Any, prefix: str = "evidence") -> str:
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def property_evidence(file: str, line: int, expression: str, adapter: str, confidence: str = "exact") -> dict[str, Any]:
    return {
        "id": stable_id(file, line, expression, adapter),
        "kind": "source",
        "file": file,
        "line": max(1, int(line or 1)),
        "expression": expression.strip()[:500],
        "adapter": adapter,
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "approximate",
    }


def baseline_payload(ir: dict[str, Any]) -> dict[str, Any]:
    return {field: copy.deepcopy(ir.get(field, {} if field in {"nodes", "tokens", "themes", "scenarioFixtures"} else [])) for field in BASELINE_FIELDS}


def baseline_hash(ir: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(baseline_payload(ir)).encode("utf-8")).hexdigest()


def seal_baseline(ir: dict[str, Any]) -> str:
    review = ir.setdefault("review", {})
    versions = review.setdefault("versions", [])
    baseline_id = str(review.get("baselineVersion") or "baseline")
    review["baselineVersion"] = baseline_id
    baseline = next((item for item in versions if isinstance(item, dict) and item.get("id") == baseline_id), None)
    if baseline is None:
        baseline = {"id": baseline_id, "label": "Before", "kind": "baseline", "status": "approved", "nodeOverrides": {}}
        versions.insert(0, baseline)
    baseline["kind"] = "baseline"
    baseline["nodeOverrides"] = {}
    digest = baseline_hash(ir)
    review["baselineHash"] = digest
    review["baselineHashAlgorithm"] = "sha256"
    return digest


def verify_baseline(ir: dict[str, Any]) -> tuple[bool, str, str]:
    expected = str(ir.get("review", {}).get("baselineHash") or "")
    actual = baseline_hash(ir)
    return bool(expected) and expected == actual, expected, actual


@dataclass(frozen=True)
class TokenDiagnostic:
    token: str
    code: str
    detail: str


class TokenResolver:
    """Resolve nested `$group.token` aliases without erasing the original references."""

    _REFERENCE = re.compile(r"^\$([A-Za-z0-9_.-]+)$")

    def __init__(self, tokens: dict[str, Any], overrides: dict[str, Any] | None = None):
        self.tokens = copy.deepcopy(tokens or {})
        self.overrides = copy.deepcopy(overrides or {})
        self.diagnostics: list[TokenDiagnostic] = []
        self._flat = self._flatten(self.tokens)
        self._flat.update(self._flatten(self.overrides))

    @staticmethod
    def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict) and "value" not in item:
                result.update(TokenResolver._flatten(item, path))
            else:
                result[path] = item.get("value") if isinstance(item, dict) and "value" in item else item
        return result

    def resolve(self, value: Any) -> Any:
        return self._resolve(value, ())

    def _resolve(self, value: Any, stack: tuple[str, ...]) -> Any:
        if not isinstance(value, str):
            return value
        match = self._REFERENCE.match(value.strip())
        if not match:
            return value
        name = match.group(1)
        if name in stack:
            self.diagnostics.append(TokenDiagnostic(name, "token-cycle", " -> ".join((*stack, name))))
            return value
        if name not in self._flat:
            self.diagnostics.append(TokenDiagnostic(name, "token-missing", f"No token named {name}"))
            return value
        return self._resolve(self._flat[name], (*stack, name))

    def resolved_tokens(self) -> dict[str, Any]:
        return {name: self._resolve(value, (name,)) for name, value in sorted(self._flat.items())}


def _path_exists(node: dict[str, Any], path: str) -> bool:
    current: Any = node
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _property_paths(node: dict[str, Any]) -> Iterable[str]:
    for group in ("layout", "style"):
        for key in node.get(group, {}) if isinstance(node.get(group), dict) else ():
            yield f"{group}.{key}"
    for key in ("text", "asset", "component", "action"):
        if key in node:
            yield key


def validate_strict_ir(ir: dict[str, Any]) -> list[str]:
    """Semantic v0.3 validator. It is strict only for fidelity schema 0.3 artifacts."""
    if str(ir.get("fidelity", {}).get("schemaVersion") or "") != FIDELITY_SCHEMA_VERSION:
        return []
    errors: list[str] = []
    nodes = ir.get("nodes")
    screens = ir.get("screens")
    if not isinstance(nodes, dict) or not nodes:
        return ["Fidelity 0.3 IR requires non-empty nodes"]
    if not isinstance(screens, list) or not screens:
        errors.append("Fidelity 0.3 IR requires non-empty screens")
        screens = []
    root_ids = {screen.get("root") for screen in screens if isinstance(screen, dict)}
    for root_id in sorted(root_ids):
        if root_id not in nodes:
            errors.append(f"Screen root does not exist: {root_id}")
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"Node {node_id} must be an object")
            continue
        if node.get("type") not in NODE_TYPES:
            errors.append(f"Node {node_id} has unsupported type {node.get('type')}")
        confidence = node.get("confidence")
        if confidence not in CONFIDENCE_LEVELS:
            errors.append(f"Node {node_id} needs exact/high/approximate/unsupported confidence")
        provenance = node.get("provenance", {})
        if not isinstance(provenance, dict):
            errors.append(f"Node {node_id} provenance must be an object")
            provenance = {}
        for path, evidence in provenance.items():
            if not _path_exists(node, path):
                errors.append(f"Node {node_id} provenance references missing property {path}")
            if not isinstance(evidence, dict) or not all(evidence.get(key) not in (None, "") for key in ("id", "kind", "file", "line", "adapter", "confidence")):
                errors.append(f"Node {node_id} has invalid provenance for {path}")
            elif evidence.get("confidence") not in CONFIDENCE_LEVELS:
                errors.append(f"Node {node_id} provenance {path} has invalid confidence")
        if confidence != "unsupported":
            for path in _property_paths(node):
                if path.startswith(VISUAL_PREFIXES) and path not in provenance:
                    errors.append(f"Node {node_id} property {path} lacks provenance")
        for child in node.get("children", []):
            if child not in nodes:
                errors.append(f"Node {node_id} references missing child {child}")
    resolver = TokenResolver(ir.get("tokens", {}))
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        for group in ("layout", "style"):
            for value in node.get(group, {}).values() if isinstance(node.get(group), dict) else ():
                resolver.resolve(value)
    errors.extend(f"{item.code}: {item.detail}" for item in resolver.diagnostics)
    for theme in ir.get("themes", {}).get("items", []) if isinstance(ir.get("themes"), dict) else ():
        if not isinstance(theme, dict):
            continue
        theme_resolver = TokenResolver(ir.get("tokens", {}), theme.get("tokenOverrides", {}))
        theme_resolver.resolved_tokens()
        errors.extend(f"theme {theme.get('id')}: {item.code}: {item.detail}" for item in theme_resolver.diagnostics)
    valid_baseline, expected, actual = verify_baseline(ir)
    if not valid_baseline:
        errors.append(f"Immutable baseline hash mismatch: expected {expected or '<missing>'}, actual {actual}")
    return errors


def fidelity_report(ir: dict[str, Any]) -> dict[str, Any]:
    schema_version = str(ir.get("fidelity", {}).get("schemaVersion") or "")
    applicable = schema_version == FIDELITY_SCHEMA_VERSION
    errors = validate_strict_ir(ir)
    properties = 0
    sourced = 0
    by_confidence = {level: 0 for level in sorted(CONFIDENCE_LEVELS)}
    unsupported: list[dict[str, Any]] = []
    for node_id, node in ir.get("nodes", {}).items():
        if not isinstance(node, dict):
            continue
        by_confidence[str(node.get("confidence") or "unsupported")] = by_confidence.get(str(node.get("confidence") or "unsupported"), 0) + 1
        provenance = node.get("provenance", {}) if isinstance(node.get("provenance"), dict) else {}
        for path in _property_paths(node):
            properties += 1
            sourced += int(path in provenance)
        if node.get("confidence") == "unsupported":
            unsupported.append({"nodeId": node_id, "component": node.get("component"), "source": node.get("source", {})})
    baseline_valid, baseline_expected, baseline_actual = verify_baseline(ir)
    return {
        "version": 1,
        "schemaVersion": schema_version or None,
        "applicable": applicable,
        "status": "not-applicable" if not applicable else "pass" if not errors else "fail",
        "applicabilityReason": None if applicable else f"Fidelity Core requires schema {FIDELITY_SCHEMA_VERSION}",
        "strictErrors": errors,
        "propertyProvenance": {"covered": sourced, "total": properties, "percent": round(100 * sourced / properties, 1) if properties else 100.0},
        "nodeConfidence": by_confidence,
        "unsupported": unsupported,
        "baseline": {"valid": baseline_valid, "expected": baseline_expected, "actual": baseline_actual},
    }
