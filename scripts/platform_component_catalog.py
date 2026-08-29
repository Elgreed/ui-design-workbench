#!/usr/bin/env python3
"""Platform component aliases and renderer defaults for HTML projection."""

from __future__ import annotations

import copy
import json
import os
import re
import site
import sys
from pathlib import Path
from typing import Any

from quality_common import platform_family


SUPPORTED_FAMILIES = ("android", "ios", "macos", "windows", "flutter", "web")


def resolve_reference(name: str) -> Path:
    candidates: list[Path] = []
    if os.environ.get("UIDW_HOME"):
        candidates.append(Path(os.environ["UIDW_HOME"]).expanduser() / "references" / name)
    candidates.extend([
        Path(__file__).resolve().parent.parent / "references" / name,
        Path(__file__).resolve().parent / "share" / "ui-design-workbench" / "references" / name,
        Path(site.USER_BASE) / "share" / "ui-design-workbench" / "references" / name,
        Path(sys.prefix) / "share" / "ui-design-workbench" / "references" / name,
    ])
    return next((item for item in candidates if item.is_file()), candidates[0])


def resolve_component_catalog() -> Path:
    return resolve_reference("component-catalog.json")


COMPONENT_CATALOG_PATH = resolve_component_catalog()
COMPONENT_INVENTORY_PATH = resolve_reference("component-inventory.json")


def component_catalog() -> dict[str, Any]:
    payload = json.loads(COMPONENT_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("families"), dict):
        raise ValueError(f"Invalid component catalog: {COMPONENT_CATALOG_PATH}")
    return payload


def component_inventory() -> dict[str, Any]:
    payload = json.loads(COMPONENT_INVENTORY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("families"), dict):
        raise ValueError(f"Invalid component inventory: {COMPONENT_INVENTORY_PATH}")
    return payload


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _family_from_standard_ref(value: Any) -> str | None:
    ref = str(value or "").lower()
    prefixes = {
        "material3.": "android", "apple.": "ios", "macos.": "macos",
        "windows.": "windows", "winui.": "windows", "flutter.": "flutter",
        "html.": "web", "aria.": "web",
    }
    return next((family for prefix, family in prefixes.items() if ref.startswith(prefix)), None)


def _index_for_family(family: str, catalog: dict[str, Any], inventory: dict[str, Any]) -> tuple[dict[str, tuple[str, dict[str, Any]]], dict[str, tuple[str, dict[str, Any]]]]:
    aliases: dict[str, tuple[str, dict[str, Any]]] = {}
    types: dict[str, tuple[str, dict[str, Any]]] = {}
    components = catalog.get("families", {}).get(family, {}).get("components", {})
    for component_id, descriptor in components.items():
        if not isinstance(descriptor, dict):
            continue
        entry = (str(component_id), descriptor)
        aliases[_key(component_id)] = entry
        for alias in descriptor.get("aliases", []):
            aliases[_key(alias)] = entry
        for node_type in descriptor.get("types", []):
            types.setdefault(_key(node_type), entry)
    concepts = inventory.get("families", {}).get(family, {}).get("inventory", {})
    for concept_id, concept in concepts.items():
        recipe_id = str(concept.get("recipe") or "")
        descriptor = components.get(recipe_id)
        if not isinstance(descriptor, dict):
            continue
        entry = (str(concept_id), descriptor)
        aliases.setdefault(_key(concept_id), entry)
        for names in concept.get("bindings", {}).values():
            for alias in names:
                # Preserve stable recipe IDs for bindings that were already
                # recognized by the calibrated catalog. The inventory extends
                # recognition; it must not silently rename existing matches.
                aliases.setdefault(_key(alias), entry)
    return aliases, types


def resolve_component(family: str, node: dict[str, Any], catalog: dict[str, Any] | None = None, inventory: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]] | None:
    if family not in SUPPORTED_FAMILIES:
        return None
    payload = catalog or component_catalog()
    aliases, types = _index_for_family(family, payload, inventory or component_inventory())
    candidates = [node.get("component"), str(node.get("standardRef") or "").rsplit(".", 1)[-1]]
    for candidate in candidates:
        if candidate and _key(candidate) in aliases:
            return aliases[_key(candidate)]
    standard_family = _family_from_standard_ref(node.get("standardRef"))
    if node.get("inheritsAppearance") or standard_family == family:
        return types.get(_key(node.get("type")))
    return None


def adapter_type_map(family: str, adapter: str, inventory: dict[str, Any] | None = None) -> dict[str, str]:
    payload = inventory or component_inventory()
    result: dict[str, str] = {}
    concepts = payload.get("families", {}).get(family, {}).get("inventory", {})
    for concept in concepts.values():
        node_type = str(concept.get("nodeType") or "custom")
        for name in concept.get("bindings", {}).get(adapter, []):
            result[str(name)] = node_type
    return result


def inventory_summary(inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = inventory or component_inventory()
    families = payload.get("families", {})
    summaries: dict[str, Any] = {}
    for family in SUPPORTED_FAMILIES:
        concepts = families.get(family, {}).get("inventory", {})
        bindings = [
            name
            for concept in concepts.values()
            for names in concept.get("bindings", {}).values()
            for name in names
        ]
        summaries[family] = {
            "conceptCount": len(concepts),
            "bindingCount": len(set(bindings)),
            "adapterCount": len({adapter for concept in concepts.values() for adapter in concept.get("bindings", {})}),
        }
    return {
        "version": payload.get("version", 1),
        "verifiedAt": payload.get("verifiedAt"),
        "families": summaries,
        "conceptCount": sum(item["conceptCount"] for item in summaries.values()),
        "bindingCount": sum(item["bindingCount"] for item in summaries.values()),
    }


def catalog_summary(catalog: dict[str, Any] | None = None, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = catalog or component_catalog()
    inventory_data = inventory or component_inventory()
    inventory_info = inventory_summary(inventory_data)
    families = payload.get("families", {})
    return {
        "version": payload.get("version", 1),
        "authorityOrder": payload.get("authorityOrder", []),
        "families": {
            family: {
                "recipeCount": len(families.get(family, {}).get("components", {})),
                **inventory_info["families"][family],
                # Backward-compatible field: callers that displayed the old
                # coarse catalog count now receive the complete binding count.
                "componentCount": inventory_info["families"][family]["bindingCount"],
                "officialSourceCount": sum(
                    1 for source in families.get(family, {}).get("sources", [])
                    if source.get("authority") in {"official", "official-standard"}
                ),
            }
            for family in SUPPORTED_FAMILIES
        },
        "recipeCount": sum(len(families.get(family, {}).get("components", {})) for family in SUPPORTED_FAMILIES),
        "conceptCount": inventory_info["conceptCount"],
        "bindingCount": inventory_info["bindingCount"],
        "componentCount": inventory_info["bindingCount"],
        "verifiedAt": inventory_info["verifiedAt"],
    }


def validate_component_catalog(catalog: dict[str, Any] | None = None, inventory: dict[str, Any] | None = None) -> list[str]:
    payload = catalog or component_catalog()
    inventory_data = inventory or component_inventory()
    errors: list[str] = []
    families = payload.get("families", {})
    if set(families) != set(SUPPORTED_FAMILIES):
        errors.append(f"catalog families must be exactly: {', '.join(SUPPORTED_FAMILIES)}")
    if set(inventory_data.get("families", {})) != set(SUPPORTED_FAMILIES):
        errors.append(f"inventory families must be exactly: {', '.join(SUPPORTED_FAMILIES)}")
    valid_kinds = {"button", "icon-button", "input", "surface", "text", "switch", "checkbox", "navigation", "list", "progress"}
    for family in SUPPORTED_FAMILIES:
        descriptor = families.get(family, {})
        if not descriptor.get("sources"):
            errors.append(f"{family}: missing official sources")
        seen: dict[str, str] = {}
        for component_id, component in descriptor.get("components", {}).items():
            kind = component.get("rendererKind")
            if kind not in valid_kinds:
                errors.append(f"{family}.{component_id}: invalid rendererKind {kind!r}")
            for alias in [component_id, *component.get("aliases", [])]:
                key = _key(alias)
                if key in seen and seen[key] != component_id:
                    errors.append(f"{family}: alias {alias!r} conflicts between {seen[key]} and {component_id}")
                seen[key] = component_id
        concepts = inventory_data.get("families", {}).get(family, {}).get("inventory", {})
        adapter_aliases: dict[tuple[str, str], str] = {}
        for concept_id, concept in concepts.items():
            recipe = concept.get("recipe")
            if recipe not in descriptor.get("components", {}):
                errors.append(f"{family}.{concept_id}: unknown recipe {recipe!r}")
            if concept.get("nodeType") not in {"button", "input", "text", "card", "list", "container", "image", "icon", "divider", "spacer"}:
                errors.append(f"{family}.{concept_id}: invalid nodeType {concept.get('nodeType')!r}")
            if not concept.get("bindings"):
                errors.append(f"{family}.{concept_id}: missing framework bindings")
            for adapter, names in concept.get("bindings", {}).items():
                for name in names:
                    key = (str(adapter), _key(name))
                    if key in adapter_aliases and adapter_aliases[key] != concept_id:
                        errors.append(f"{family}.{adapter}: binding {name!r} conflicts between {adapter_aliases[key]} and {concept_id}")
                    adapter_aliases[key] = str(concept_id)
    return errors


def apply_component_defaults(ir: dict[str, Any]) -> dict[str, Any]:
    """Return a render-only IR copy enriched with platform component defaults."""
    rendered = copy.deepcopy(ir)
    catalog = component_catalog()
    inventory = component_inventory()
    nodes = rendered.get("nodes", {})
    node_families: dict[str, str] = {}

    def visit(node_id: str, family: str, seen: set[str]) -> None:
        if not node_id or node_id in seen or node_id not in nodes:
            return
        seen.add(node_id)
        node_families.setdefault(node_id, family)
        for child_id in nodes[node_id].get("children", []):
            visit(str(child_id), family, seen)

    for screen in rendered.get("screens", []):
        family = platform_family(screen.get("platform"))
        if family in SUPPORTED_FAMILIES:
            visit(str(screen.get("root") or ""), family, set())

    target_families = {
        platform_family(value)
        for value in rendered.get("design", {}).get("targetPlatforms", []) or rendered.get("platforms", [])
    }
    target_families.discard(None)
    fallback_family = next(iter(target_families)) if len(target_families) == 1 else None

    for node_id, node in nodes.items():
        family = node_families.get(node_id) or _family_from_standard_ref(node.get("standardRef")) or fallback_family
        if family not in SUPPORTED_FAMILIES:
            continue
        resolved = resolve_component(family, node, catalog, inventory)
        if not resolved:
            continue
        component_id, descriptor = resolved
        node["rendererFamily"] = family
        node["rendererComponentId"] = f"{family}.{component_id}"
        node["rendererRecipeId"] = next(
            (
                concept.get("recipe")
                for candidate_id, concept in inventory.get("families", {}).get(family, {}).get("inventory", {}).items()
                if candidate_id == component_id
            ),
            component_id,
        )
        node["rendererKind"] = descriptor.get("rendererKind", node.get("type", "container"))
        node["rendererDefaults"] = {
            "layout": copy.deepcopy(descriptor.get("layout", {})),
            "style": copy.deepcopy(descriptor.get("style", {})),
        }
        node["layout"] = {**node["rendererDefaults"]["layout"], **(node.get("layout", {}) if isinstance(node.get("layout"), dict) else {})}
        node["style"] = {**node["rendererDefaults"]["style"], **(node.get("style", {}) if isinstance(node.get("style"), dict) else {})}
        authored_semantics = node.get("semantics", {}) if isinstance(node.get("semantics"), dict) else {}
        default_semantics = copy.deepcopy(descriptor.get("semantics", {}))
        conditional_roles = {"button", "link", "textbox", "checkbox", "radio", "switch", "slider", "combobox", "menuitem", "tab"}
        if (
            str(default_semantics.get("role") or "").lower() in conditional_roles
            and node.get("type") not in {"button", "input"}
            and not node.get("action")
            and not authored_semantics.get("role")
        ):
            default_semantics.pop("role", None)
        semantics = {**default_semantics, **authored_semantics}
        if semantics:
            node["semantics"] = semantics
        if descriptor.get("rendererKind") in {"switch", "checkbox"} and str(semantics.get("role") or "").lower() in conditional_roles:
            node["type"] = "button"
    rendered.setdefault("renderer", {})["componentCatalog"] = catalog_summary(catalog, inventory)
    return rendered
