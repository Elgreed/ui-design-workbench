#!/usr/bin/env python3
"""Shared deterministic helpers for UI Design Workbench quality gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parent.parent
PROFILE_CATALOG_PATH = SKILL_ROOT / "references" / "platform-profiles.json"


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
    if "android" in platform:
        return "android"
    if platform in {"ios", "ipados", "swiftui", "uikit"} or "apple" in platform:
        return "ios"
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
        elif "react-native" in normalized or "react_native" in normalized:
            found.add("react-native")
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
