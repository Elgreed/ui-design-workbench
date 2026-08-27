#!/usr/bin/env python3
"""Shared deterministic helpers for UI Design Workbench quality gates."""

from __future__ import annotations

import json
import os
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
    if platform in {"android-tv", "android-tv-compose", "android-tv-views", "android-tv-leanback", "compose-tv", "leanback"} or "android-tv" in platform:
        return "android-tv"
    if platform in {"windows", "windows-winui", "windows-wpf", "windows-xaml", "winui", "winui3", "wpf", "windows-app-sdk", "react-native-windows"} or platform.startswith("windows-"):
        return "windows"
    if platform in {"macos", "swiftui-macos", "appkit", "mac-catalyst", "react-native-macos"} or "macos" in platform:
        return "macos"
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
