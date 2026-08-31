#!/usr/bin/env python3
"""Deterministic, buildless layout model for HTML projection geometry.

The model intentionally implements the small cross-platform subset represented by
UI IR (boxes, row/column/overlay stacks, constraints and deterministic text
metrics).  It is not a reimplementation of any native platform layout engine.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any


MODEL_VERSION = "deterministic-box-v1"
_LENGTH = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:px|dp|sp|pt)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Size:
    width: float
    height: float
    complete: bool = True


def _deep_merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(base)
    for key, value in patch.items():
        result[key] = _deep_merge(result.get(key), value) if isinstance(value, dict) else copy.deepcopy(value)
    return result


class ValueResolver:
    def __init__(self, tokens: dict[str, Any] | None = None) -> None:
        self.tokens = tokens or {}

    def token(self, value: Any) -> Any:
        current = value
        seen: set[str] = set()
        while isinstance(current, str) and current.startswith("$") and current not in seen:
            seen.add(current)
            resolved: Any = self.tokens
            for part in current[1:].split("."):
                resolved = resolved.get(part) if isinstance(resolved, dict) else None
            if resolved is None:
                return current
            current = resolved.get("value", resolved) if isinstance(resolved, dict) else resolved
        return current

    def length(self, value: Any) -> float | None:
        value = self.token(value)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        if isinstance(value, str):
            match = _LENGTH.match(value.strip())
            if match:
                return float(match.group(1))
        return None

    def number(self, value: Any, default: float = 0.0) -> float:
        resolved = self.length(value)
        return resolved if resolved is not None else default


def context_key(screen_id: str, version_id: str, theme_id: str, scenario_id: str) -> str:
    return "|".join((str(screen_id), str(version_id), str(theme_id), str(scenario_id)))


def _edge_values(layout: dict[str, Any], resolver: ValueResolver, prefix: str) -> tuple[float, float, float, float]:
    all_value = resolver.number(layout.get(prefix))
    horizontal = resolver.number(layout.get(f"{prefix}Horizontal"), all_value)
    vertical = resolver.number(layout.get(f"{prefix}Vertical"), all_value)
    top = resolver.number(layout.get(f"{prefix}Top"), vertical)
    right = resolver.number(layout.get(f"{prefix}Right"), horizontal)
    bottom = resolver.number(layout.get(f"{prefix}Bottom"), vertical)
    left = resolver.number(layout.get(f"{prefix}Left"), horizontal)
    return top, right, bottom, left


class LayoutSolver:
    def __init__(self, nodes: dict[str, Any], tokens: dict[str, Any]) -> None:
        self.nodes = nodes
        self.values = ValueResolver(tokens)
        self.rects: dict[str, dict[str, float]] = {}
        self.diagnostics: list[str] = []

    def solve(self, root_id: str, width: float, height: float) -> dict[str, Any]:
        if root_id not in self.nodes:
            return {"status": "partial", "nodes": {}, "diagnostics": [f"missing-root:{root_id}"]}
        measured = self._measure(root_id, width, height, width, height, set())
        self._layout(root_id, 0.0, 0.0, measured.width, measured.height, set())
        reachable = self._reachable(root_id)
        missing = sorted(reachable - self.rects.keys())
        if missing:
            self.diagnostics.append(f"unsolved-nodes:{','.join(missing)}")
        status = "solved" if measured.complete and not missing else "partial"
        return {
            "status": status,
            "nodes": self.rects,
            "diagnostics": list(dict.fromkeys(self.diagnostics)),
        }

    def _reachable(self, root_id: str) -> set[str]:
        result: set[str] = set()
        stack = [root_id]
        while stack:
            node_id = stack.pop()
            if node_id in result or node_id not in self.nodes:
                continue
            result.add(node_id)
            stack.extend(str(child) for child in self.nodes[node_id].get("children", []))
        return result

    def _dimension(self, layout: dict[str, Any], axis: str, available: float | None, forced: float | None) -> float | None:
        if forced is not None:
            return max(0.0, forced)
        raw = layout.get(axis)
        explicit = self.values.length(raw)
        if explicit is not None:
            return max(0.0, explicit)
        if raw == "fill" and available is not None:
            return max(0.0, available)
        return None

    def _clamp(self, value: float, layout: dict[str, Any], axis: str) -> float:
        minimum = self.values.length(layout.get(f"min{axis.title()}"))
        maximum = self.values.length(layout.get(f"max{axis.title()}"))
        if minimum is not None:
            value = max(value, minimum)
        if maximum is not None:
            value = min(value, maximum)
        return max(0.0, value)

    def _typography(self, node: dict[str, Any]) -> tuple[float, float, float]:
        style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
        typography = self.values.token(style.get("typography"))
        typography = typography if isinstance(typography, dict) else {}
        font_size = self.values.length(style.get("fontSize", typography.get("fontSize"))) or 16.0
        line_height = self.values.length(style.get("lineHeight", typography.get("lineHeight"))) or font_size * 1.2
        letter_spacing = self.values.length(style.get("letterSpacing", typography.get("letterSpacing"))) or 0.0
        return font_size, line_height, letter_spacing

    def _text_size(self, node: dict[str, Any], max_width: float | None) -> Size:
        text = str(node.get("text") or node.get("value") or node.get("placeholder") or "")
        font_size, line_height, letter_spacing = self._typography(node)
        lines = text.splitlines() or [""]
        glyph_width = max(1.0, font_size * 0.55 + letter_spacing)
        natural_width = max((len(line) * glyph_width for line in lines), default=0.0)
        if max_width is not None and max_width > 0:
            wrapped_lines = sum(max(1, math.ceil((len(line) * glyph_width) / max_width)) for line in lines)
            width = min(natural_width, max_width)
        else:
            wrapped_lines = len(lines)
            width = natural_width
        return Size(width, max(line_height, wrapped_lines * line_height))

    def _leaf_content_size(self, node: dict[str, Any], max_width: float | None) -> Size:
        node_type = node.get("type")
        if node_type in {"text", "button", "input"}:
            return self._text_size(node, max_width)
        if node_type == "icon":
            font_size, _, _ = self._typography(node)
            return Size(font_size, font_size)
        if node_type in {"spacer", "divider"}:
            return Size(0.0, 0.0)
        if node_type == "image":
            return Size(0.0, 0.0, False)
        if node_type == "custom":
            return Size(0.0, 0.0, False)
        return Size(0.0, 0.0)

    def _measure(
        self,
        node_id: str,
        available_width: float | None,
        available_height: float | None,
        forced_width: float | None = None,
        forced_height: float | None = None,
        stack: set[str] | None = None,
    ) -> Size:
        stack = set(stack or ())
        if node_id in stack or node_id not in self.nodes:
            self.diagnostics.append(f"invalid-tree:{node_id}")
            return Size(0.0, 0.0, False)
        stack.add(node_id)
        node = self.nodes[node_id]
        layout = node.get("layout", {}) if isinstance(node.get("layout"), dict) else {}
        padding_top, padding_right, padding_bottom, padding_left = _edge_values(layout, self.values, "padding")
        width = self._dimension(layout, "width", available_width, forced_width)
        height = self._dimension(layout, "height", available_height, forced_height)
        inner_width = max(0.0, width - padding_left - padding_right) if width is not None else (
            max(0.0, available_width - padding_left - padding_right) if available_width is not None else None
        )
        inner_height = max(0.0, height - padding_top - padding_bottom) if height is not None else (
            max(0.0, available_height - padding_top - padding_bottom) if available_height is not None else None
        )
        children = [str(child) for child in node.get("children", []) if str(child) in self.nodes]
        direction = layout.get("direction") or ("column" if children else None)
        complete = True
        content_width = content_height = 0.0

        if children and direction in {"row", "column", "overlay"}:
            child_sizes: list[tuple[Size, tuple[float, float, float, float], dict[str, Any]]] = []
            for child_id in children:
                child = self.nodes[child_id]
                child_layout = child.get("layout", {}) if isinstance(child.get("layout"), dict) else {}
                margins = _edge_values(child_layout, self.values, "margin")
                child_size = self._measure(child_id, inner_width, inner_height, None, None, stack)
                child_sizes.append((child_size, margins, child_layout))
                complete = complete and child_size.complete
            gap = self.values.number(layout.get("gap"))
            if direction == "row":
                flow = [item for item in child_sizes if item[2].get("position") != "absolute"]
                content_width = sum(size.width + margins[1] + margins[3] for size, margins, _ in flow) + gap * max(0, len(flow) - 1)
                content_height = max((size.height + margins[0] + margins[2] for size, margins, _ in child_sizes), default=0.0)
            elif direction == "column":
                flow = [item for item in child_sizes if item[2].get("position") != "absolute"]
                content_width = max((size.width + margins[1] + margins[3] for size, margins, _ in child_sizes), default=0.0)
                content_height = sum(size.height + margins[0] + margins[2] for size, margins, _ in flow) + gap * max(0, len(flow) - 1)
            else:
                content_width = max((size.width + margins[1] + margins[3] for size, margins, _ in child_sizes), default=0.0)
                content_height = max((size.height + margins[0] + margins[2] for size, margins, _ in child_sizes), default=0.0)
        elif children:
            self.diagnostics.append(f"unsupported-direction:{node_id}:{direction}")
            complete = False
        else:
            leaf = self._leaf_content_size(node, inner_width)
            content_width, content_height, complete = leaf.width, leaf.height, leaf.complete

        if width is None:
            width = content_width + padding_left + padding_right
        if height is None:
            height = content_height + padding_top + padding_bottom
        aspect_ratio = self.values.length(layout.get("aspectRatio"))
        if aspect_ratio and aspect_ratio > 0:
            raw_width, raw_height = layout.get("width"), layout.get("height")
            if raw_width not in (None, "hug") and raw_height in (None, "hug"):
                height = width / aspect_ratio
            elif raw_height not in (None, "hug") and raw_width in (None, "hug"):
                width = height * aspect_ratio
        width = self._clamp(width, layout, "width")
        height = self._clamp(height, layout, "height")
        explicit_box = self._dimension(layout, "width", available_width, forced_width) is not None and self._dimension(layout, "height", available_height, forced_height) is not None
        return Size(width, height, complete or explicit_box)

    def _axis_position(self, alignment: str, available: float, size: float, start_margin: float, end_margin: float) -> float:
        if alignment in {"center"}:
            return max(start_margin, (available - size) / 2.0)
        if alignment in {"end", "flex-end"}:
            return max(start_margin, available - size - end_margin)
        return start_margin

    def _layout(self, node_id: str, x: float, y: float, width: float, height: float, stack: set[str]) -> None:
        if node_id in stack or node_id not in self.nodes:
            return
        stack = set(stack)
        stack.add(node_id)
        self.rects[node_id] = {key: round(value, 4) for key, value in {"x": x, "y": y, "width": width, "height": height}.items()}
        node = self.nodes[node_id]
        layout = node.get("layout", {}) if isinstance(node.get("layout"), dict) else {}
        children = [str(child) for child in node.get("children", []) if str(child) in self.nodes]
        direction = layout.get("direction") or ("column" if children else None)
        if not children or direction not in {"row", "column", "overlay"}:
            return
        padding_top, padding_right, padding_bottom, padding_left = _edge_values(layout, self.values, "padding")
        inner_width = max(0.0, width - padding_left - padding_right)
        inner_height = max(0.0, height - padding_top - padding_bottom)
        horizontal = direction == "row"
        inner_main = inner_width if horizontal else inner_height
        inner_cross = inner_height if horizontal else inner_width
        gap = self.values.number(layout.get("gap"))
        entries: list[dict[str, Any]] = []
        for child_id in children:
            child_layout = self.nodes[child_id].get("layout", {}) if isinstance(self.nodes[child_id].get("layout"), dict) else {}
            margins = _edge_values(child_layout, self.values, "margin")
            natural = self._measure(child_id, inner_width, inner_height, None, None, stack)
            main_spec = child_layout.get("width" if horizontal else "height")
            cross_spec = child_layout.get("height" if horizontal else "width")
            grow = self.values.number(child_layout.get("grow"), 0.0)
            if main_spec == "fill" and grow <= 0:
                grow = 1.0
            entries.append({"id": child_id, "layout": child_layout, "margins": margins, "size": natural, "grow": grow, "mainSpec": main_spec, "crossSpec": cross_spec})

        if direction == "overlay":
            for entry in entries:
                top, right, bottom, left = entry["margins"]
                child_width = entry["size"].width
                child_height = entry["size"].height
                authored_left = self.values.length(entry["layout"].get("left"))
                authored_right = self.values.length(entry["layout"].get("right"))
                authored_top = self.values.length(entry["layout"].get("top"))
                authored_bottom = self.values.length(entry["layout"].get("bottom"))
                if entry["crossSpec"] == "fill" or entry["layout"].get("alignSelf") == "stretch" or (authored_left is not None and authored_right is not None):
                    child_width = max(0.0, inner_width - left - right)
                    if authored_left is not None and authored_right is not None:
                        child_width = max(0.0, inner_width - authored_left - authored_right - left - right)
                if entry["mainSpec"] == "fill" or entry["layout"].get("justifySelf") == "stretch" or (authored_top is not None and authored_bottom is not None):
                    child_height = max(0.0, inner_height - top - bottom)
                    if authored_top is not None and authored_bottom is not None:
                        child_height = max(0.0, inner_height - authored_top - authored_bottom - top - bottom)
                if entry["layout"].get("position") == "absolute" and (authored_left is not None or authored_right is not None):
                    child_x = padding_left + (authored_left + left if authored_left is not None else inner_width - child_width - (authored_right or 0.0) - right)
                else:
                    child_x = padding_left + self._axis_position(entry["layout"].get("justifySelf") or layout.get("justify", "start"), inner_width, child_width, left, right)
                if entry["layout"].get("position") == "absolute" and (authored_top is not None or authored_bottom is not None):
                    child_y = padding_top + (authored_top + top if authored_top is not None else inner_height - child_height - (authored_bottom or 0.0) - bottom)
                else:
                    child_y = padding_top + self._axis_position(entry["layout"].get("alignSelf") or layout.get("align", "start"), inner_height, child_height, top, bottom)
                self._layout(entry["id"], child_x, child_y, child_width, child_height, stack)
            return

        flow = [entry for entry in entries if entry["layout"].get("position") != "absolute"]
        fixed = 0.0
        total_grow = 0.0
        for entry in flow:
            top, right, bottom, left = entry["margins"]
            margin_main = left + right if horizontal else top + bottom
            if entry["grow"] > 0:
                total_grow += entry["grow"]
                fixed += margin_main + (self.values.length(entry["layout"].get("flexBasis")) or 0.0)
            else:
                fixed += margin_main + (entry["size"].width if horizontal else entry["size"].height)
        base_gap = gap * max(0, len(flow) - 1)
        remaining = max(0.0, inner_main - fixed - base_gap)
        justify = layout.get("justify", "start")
        lead = 0.0
        actual_gap = gap
        occupied = fixed + base_gap + (remaining if total_grow > 0 else 0.0)
        free = max(0.0, inner_main - occupied)
        if total_grow <= 0:
            if justify == "center":
                lead = free / 2.0
            elif justify == "end":
                lead = free
            elif justify == "between" and len(flow) > 1:
                actual_gap = gap + free / (len(flow) - 1)
            elif justify == "around" and flow:
                actual_gap = gap + free / len(flow)
                lead = (actual_gap - gap) / 2.0
            elif justify == "evenly" and flow:
                actual_gap = gap + free / (len(flow) + 1)
                lead = actual_gap - gap
        cursor = lead
        for entry in flow:
            top, right, bottom, left = entry["margins"]
            margin_before = left if horizontal else top
            margin_after = right if horizontal else bottom
            cursor += margin_before
            natural_main = entry["size"].width if horizontal else entry["size"].height
            main_size = natural_main
            if entry["grow"] > 0 and total_grow > 0:
                basis = self.values.length(entry["layout"].get("flexBasis")) or 0.0
                main_size = basis + remaining * entry["grow"] / total_grow
            natural_cross = entry["size"].height if horizontal else entry["size"].width
            cross_before, cross_after = (top, bottom) if horizontal else (left, right)
            align = entry["layout"].get("alignSelf") or layout.get("align") or "stretch"
            cross_size = natural_cross
            if entry["crossSpec"] == "fill" or align == "stretch" and entry["crossSpec"] is None:
                cross_size = max(0.0, inner_cross - cross_before - cross_after)
            cross_pos = self._axis_position(align, inner_cross, cross_size, cross_before, cross_after)
            child_width, child_height = (main_size, cross_size) if horizontal else (cross_size, main_size)
            child_x = padding_left + (cursor if horizontal else cross_pos)
            child_y = padding_top + (cross_pos if horizontal else cursor)
            self._layout(entry["id"], child_x, child_y, child_width, child_height, stack)
            cursor += main_size + margin_after + actual_gap

        for entry in entries:
            if entry["layout"].get("position") != "absolute":
                continue
            top, right, bottom, left = entry["margins"]
            child_width, child_height = entry["size"].width, entry["size"].height
            authored_left = self.values.length(entry["layout"].get("left"))
            authored_right = self.values.length(entry["layout"].get("right"))
            authored_top = self.values.length(entry["layout"].get("top"))
            authored_bottom = self.values.length(entry["layout"].get("bottom"))
            if entry["layout"].get("width") == "fill" or (authored_left is not None and authored_right is not None):
                child_width = max(0.0, inner_width - (authored_left or 0.0) - (authored_right or 0.0))
            if entry["layout"].get("height") == "fill" or (authored_top is not None and authored_bottom is not None):
                child_height = max(0.0, inner_height - (authored_top or 0.0) - (authored_bottom or 0.0))
            child_x = padding_left + (authored_left if authored_left is not None else max(0.0, inner_width - child_width - (authored_right or 0.0))) + left
            child_y = padding_top + (authored_top if authored_top is not None else max(0.0, inner_height - child_height - (authored_bottom or 0.0))) + top
            self._layout(entry["id"], child_x, child_y, child_width, child_height, stack)


def _version_chain(review: dict[str, Any], version_id: str) -> list[dict[str, Any]]:
    versions = review.get("versions", []) if isinstance(review.get("versions"), list) else []
    by_id = {str(item.get("id")): item for item in versions if item.get("id")}
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = by_id.get(version_id)
    while current and str(current.get("id")) not in seen:
        seen.add(str(current["id"]))
        chain.insert(0, current)
        current = by_id.get(str(current.get("parent"))) if current.get("parent") else None
    return chain


def _screen_scenarios(ir: dict[str, Any], screen: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures = ir.get("scenarioFixtures", {}) if isinstance(ir.get("scenarioFixtures"), dict) else {}
    result = [{"id": "default", "nodeStates": {}, "nodeOverrides": {}}]
    for item in screen.get("scenarios", []) if isinstance(screen.get("scenarios"), list) else []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        fixture = fixtures.get(item.get("fixtureRef"), {}) if item.get("fixtureRef") else {}
        fixture = fixture if isinstance(fixture, dict) else {}
        result.append(_deep_merge(fixture, item))
    return result[:12]


def _materialize(
    ir: dict[str, Any],
    version: dict[str, Any],
    theme: dict[str, Any],
    scenario: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = copy.deepcopy(ir.get("nodes", {}))
    review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
    overrides: list[dict[str, Any]] = []
    overrides.append(theme.get("nodeOverrides", {}) if isinstance(theme.get("nodeOverrides"), dict) else {})
    for item in _version_chain(review, str(version.get("id", "baseline"))):
        overrides.append(item.get("nodeOverrides", {}) if isinstance(item.get("nodeOverrides"), dict) else {})
    overrides.append(scenario.get("nodeOverrides", {}) if isinstance(scenario.get("nodeOverrides"), dict) else {})
    for mapping in overrides:
        for node_id, patch in mapping.items():
            if node_id in nodes and isinstance(patch, dict):
                nodes[node_id] = _deep_merge(nodes[node_id], patch)
    node_states = scenario.get("nodeStates", {}) if isinstance(scenario.get("nodeStates"), dict) else {}
    for node_id, state_id in node_states.items():
        if node_id not in nodes:
            continue
        variant = nodes[node_id].get("states", {}).get(state_id)
        if isinstance(variant, dict):
            nodes[node_id] = _deep_merge(nodes[node_id], variant)
    tokens = _deep_merge(ir.get("tokens", {}), theme.get("tokenOverrides", {}))
    return nodes, tokens


def validate_projection_geometry(projection: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for context_id, context in projection.get("contexts", {}).items():
        for node_id, rect in context.get("nodes", {}).items():
            for field in ("x", "y", "width", "height"):
                value = rect.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    errors.append(f"{context_id}:{node_id}:{field}:not-finite")
            if isinstance(rect.get("width"), (int, float)) and rect["width"] < 0:
                errors.append(f"{context_id}:{node_id}:negative-width")
            if isinstance(rect.get("height"), (int, float)) and rect["height"] < 0:
                errors.append(f"{context_id}:{node_id}:negative-height")
    return errors


def build_projection_geometry(ir: dict[str, Any]) -> dict[str, Any]:
    """Build projection-only geometry without mutating the supplied IR."""
    viewport_default = ir.get("viewport", {}) if isinstance(ir.get("viewport"), dict) else {}
    themes_config = ir.get("themes", {}) if isinstance(ir.get("themes"), dict) else {}
    themes = themes_config.get("items", []) if isinstance(themes_config.get("items"), list) else []
    themes = themes or [{"id": "light", "tokenOverrides": {}, "nodeOverrides": {}}]
    review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
    versions = review.get("versions", []) if isinstance(review.get("versions"), list) else []
    versions = versions or [{"id": "baseline", "nodeOverrides": {}}]
    projection: dict[str, Any] = {"version": 1, "model": MODEL_VERSION, "contexts": {}}
    for screen in ir.get("screens", []):
        viewport = {**viewport_default, **(screen.get("viewport", {}) if isinstance(screen.get("viewport"), dict) else {})}
        width = ValueResolver().length(viewport.get("width")) or 390.0
        height = ValueResolver().length(viewport.get("height")) or 844.0
        for version in versions:
            for theme in themes:
                for scenario in _screen_scenarios(ir, screen):
                    nodes, tokens = _materialize(ir, version, theme, scenario)
                    solved = LayoutSolver(nodes, tokens).solve(str(screen.get("root", "")), width, height)
                    key = context_key(str(screen.get("id", "")), str(version.get("id", "baseline")), str(theme.get("id", "light")), str(scenario.get("id", "default")))
                    projection["contexts"][key] = {
                        "screenId": screen.get("id"),
                        "versionId": version.get("id", "baseline"),
                        "themeId": theme.get("id", "light"),
                        "scenarioId": scenario.get("id", "default"),
                        **solved,
                    }
    errors = validate_projection_geometry(projection)
    assert not errors, "Invalid deterministic projection geometry: " + "; ".join(errors[:8])
    return projection
