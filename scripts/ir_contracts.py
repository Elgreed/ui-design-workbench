#!/usr/bin/env python3
"""Canonical interaction and navigation contracts shared by UIDW stages."""

from __future__ import annotations

from typing import Any


INTERACTION_CONTRACT_VERSION = 1
DIAGNOSTICS_ENGINE_VERSION = 3

NATIVE_INTERACTIVE_NODE_TYPES = frozenset({"button", "input"})
INTERACTIVE_SEMANTIC_ROLES = frozenset(
    {
        "button",
        "checkbox",
        "combobox",
        "gridcell",
        "link",
        "menuitem",
        "option",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "textbox",
        "treeitem",
    }
)
SUPPORTED_ACTION_TYPES = frozenset(
    {
        "navigate",
        "back",
        "set-node-state",
        "toggle-node-state",
        "toggle",
        "reset-state",
    }
)


def interaction_contract(node: dict[str, Any]) -> dict[str, Any]:
    """Return the only supported interpretation of a node's interactivity."""

    node_type = str(node.get("type", "")).strip().lower()
    action_type = str(node.get("action", {}).get("type", "")).strip()
    semantic_role = str(node.get("semantics", {}).get("role", "")).strip().lower()
    sources: list[str] = []
    if node_type in NATIVE_INTERACTIVE_NODE_TYPES:
        sources.append("native-node")
    if action_type in SUPPORTED_ACTION_TYPES:
        sources.append("action")
    if semantic_role in INTERACTIVE_SEMANTIC_ROLES:
        sources.append("semantic-role")
    return {
        "version": INTERACTION_CONTRACT_VERSION,
        "interactive": bool(sources),
        "sources": sources,
        "nodeType": node_type,
        "actionType": action_type,
        "semanticRole": semantic_role,
        "keyboardExpected": bool(sources),
    }


def browser_interaction_contract() -> dict[str, Any]:
    """Serializable constants embedded into the standalone workbench."""

    return {
        "version": INTERACTION_CONTRACT_VERSION,
        "nativeNodeTypes": sorted(NATIVE_INTERACTIVE_NODE_TYPES),
        "semanticRoles": sorted(INTERACTIVE_SEMANTIC_ROLES),
        "actionTypes": sorted(SUPPORTED_ACTION_TYPES),
    }
