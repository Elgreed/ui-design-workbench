"""Conservative Android XML discovery helpers shared by the scanner and adapter.

The helpers deliberately stop at source evidence. They do not execute Android
resource resolution, Data Binding expressions, custom views, or Layoutlib.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


SCREEN_PREFIXES = (
    "activity_", "fragment_", "dialog_", "scene_", "screen_", "page_",
    "bottom_sheet_", "sheet_",
)
COLLECTION_PREFIXES = ("cell_", "item_", "row_", "list_item_", "grid_item_")
PARTIAL_PREFIXES = ("include_", "partial_", "content_", "merge_")


def _local(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attrs(element: ET.Element) -> dict[str, str]:
    return {_local(key): str(value) for key, value in element.attrib.items()}


def _line(text: str, expression: str, start: int = 0) -> int:
    offset = text.find(expression, start)
    return text.count("\n", 0, max(0, offset)) + 1 if offset >= 0 else 1


def _pascal(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", value) if part)


def _snake(value: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def canonical_android_id(value: str | None) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"@\+?id/([\w.:-]+)", raw)
    return f"@id/{match.group(1)}" if match else raw


def android_layout_metadata(path: Path) -> dict[str, str] | None:
    """Classify one res/layout* file without treating every partial as a screen."""
    parts = [part.lower() for part in path.parts]
    layout_dir = next((part for part in reversed(parts[:-1]) if part == "layout" or part.startswith("layout-")), "")
    if path.suffix.lower() != ".xml" or not layout_dir:
        return None
    stem = path.stem.lower()
    qualifier = layout_dir.removeprefix("layout").lstrip("-")
    if stem.startswith(SCREEN_PREFIXES):
        role = "screen"
    elif stem.startswith(COLLECTION_PREFIXES):
        role = "collection-item"
    elif stem.startswith(PARTIAL_PREFIXES) or stem == "include":
        role = "partial"
    else:
        role = "component"
    label = _pascal(stem)
    if qualifier:
        label = f"{label} [{qualifier}]"
    return {
        "role": role,
        "resource": stem,
        "qualifier": qualifier,
        "name": label,
        "sourceKind": "android-layout-variant" if qualifier else "android-layout",
    }


def android_layout_refs(text: str) -> list[str]:
    """Extract layout resources referenced directly or through generated bindings."""
    refs = {match.group(1) for match in re.finditer(r"\bR\.layout\.([A-Za-z0-9_]+)", text)}
    if refs:
        return sorted(refs)
    binding_patterns = (
        r"\bBase[A-Za-z0-9_]*\s*<\s*([A-Z][A-Za-z0-9]+Binding)",
        r"\b([A-Z][A-Za-z0-9]+Binding)\.inflate\s*\(",
    )
    for pattern in binding_patterns:
        for match in re.finditer(pattern, text):
            candidate = _snake(match.group(1).removesuffix("Binding"))
            if candidate:
                refs.add(candidate)
    if refs:
        return sorted(refs)
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+)Binding\b", text):
        candidate = _snake(match.group(1))
        if candidate:
            refs.add(candidate)
    return sorted(refs)


def parse_android_navigation(text: str, source: str) -> dict[str, list[dict[str, Any]]]:
    """Read destinations, actions, and deep links from an Android nav graph."""
    result: dict[str, list[dict[str, Any]]] = {"screens": [], "routes": [], "navigationTargets": []}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return result
    if _local(root.tag) != "navigation":
        return result

    def walk(container: ET.Element, groups: list[str]) -> None:
        container_attrs = _attrs(container)
        graph_label = container_attrs.get("label") or canonical_android_id(container_attrs.get("id")).removeprefix("@id/")
        nested_groups = [*groups, graph_label] if graph_label else groups
        for child in container:
            tag = _local(child.tag)
            attrs = _attrs(child)
            destination_id = canonical_android_id(attrs.get("id"))
            if tag == "navigation":
                walk(child, nested_groups)
                continue
            if tag not in {"fragment", "activity", "dialog"}:
                continue
            class_name = attrs.get("name", "")
            short_name = class_name.rsplit(".", 1)[-1] if class_name else destination_id.removeprefix("@id/")
            label = attrs.get("label") or short_name or destination_id
            line = _line(text, attrs.get("id") or f"<{tag}")
            if destination_id:
                result["screens"].append({
                    "name": short_name or _pascal(destination_id.removeprefix("@id/")),
                    "label": label,
                    "file": source,
                    "line": line,
                    "platform": "android-views",
                    "confidence": "high",
                    "fragment": destination_id,
                    "route": destination_id,
                    "androidClass": class_name,
                    "groupPath": [value for value in nested_groups if value],
                    "sourceKind": "android-navigation-destination",
                })
                result["routes"].append({"route": destination_id, "file": source, "line": line})
            for nested in child:
                nested_tag = _local(nested.tag)
                nested_attrs = _attrs(nested)
                if nested_tag == "action":
                    target = canonical_android_id(nested_attrs.get("destination"))
                    if target:
                        result["navigationTargets"].append({
                            "source": destination_id,
                            "target": target,
                            "actionId": canonical_android_id(nested_attrs.get("id")),
                            "label": canonical_android_id(nested_attrs.get("id")) or target,
                            "file": source,
                            "line": _line(text, nested_attrs.get("id") or target),
                            "sourceKind": "android-navigation-action",
                        })
                elif nested_tag == "deepLink" and nested_attrs.get("uri"):
                    result["routes"].append({
                        "route": nested_attrs["uri"],
                        "file": source,
                        "line": _line(text, nested_attrs["uri"]),
                        "screenTarget": destination_id,
                    })

    walk(root, [])
    return result


def reconcile_android_screen_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge nav destinations, Android classes, and referenced layout resources."""
    items = [dict(item) for item in candidates]
    class_items = {
        str(item.get("androidClass") or item.get("name") or "").rsplit(".", 1)[-1]: item
        for item in items
        if item.get("sourceKind") in {"android-class", "android-class-template"}
    }

    def inherited_layouts(item: dict[str, Any]) -> list[str]:
        current = item
        seen: set[str] = set()
        while current:
            refs = [str(value) for value in current.get("layoutRefs", []) if value]
            if refs:
                return refs
            super_name = str(current.get("androidSuperClass") or "")
            if not super_name or super_name in seen:
                break
            seen.add(super_name)
            current = class_items.get(super_name, {})
        return []
    claimed_layouts: set[str] = set()
    claimed_classes: set[int] = set()
    for item in items:
        if item.get("sourceKind") != "android-navigation-destination":
            continue
        class_name = str(item.get("androidClass") or item.get("name") or "").rsplit(".", 1)[-1]
        class_item = class_items.get(class_name)
        if not class_item:
            continue
        refs = inherited_layouts(class_item)
        if refs:
            item["layoutRefs"] = refs
            claimed_layouts.update(refs)
        item["implementationSource"] = class_item.get("file", "")
        claimed_classes.add(id(class_item))

    for item in items:
        if item.get("sourceKind") not in {"android-class", "android-class-template"} or id(item) in claimed_classes:
            continue
        if item.get("sourceKind") == "android-class-template":
            claimed_classes.add(id(item))
            continue
        refs = inherited_layouts(item)
        if refs:
            item["layoutRefs"] = refs
        if refs:
            claimed_layouts.update(refs)
        else:
            claimed_classes.add(id(item))

    reconciled: list[dict[str, Any]] = []
    for item in items:
        if id(item) in claimed_classes:
            continue
        if item.get("sourceKind", "").startswith("android-layout") and item.get("layoutResource") in claimed_layouts:
            continue
        reconciled.append(item)
    return reconciled
