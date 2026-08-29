#!/usr/bin/env python3
"""Shared deterministic helpers for UI Design Workbench quality gates."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


def resolve_profile_catalog() -> Path:
    candidates = []
    if os.environ.get("UIDW_HOME"):
        candidates.append(Path(os.environ["UIDW_HOME"]).expanduser() / "references" / "platform-profiles.json")
    candidates.extend([
        Path(__file__).resolve().parent.parent / "references" / "platform-profiles.json",
        Path(__file__).resolve().parent / "share" / "ui-design-workbench" / "references" / "platform-profiles.json",
        Path(sys.prefix) / "share" / "ui-design-workbench" / "references" / "platform-profiles.json",
    ])
    return next((item for item in candidates if item.is_file()), candidates[0])


PROFILE_CATALOG_PATH = resolve_profile_catalog()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def profile_catalog() -> dict[str, Any]:
    return read_json(PROFILE_CATALOG_PATH)


def platform_family(value: Any) -> str | None:
    platform = str(value or "").strip().lower()
    if any(marker in platform for marker in ("android-tv", "compose-tv", "leanback", "react-native", "react_native", "mac-catalyst")):
        return None
    if platform in {"windows", "windows-winui", "windows-wpf", "windows-xaml", "winui", "winui3", "wpf", "windows-app-sdk"} or platform.startswith("windows-"):
        return "windows"
    if platform in {"macos", "swiftui-macos", "appkit"} or "macos" in platform:
        return "macos"
    if "android" in platform:
        return "android"
    if platform in {"ios", "swiftui", "uikit"} or "apple" in platform:
        return "ios"
    if platform == "flutter":
        return "flutter"
    if platform in {"web", "react-web", "vue", "svelte"}:
        return "web"
    return None


def target_families(ir: dict[str, Any]) -> set[str]:
    explicit = ir.get("design", {}).get("targetPlatforms", [])
    values = explicit or ir.get("platforms", [])
    families = {platform_family(item) for item in values}
    families.discard(None)
    return families


def framework_adapters(ir: dict[str, Any]) -> set[str]:
    known = profile_catalog().get("frameworkAdapters", {})
    found: set[str] = set()
    for value in ir.get("platforms", []):
        normalized = str(value or "").strip().lower()
        if normalized in known:
            found.add(normalized)
        elif "flutter" in normalized:
            found.add("flutter")
    return found


def walk_tree_screen_ids(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        screen_id = item.get("screenId") or item.get("screen")
        if screen_id:
            result.append(str(screen_id))
        result.extend(walk_tree_screen_ids(item.get("children", [])))
    return result


def walk_tree_screen_paths(items: Iterable[Any], path: tuple[str, ...] = ()) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        screen_id = item.get("screenId") or item.get("screen")
        if screen_id:
            result[str(screen_id)] = list(path)
            continue
        label = str(item.get("label") or item.get("name") or item.get("id") or "").strip()
        result.update(walk_tree_screen_paths(item.get("children", []), (*path, label) if label else path))
    return result


def hierarchy_issues(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare authored screenTree paths with source-evidenced hierarchy metadata."""
    paths = walk_tree_screen_paths(ir.get("screenTree", []))
    screens = ir.get("screens", [])
    discovered = [item for item in ir.get("discoveredScreens", []) if isinstance(item, dict)]
    screen_by_evidence: dict[tuple[str, str], str] = {}
    screen_by_fragment: dict[str, str] = {}
    for screen in screens:
        screen_id = str(screen.get("id") or "")
        source = screen.get("source", {}) if isinstance(screen.get("source"), dict) else {}
        screen_by_evidence[(str(source.get("file") or ""), str(source.get("symbol") or screen.get("name") or ""))] = screen_id
        if screen.get("fragment"):
            screen_by_fragment[str(screen["fragment"])] = screen_id

    def normalized(values: Iterable[Any]) -> list[str]:
        return [re.sub(r"[^\w]+", " ", str(value).casefold()).strip() for value in values if str(value).strip()]

    def contains_path(actual: list[str], expected: list[str]) -> bool:
        if not expected:
            return True
        return any(actual[index:index + len(expected)] == expected for index in range(len(actual) - len(expected) + 1))

    issues: list[dict[str, Any]] = []
    evidence_by_fragment = {str(item.get("fragment")): item for item in discovered if item.get("fragment")}
    for candidate in discovered:
        key = (str(candidate.get("file") or ""), str(candidate.get("name") or ""))
        screen_id = screen_by_evidence.get(key) or screen_by_fragment.get(str(candidate.get("fragment") or ""))
        if not screen_id or screen_id not in paths:
            continue
        expected = normalized(candidate.get("groupPath", []))
        actual = normalized(paths[screen_id])
        if expected and not contains_path(actual, expected):
            issues.append({
                "code": "group-path-mismatch",
                "screenId": screen_id,
                "expected": candidate.get("groupPath", []),
                "actual": paths[screen_id],
            })
        parent_fragment = str(candidate.get("parentFragment") or "")
        if not parent_fragment:
            continue
        parent_candidate = evidence_by_fragment.get(parent_fragment, {})
        parent_key = (str(parent_candidate.get("file") or ""), str(parent_candidate.get("name") or ""))
        parent_id = screen_by_evidence.get(parent_key) or screen_by_fragment.get(parent_fragment)
        if not parent_id or parent_id not in paths:
            continue
        parent_path = normalized(paths[parent_id])
        child_path = normalized(paths[screen_id])
        if len(child_path) <= len(parent_path) or child_path[:len(parent_path)] != parent_path:
            issues.append({
                "code": "parent-hierarchy-flattened",
                "screenId": screen_id,
                "parentScreenId": parent_id,
                "parentPath": paths[parent_id],
                "actual": paths[screen_id],
            })
    return issues


def navigation_graph_issues(ir: dict[str, Any]) -> list[dict[str, Any]]:
    discovered = [item for item in ir.get("discoveredScreens", []) if isinstance(item, dict)]
    nested = [item for item in discovered if item.get("parentFragment")]
    graph = ir.get("navigationGraph")
    if not nested and graph is None:
        return []
    if not isinstance(graph, dict):
        return [{"code": "navigation-graph-missing"}]
    screen_ids = {str(item.get("id")) for item in ir.get("screens", []) if item.get("id")}
    graph_ids = {str(item.get("screenId")) for item in graph.get("nodes", []) if isinstance(item, dict) and item.get("screenId")}
    issues: list[dict[str, Any]] = []
    if graph_ids != screen_ids:
        issues.append({"code": "navigation-graph-node-mismatch", "missing": sorted(screen_ids - graph_ids), "unknown": sorted(graph_ids - screen_ids)})
    edges = {
        (str(item.get("from")), str(item.get("to")), str(item.get("kind")))
        for item in graph.get("edges", []) if isinstance(item, dict)
    }
    for source, target, kind in edges:
        if source not in screen_ids or target not in screen_ids:
            issues.append({"code": "navigation-graph-edge-invalid", "from": source, "to": target, "kind": kind})
    screen_by_fragment = {str(item.get("fragment")): str(item.get("id")) for item in ir.get("screens", []) if item.get("fragment")}
    candidate_screen = {
        str(item.get("fragment")): screen_by_fragment.get(str(item.get("fragment")))
        for item in discovered if item.get("fragment")
    }
    for item in nested:
        child_id = candidate_screen.get(str(item.get("fragment")))
        parent_id = candidate_screen.get(str(item.get("parentFragment")))
        if child_id and parent_id and (parent_id, child_id, "open-logical-view") not in edges:
            issues.append({"code": "navigation-parent-edge-missing", "from": parent_id, "to": child_id})
    return issues


def node_screen_map(ir: dict[str, Any]) -> dict[str, set[str]]:
    nodes = ir.get("nodes", {})
    result: dict[str, set[str]] = {str(node_id): set() for node_id in nodes}

    def visit(node_id: str, screen_id: str, seen: set[str]) -> None:
        if node_id in seen or node_id not in nodes:
            return
        seen.add(node_id)
        result.setdefault(node_id, set()).add(screen_id)
        for child in nodes[node_id].get("children", []):
            visit(str(child), screen_id, seen)

    for screen in ir.get("screens", []):
        visit(str(screen.get("root", "")), str(screen.get("id", "")), set())
    return result
