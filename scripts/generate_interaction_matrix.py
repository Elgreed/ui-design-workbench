#!/usr/bin/env python3
"""Generate a bounded interaction/state scenario plan from UI IR actions and states."""

from __future__ import annotations

import argparse
import copy
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from quality_common import node_screen_map, profile_catalog, read_json, target_families, write_json


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def action_step(node_id: str, action: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "activate",
        "nodeId": node_id,
        "actionType": action.get("type"),
        "target": action.get("target"),
        "state": action.get("state"),
        "offState": action.get("offState"),
    }


def expected_for(action: dict[str, Any]) -> list[str]:
    kind = action.get("type")
    if kind == "navigate":
        return [f"active screen becomes {action.get('target')}", "browser history and screen tree agree"]
    if kind == "back":
        return ["previous reachable screen is restored", "focus returns predictably"]
    if kind in {"toggle", "toggle-node-state"}:
        return [f"target alternates between {action.get('state')} and {action.get('offState', 'default')}", "visible and semantic state stay synchronized"]
    if kind == "set-node-state":
        return [f"target state becomes {action.get('state')}", "dependent controls and visible values agree"]
    if kind == "reset-state":
        return ["affected state returns to its declared default", "visible value and internal state agree"]
    return ["declared action produces visible feedback", "focus and geometry remain valid"]


def build_matrix(ir: dict[str, Any], max_pairs: int = 24) -> dict[str, Any]:
    nodes = ir.get("nodes", {})
    screen_map = node_screen_map(ir)
    by_screen: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    scenarios: list[dict[str, Any]] = []

    for node_id, node in sorted(nodes.items()):
        action = node.get("action") if isinstance(node.get("action"), dict) else {}
        if not action.get("type"):
            continue
        screens = sorted(screen_map.get(str(node_id), [])) or [None]
        for screen_id in screens:
            by_screen[str(screen_id or "global")].append((str(node_id), action))
            base = f"{screen_id or 'global'}-{node_id}-{action['type']}"
            step = action_step(str(node_id), action)
            scenarios.append({
                "id": f"single-{slug(base)}",
                "kind": "single",
                "screenId": screen_id,
                "nodeIds": [node_id],
                "startState": "declared default",
                "steps": [step],
                "assertions": expected_for(action) + ["no clipping, overlap, or unexpected scroll jump"],
            })
            scenarios.append({
                "id": f"repeat-{slug(base)}",
                "kind": "repeated",
                "screenId": screen_id,
                "nodeIds": [node_id],
                "startState": "declared default",
                "steps": [step, step],
                "assertions": expected_for(action) + ["second activation is deterministic and does not duplicate transient UI"],
            })
            if action.get("type") in {"toggle", "toggle-node-state", "set-node-state", "reset-state"}:
                scenarios.append({
                    "id": f"reverse-{slug(base)}",
                    "kind": "reverse",
                    "screenId": screen_id,
                    "nodeIds": [node_id, str(action.get("target") or node_id)],
                    "startState": "declared default",
                    "steps": [step, {"type": "reverse-or-reset", "nodeId": node_id, "target": action.get("target")}],
                    "assertions": ["initial visible, semantic, and geometry state is restored", "no stale labels, pressed states, or dependent values remain"],
                })

    pair_count = 0
    for screen_id, controls in sorted(by_screen.items()):
        for index, first in enumerate(controls):
            for second in controls[index + 1:]:
                if pair_count >= max_pairs:
                    break
                first_id, first_action = first
                second_id, second_action = second
                scenarios.append({
                    "id": f"chain-{slug(screen_id)}-{slug(first_id)}-{slug(second_id)}",
                    "kind": "chained",
                    "screenId": None if screen_id == "global" else screen_id,
                    "nodeIds": [first_id, second_id],
                    "startState": "declared default",
                    "steps": [action_step(first_id, first_action), action_step(second_id, second_action)],
                    "assertions": ["the second control resolves or composes with the first state", "only one mutually exclusive surface remains open", "focus, history, visible values, and geometry remain consistent"],
                })
                pair_count += 1
            if pair_count >= max_pairs:
                break

    for node_id, node in sorted(nodes.items()):
        if node.get("type") != "input" or node.get("inputType") != "range":
            continue
        semantics = node.get("semantics", {})
        minimum = node.get("min", semantics.get("min", 0))
        maximum = node.get("max", semantics.get("max", 100))
        midpoint = (minimum + maximum) / 2 if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) else None
        scenarios.append({
            "id": f"boundary-{slug(str(node_id))}",
            "kind": "boundary",
            "screenId": next(iter(sorted(screen_map.get(str(node_id), []))), None),
            "nodeIds": [node_id],
            "startState": "declared default",
            "steps": [{"type": "set-value", "nodeId": node_id, "value": value} for value in (minimum, midpoint, maximum) if value is not None],
            "assertions": ["visible value matches the control value at min, midpoint, and max", "dependent geometry remains inside scroll bounds"],
        })

    profiles = profile_catalog().get("profiles", {})
    required_states = sorted({state for profile in profiles.values() if profile.get("family") in target_families(ir) for state in profile.get("requiredInteractionStates", [])})
    workbench = [
        {"id": "workbench-zoom-cycle", "kind": "workbench", "steps": ["Fit", "20%", "100%", "200%", "Reset"], "assertions": ["one scale state drives geometry and label", "no card reflow or overlap", "scroll bounds match scaled canvas"]},
        {"id": "workbench-menu-exclusivity", "kind": "workbench", "steps": ["open each menu", "click outside", "Escape", "change view"], "assertions": ["at most one menu is open", "focus returns to its trigger"]},
        {"id": "workbench-panel-continuity", "kind": "workbench", "steps": ["select node", "resize panel", "hide panel", "restore panel", "change viewport"], "assertions": ["selection and scroll are preserved", "compact panels are mutually exclusive"]},
    ]
    return {
        "version": 1,
        "status": "ready" if scenarios else "empty",
        "source": {"screens": len(ir.get("screens", [])), "actionNodes": sum(1 for node in nodes.values() if node.get("action", {}).get("type"))},
        "requiredPlatformStates": required_states,
        "scenarioCount": len(scenarios) + len(workbench),
        "scenarios": scenarios + workbench,
        "limits": {"maxCrossControlPairs": max_pairs, "generatedCrossControlPairs": pair_count},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", help="Path to ui-ir.json")
    parser.add_argument("--output", required=True, help="Path for ui-interaction-matrix.json")
    parser.add_argument("--merge-output", help="Optional new IR containing review.scenarioPlan")
    parser.add_argument("--max-pairs", type=int, default=24, help="Maximum generated cross-control pairs")
    args = parser.parse_args()
    ir = read_json(args.ir)
    matrix = build_matrix(ir, max(0, args.max_pairs))
    write_json(args.output, matrix)
    if args.merge_output:
        merged = copy.deepcopy(ir)
        merged.setdefault("review", {})["scenarioPlan"] = matrix
        write_json(args.merge_output, merged)
    print(f"Interaction matrix: {matrix['scenarioCount']} scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
