#!/usr/bin/env python3
"""Built-in platform adapters beyond static Web and Jetpack Compose."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from android_resource_resolver import AndroidResourceCatalog
from android_xml_support import android_layout_metadata
from apple_resource_resolver import AppleResourceCatalog, sf_symbol_asset
from fidelity_adapter_api import AdapterResult, SourceContext
from fidelity_core import property_evidence
from platform_component_catalog import adapter_type_map


def _slug(value: str, fallback: str = "node") -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", value)
    return re.sub(r"[^a-z0-9]+", "-", separated.lower()).strip("-") or fallback


def _local(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attrs(element: ET.Element) -> dict[str, str]:
    return {_local(key): str(value) for key, value in element.attrib.items()}


def _line(text: str, expression: str, start: int = 0) -> int:
    offset = text.find(expression, start)
    return text.count("\n", 0, max(0, offset)) + 1 if offset >= 0 else 1


def _balanced_close(text: str, start: int, opening: str, closing: str) -> int | None:
    depth, quote, escaped = 0, None, False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _normalize_ref(value: str, preferred_group: str = "spacing") -> Any:
    value = value.strip()
    if value in {"match_parent", "-1"}: return "fill"
    if value in {"wrap_content", "Auto"}: return "hug"
    numeric = re.fullmatch(r"-?\d+(?:\.\d+)?", value)
    if numeric: return float(value) if "." in value else int(value)
    dimension = re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:dp|sp|pt)", value)
    if dimension: return f"{dimension.group(1)}px"
    match = re.fullmatch(r"@(color|dimen|string)/([\w.-]+)", value)
    if match:
        resource_type, resource_name = match.groups()
        group = "colors" if resource_type == "color" else "strings" if resource_type == "string" else preferred_group
        return f"${group}.{_slug(resource_name).replace('-', '_')}"
    match = re.fullmatch(r"\{(?:StaticResource|ThemeResource)\s+([\w.-]+)\}", value)
    if match:
        return f"${preferred_group}.{_slug(match.group(1)).replace('-', '_')}"
    return value


def _set(node: dict[str, Any], path: str, value: Any, context: SourceContext, line: int, expression: str, adapter: str, confidence: str = "exact") -> None:
    group, key = path.split(".", 1)
    node.setdefault(group, {})[key] = value
    node.setdefault("provenance", {})[path] = property_evidence(context.source, line, expression, adapter, confidence)


def _root_node(context: SourceContext, adapter: str, standard: str, line: int = 1) -> dict[str, Any]:
    return {
        "type": "container", "layout": {"direction": "column", "width": "fill", "height": "fill"}, "style": {}, "children": [],
        "source": {"file": context.source, "line": line}, "confidence": "high", "standardRef": standard,
        "provenance": {
            "layout.direction": property_evidence(context.source, line, "screen root", adapter, "high"),
            "layout.width": property_evidence(context.source, line, "screen bounds", adapter, "high"),
            "layout.height": property_evidence(context.source, line, "screen bounds", adapter, "high"),
        },
    }


class AndroidXmlAdapter:
    id = "android-xml"
    platforms = ("android",)
    extensions = (".xml",)
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "deterministic-projection"
    native_evidence_required = True
    native_providers = ("paparazzi", "roborazzi", "android-emulator")
    resource_resolution = ("values strings/colors/dimens", "styles", "bitmap/vector/shape drawables", "static layout includes")
    layout_features = ("LinearLayout gravity/weight", "Frame/Constraint overlay", "parent-edge centering", "directional padding/margins", "image scaleType")
    limitations = ("custom views are not expanded", "complex ConstraintLayout equations and runtime resources remain explicit gaps")
    TYPES = {
        "LinearLayout": "container", "ConstraintLayout": "container", "FrameLayout": "container", "RelativeLayout": "container",
        "CoordinatorLayout": "container", "AppBarLayout": "container", "Toolbar": "container", "MaterialToolbar": "container",
        "ScrollView": "container", "NestedScrollView": "container", "HorizontalScrollView": "container", "ViewPager": "container",
        "ViewPager2": "container", "SwipeRefreshLayout": "container", "DrawerLayout": "container", "NavigationView": "container",
        "RecyclerView": "list", "ListView": "list", "GridView": "list", "TabLayout": "container",
        "TextView": "text", "AppCompatTextView": "text", "MaterialTextView": "text", "Button": "button",
        "AppCompatButton": "button", "MaterialButton": "button", "FloatingActionButton": "button", "ExtendedFloatingActionButton": "button",
        "EditText": "input", "AppCompatEditText": "input", "TextInputEditText": "input", "TextInputLayout": "container",
        "CheckBox": "button", "RadioButton": "button", "Switch": "button", "SwitchMaterial": "button", "Chip": "button",
        "MaterialCheckBox": "button", "MaterialSwitch": "button", "CheckedTextView": "button", "RadioGroup": "container",
        "MaterialButtonToggleGroup": "container", "GridLayout": "container", "ShimmerFrameLayout": "container", "SearchView": "input",
        "ImageView": "image", "AppCompatImageView": "image", "ShapeableImageView": "image", "ImageButton": "button",
        "AppCompatImageButton": "button", "CardView": "card", "MaterialCardView": "card", "View": "divider", "Space": "spacer",
        "ProgressBar": "custom", "Guideline": "spacer", "Barrier": "spacer", "Group": "container",
    }
    TYPES.update(adapter_type_map("android", "android-xml"))

    def __init__(self) -> None:
        self._catalogs: dict[str, AndroidResourceCatalog] = {}

    def prepare(self, contexts: list[SourceContext]) -> None:
        roots = {str(context.root.resolve()): context.root for context in contexts if self.supports(context)}
        self._catalogs = {key: AndroidResourceCatalog.discover(root) for key, root in roots.items()}

    def _catalog(self, context: SourceContext) -> AndroidResourceCatalog:
        key = str(context.root.resolve())
        if key not in self._catalogs:
            self._catalogs[key] = AndroidResourceCatalog.discover(context.root)
        return self._catalogs[key]

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".xml" and any(value.startswith("android-") for value in context.platforms)

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
        catalog = self._catalog(context)
        try:
            root = ET.fromstring(context.text)
        except ET.ParseError as exc:
            result.unsupported.append({"adapter": self.id, "file": context.source, "line": getattr(exc, "position", (1,))[0], "expression": str(exc), "reason": "invalid-xml"})
            return result
        normalized_source = "/" + context.source.lower().replace("\\", "/")
        if "/res/color" in normalized_source:
            items = [child for child in root if _local(child.tag) == "item"] if _local(root.tag) == "selector" else []
            default_item = next((child for child in reversed(items) if not any(key.startswith("state_") for key in _attrs(child))), None)
            selected = default_item if default_item is not None else items[-1] if items else root
            value = _attrs(selected).get("color") or (selected.text or "").strip()
            if value:
                result.tokens["colors"][_slug(context.path.stem).replace("-", "_")] = {
                    "value": _normalize_ref(value, "colors"),
                    "source": {"file": context.source, "line": _line(context.text, value)},
                    "adapter": self.id,
                }
            if len(items) > 1:
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": 1, "expression": context.path.name, "reason": "stateful-color-selector-uses-default-state"})
            return result
        if _local(root.tag) == "resources":
            for child in root:
                tag, attrs, value = _local(child.tag), _attrs(child), (child.text or "").strip()
                name = attrs.get("name") or attrs.get("Key")
                if not name:
                    continue
                line = _line(context.text, name)
                if tag == "style":
                    result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": name, "reason": "unresolved-android-style"})
                    continue
                if not value:
                    continue
                if tag in {"color", "Color", "SolidColorBrush"}:
                    groups = ("colors",)
                elif tag == "dimen":
                    groups = ("spacing", "typography") if value.endswith("sp") else ("spacing",)
                elif tag in {"string", "plurals", "string-array"}:
                    groups = ("strings",)
                elif tag in {"bool", "integer", "fraction"}:
                    groups = ("values",)
                else:
                    continue
                for group in groups:
                    result.tokens.setdefault(group, {})[_slug(name).replace("-", "_")] = {
                        "value": _normalize_ref(value, group),
                        "source": {"file": context.source, "line": line},
                        "adapter": self.id,
                    }
            if "/values-night" in "/" + context.source.lower().replace("\\", "/"):
                result.themes.append({"id": "dark", "label": "Dark", "kind": "dark", "sourceRefs": [{"file": context.source, "line": 1, "reason": "values-night"}], "tokenOverrides": result.tokens, "nodeOverrides": {}})
                result.tokens = {group: {} for group in result.tokens}
            return result
        if context.role == "navigation":
            return result
        content_root = root
        if _local(root.tag) == "layout":
            content_root = next((child for child in root if isinstance(child.tag, str) and _local(child.tag) != "data"), None)
            if content_root is None:
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": 1, "expression": "<layout>", "reason": "data-binding-layout-without-view-root"})
                return result
        platform = "android"
        screen_id = _slug(context.path.stem, "android-layout")
        root_id = f"{screen_id}-root"
        result.nodes[root_id] = _root_node(context, self.id, "project.android.layout")
        count = 0

        def convert(element: ET.Element, active_context: SourceContext, active_text: str, include_stack: tuple[str, ...] = ()) -> str:
            nonlocal count
            count += 1
            raw_tag, explicit_attrs = _local(element.tag), _attrs(element)
            if raw_tag == "include":
                reference = explicit_attrs.get("layout", "")
                line = _line(active_text, reference or "<include")
                node_id = f"{screen_id}-include-{count}"
                node = {
                    "type": "container", "component": "include", "layout": {"width": "fill"}, "style": {}, "children": [],
                    "source": {"file": active_context.source, "line": line}, "confidence": "high", "standardRef": "project.android.include",
                    "provenance": {
                        "component": property_evidence(active_context.source, line, reference or "include", self.id, "exact"),
                        "layout.width": property_evidence(active_context.source, line, reference or "include", self.id, "high"),
                    },
                }
                target = catalog.layout(reference)
                if not target or reference in include_stack:
                    result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": reference, "reason": "unresolved-or-cyclic-layout-include"})
                else:
                    try:
                        target_text = target.read_text(encoding="utf-8", errors="replace")
                        target_root = ET.fromstring(target_text)
                        target_context = SourceContext(active_context.root, target, target.relative_to(active_context.root).as_posix(), target_text, active_context.platforms, "component")
                        candidates = list(target_root) if _local(target_root.tag) == "merge" else [target_root]
                        node["children"] = [convert(child, target_context, target_text, (*include_stack, reference)) for child in candidates]
                    except (OSError, ET.ParseError, ValueError) as exc:
                        result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": reference, "reason": f"invalid-layout-include:{type(exc).__name__}"})
                result.nodes[node_id] = node
                return node_id
            style_values, style_entry = catalog.style(explicit_attrs.get("style"))
            normalized_style = {key.rsplit(":", 1)[-1]: value for key, value in style_values.items()}
            attrs = {**normalized_style, **explicit_attrs}
            short = raw_tag.rsplit(".", 1)[-1]
            node_id = f"{screen_id}-{_slug(attrs.get('id', '').split('/')[-1] or short)}-{count}"
            node_type = self.TYPES.get(short, "custom")
            line = _line(active_text, f"<{raw_tag}")
            standard_prefix = "material3" if short.startswith("Material") or "TextInput" in short else "project"
            node: dict[str, Any] = {
                "type": node_type, "component": raw_tag, "layout": {}, "style": {}, "children": [], "source": {"file": active_context.source, "line": line},
                "confidence": "high" if node_type != "custom" else "unsupported", "standardRef": f"{standard_prefix}.android-xml.{short.lower()}", "provenance": {},
            }
            if node_type != "custom":
                node["inheritsAppearance"] = True
                node["provenance"]["component"] = property_evidence(active_context.source, line, raw_tag, self.id, "exact")
            else:
                result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": raw_tag, "reason": "unsupported-android-view"})
            if short in {"FrameLayout", "ConstraintLayout", "CoordinatorLayout"}:
                _set(node, "layout.direction", "overlay", active_context, line, short, self.id)
            mapping = {
                "layout_width": ("layout.width", "spacing"), "layout_height": ("layout.height", "spacing"), "padding": ("layout.padding", "spacing"),
                "paddingHorizontal": ("layout.paddingHorizontal", "spacing"), "paddingVertical": ("layout.paddingVertical", "spacing"),
                "paddingStart": ("layout.paddingLeft", "spacing"), "paddingEnd": ("layout.paddingRight", "spacing"), "paddingTop": ("layout.paddingTop", "spacing"), "paddingBottom": ("layout.paddingBottom", "spacing"),
                "layout_margin": ("layout.margin", "spacing"), "layout_marginHorizontal": ("layout.marginHorizontal", "spacing"), "layout_marginVertical": ("layout.marginVertical", "spacing"),
                "layout_marginStart": ("layout.marginLeft", "spacing"), "layout_marginEnd": ("layout.marginRight", "spacing"), "layout_marginTop": ("layout.marginTop", "spacing"), "layout_marginBottom": ("layout.marginBottom", "spacing"),
                "minWidth": ("layout.minWidth", "spacing"), "minHeight": ("layout.minHeight", "spacing"), "maxWidth": ("layout.maxWidth", "spacing"), "maxHeight": ("layout.maxHeight", "spacing"),
                "textColor": ("style.color", "color"), "textSize": ("style.fontSize", "dimen"), "alpha": ("style.opacity", "spacing"), "fontFamily": ("style.fontFamily", "font"),
                "tint": ("style.color", "color"),
            }
            for attr, (path, group) in mapping.items():
                if attr in attrs:
                    resolved = catalog.resolve(attrs[attr], group, normalized_style)
                    value = resolved.value if resolved.resolved else _normalize_ref(attrs[attr], "colors" if group == "color" else group)
                    source = resolved.source or (style_entry.source if attr not in explicit_attrs and style_entry else active_context.source)
                    source_line = resolved.line if resolved.source else style_entry.line if attr not in explicit_attrs and style_entry else line
                    group_name, key = path.split(".", 1)
                    node.setdefault(group_name, {})[key] = value
                    node["provenance"][path] = property_evidence(source, source_line, f'{attr}="{attrs[attr]}"', self.id, resolved.confidence if resolved.source else "exact")
            if attrs.get("orientation") in {"vertical", "horizontal"}:
                _set(node, "layout.direction", "column" if attrs["orientation"] == "vertical" else "row", active_context, line, f'orientation="{attrs["orientation"]}"', self.id)
            direction = node.get("layout", {}).get("direction", "column")
            gravity = attrs.get("gravity", "")
            if gravity:
                if "center" == gravity or "center_horizontal" in gravity:
                    _set(node, "layout.align" if direction == "column" else "layout.justify", "center", active_context, line, f'gravity="{gravity}"', self.id)
                if "center" == gravity or "center_vertical" in gravity:
                    _set(node, "layout.justify" if direction == "column" else "layout.align", "center", active_context, line, f'gravity="{gravity}"', self.id)
                if "end" in gravity or "right" in gravity:
                    _set(node, "layout.align" if direction == "column" else "layout.justify", "end", active_context, line, f'gravity="{gravity}"', self.id)
            layout_gravity = attrs.get("layout_gravity", "")
            if "center" in layout_gravity:
                _set(node, "layout.alignSelf", "center", active_context, line, f'layout_gravity="{layout_gravity}"', self.id)
                _set(node, "layout.justifySelf", "center", active_context, line, f'layout_gravity="{layout_gravity}"', self.id)
            if attrs.get("layout_weight"):
                _set(node, "layout.grow", _normalize_ref(attrs["layout_weight"]), active_context, line, f'layout_weight="{attrs["layout_weight"]}"', self.id)
            text_style = attrs.get("textStyle", "")
            if "bold" in text_style:
                _set(node, "style.fontWeight", 700, active_context, line, f'textStyle="{text_style}"', self.id)
            if "italic" in text_style:
                _set(node, "style.fontStyle", "italic", active_context, line, f'textStyle="{text_style}"', self.id)
            text_alignment = {"center": "center", "viewStart": "start", "textStart": "start", "viewEnd": "end", "textEnd": "end"}.get(attrs.get("textAlignment", ""))
            if text_alignment:
                _set(node, "style.textAlign", text_alignment, active_context, line, f'textAlignment="{attrs["textAlignment"]}"', self.id)
            constraints = {key: value for key, value in attrs.items() if key.startswith("layout_constraint")}
            if constraints:
                result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": ", ".join(sorted(constraints)), "reason": "unresolved-constraint-equations"})
            horizontal_center = constraints.get("layout_constraintStart_toStartOf") == "parent" and constraints.get("layout_constraintEnd_toEndOf") == "parent"
            vertical_center = constraints.get("layout_constraintTop_toTopOf") == "parent" and constraints.get("layout_constraintBottom_toBottomOf") == "parent"
            if horizontal_center:
                _set(node, "layout.justifySelf", "stretch" if attrs.get("layout_width") == "0dp" else "center", active_context, line, "horizontal parent constraints", self.id, "high")
                if attrs.get("layout_width") == "0dp": node["layout"]["width"] = "fill"
            if vertical_center:
                _set(node, "layout.alignSelf", "stretch" if attrs.get("layout_height") == "0dp" else "center", active_context, line, "vertical parent constraints", self.id, "high")
                if attrs.get("layout_height") == "0dp": node["layout"]["height"] = "fill"
            unsupported_constraints = [key for key in constraints if key not in {"layout_constraintStart_toStartOf", "layout_constraintEnd_toEndOf", "layout_constraintTop_toTopOf", "layout_constraintBottom_toBottomOf"}]
            if unsupported_constraints:
                result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": ", ".join(sorted(unsupported_constraints)), "reason": "unsupported-constraint-equation"})
            if attrs.get("text"):
                resolved = catalog.resolve(attrs["text"], "string", normalized_style)
                node["text"] = resolved.value if resolved.resolved else _normalize_ref(attrs["text"], "strings")
                node["provenance"]["text"] = property_evidence(resolved.source or active_context.source, resolved.line if resolved.source else line, f'text="{attrs["text"]}"', self.id, resolved.confidence if resolved.source else "exact")
            if attrs.get("hint"):
                resolved = catalog.resolve(attrs["hint"], "string", normalized_style)
                node["placeholder"] = resolved.value if resolved.resolved else attrs["hint"]
                node["provenance"]["placeholder"] = property_evidence(resolved.source or active_context.source, resolved.line if resolved.source else line, f'hint="{attrs["hint"]}"', self.id, resolved.confidence if resolved.source else "exact")
            if attrs.get("contentDescription"):
                resolved = catalog.resolve(attrs["contentDescription"], "string", normalized_style)
                node["alt"] = resolved.value if resolved.resolved else attrs["contentDescription"]
                node["semantics"] = {"role": "button" if node_type == "button" else "image", "label": node["alt"]}
                node["provenance"]["alt"] = property_evidence(resolved.source or active_context.source, resolved.line if resolved.source else line, f'contentDescription="{attrs["contentDescription"]}"', self.id, resolved.confidence if resolved.source else "exact")
            if attrs.get("background", "").startswith("@drawable/"):
                drawable = catalog.drawable(attrs["background"], normalized_style)
                node["style"].update(drawable.style)
                for key in drawable.style:
                    node["provenance"][f"style.{key}"] = property_evidence(drawable.source, drawable.line, attrs["background"], self.id, drawable.confidence)
                if not drawable.style:
                    result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": attrs["background"], "reason": "unsupported-background-drawable"})
            elif attrs.get("background"):
                resolved = catalog.resolve(attrs["background"], "color", normalized_style)
                node["style"]["backgroundColor"] = resolved.value if resolved.resolved else attrs["background"]
                node["provenance"]["style.backgroundColor"] = property_evidence(resolved.source or active_context.source, resolved.line if resolved.source else line, attrs["background"], self.id, resolved.confidence if resolved.source else "exact")
            if attrs.get("src") or attrs.get("srcCompat"):
                asset = attrs.get("srcCompat") or attrs.get("src")
                drawable = catalog.drawable(str(asset), normalized_style)
                node["asset"] = drawable.asset or asset
                node["style"].update(drawable.style)
                node["provenance"]["asset"] = property_evidence(drawable.source or active_context.source, drawable.line if drawable.source else line, str(asset), self.id, drawable.confidence)
                if not drawable.asset:
                    result.unsupported.append({"adapter": self.id, "file": active_context.source, "line": line, "expression": asset, "reason": "unsupported-android-drawable"})
            scale_types = {"centerCrop": "cover", "fitCenter": "contain", "centerInside": "contain", "fitXY": "fill", "center": "none"}
            if attrs.get("scaleType") in scale_types:
                _set(node, "style.objectFit", scale_types[attrs["scaleType"]], active_context, line, f'scaleType="{attrs["scaleType"]}"', self.id)
            if attrs.get("focusable") == "true":
                node["states"] = {"default": {}, "focused": {"style": {"outline": "source-focus"}}}
            node["children"] = [convert(child, active_context, active_text, include_stack) for child in element if isinstance(child.tag, str)]
            if short == "ImageButton" and node.get("asset"):
                icon_id = f"{node_id}-icon"
                result.nodes[icon_id] = {
                    "type": "icon", "component": "ImageButton.drawable", "asset": node["asset"], "alt": node.get("alt", ""),
                    "layout": {"width": "fill", "height": "fill"}, "style": {"objectFit": node.get("style", {}).get("objectFit", "contain")}, "children": [],
                    "source": {"file": active_context.source, "line": line}, "confidence": node.get("confidence", "high"), "standardRef": node.get("standardRef"),
                    "provenance": {"asset": node["provenance"].get("asset", property_evidence(active_context.source, line, str(node["asset"]), self.id, "exact"))},
                }
                node["children"].insert(0, icon_id)
            if node.get("layout", {}).get("direction") == "overlay":
                for child_id in node["children"]:
                    child_node = result.nodes[child_id]
                    child_node.setdefault("layout", {})["gridArea"] = "1 / 1"
                    child_source = child_node.get("source", {})
                    child_node.setdefault("provenance", {})["layout.gridArea"] = property_evidence(
                        str(child_source.get("file") or active_context.source),
                        int(child_source.get("line") or line),
                        "overlay parent",
                        self.id,
                        "high",
                    )
            result.nodes[node_id] = node
            return node_id

        candidates = list(content_root) if _local(content_root.tag) == "merge" else [content_root]
        result.nodes[root_id]["children"] = [convert(child, context, context.text) for child in candidates]
        if context.role == "screen":
            metadata = android_layout_metadata(context.path) or {}
            result.screens.append({
                "id": screen_id,
                "name": context.path.stem,
                "root": root_id,
                "route": "",
                "platform": platform,
                "source": {"file": context.source, "line": 1, "symbol": context.path.stem},
                "confidence": "high",
                "androidLayout": str(metadata.get("resource") or context.path.stem),
                "resourceQualifier": str(metadata.get("qualifier") or ""),
            })
        return result


class XamlAdapter:
    id = "xaml"
    platforms = ("windows",)
    extensions = (".xaml",)
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "deterministic-projection"
    native_evidence_required = True
    native_providers = ("windows-app-sdk", "wpf-screenshot")
    limitations = ("templates and bindings are not evaluated", "custom controls remain unsupported")
    TYPES = {"Page": "container", "Window": "container", "UserControl": "container", "Grid": "container", "StackPanel": "container", "Canvas": "container", "Border": "card", "Expander": "card", "NavigationView": "container", "CommandBar": "container", "MenuBar": "container", "ToolBar": "container", "Frame": "container", "ScrollViewer": "container", "ListView": "list", "GridView": "list", "ItemsControl": "list", "TreeView": "list", "TextBlock": "text", "Label": "text", "Button": "button", "HyperlinkButton": "button", "AppBarButton": "button", "ToggleSwitch": "button", "ToggleButton": "button", "CheckBox": "button", "RadioButton": "button", "TextBox": "input", "PasswordBox": "input", "AutoSuggestBox": "input", "NumberBox": "input", "Image": "image", "SymbolIcon": "icon", "FontIcon": "icon", "ProgressBar": "container", "ProgressRing": "container", "Rectangle": "divider"}
    TYPES.update(adapter_type_map("windows", "xaml"))

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".xaml" and any(value.startswith("windows-") for value in context.platforms)

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
        try:
            root = ET.fromstring(context.text)
        except ET.ParseError as exc:
            result.unsupported.append({"adapter": self.id, "file": context.source, "line": getattr(exc, "position", (1,))[0], "expression": str(exc), "reason": "invalid-xaml"})
            return result
        root_tag = _local(root.tag)
        if root_tag == "ResourceDictionary":
            for child in root:
                attrs, value = _attrs(child), (child.text or attrs.get("Color") or "").strip()
                name = attrs.get("Key")
                if not name or not value:
                    continue
                group = "colors" if _local(child.tag) in {"Color", "SolidColorBrush"} else "spacing"
                result.tokens[group][_slug(name).replace("-", "_")] = {"value": _normalize_ref(value, group), "source": {"file": context.source, "line": _line(context.text, name)}, "adapter": self.id}
            return result
        root_attrs = _attrs(root)
        name = root_attrs.get("Class", context.path.stem).split(".")[-1]
        screen_id, root_id = _slug(name, "windows-view"), f"{_slug(name, 'windows-view')}-root"
        result.nodes[root_id] = _root_node(context, self.id, "project.windows.xaml")
        count = 0

        def convert(element: ET.Element) -> str:
            nonlocal count
            count += 1
            tag, attrs = _local(element.tag), _attrs(element)
            node_id = f"{screen_id}-{_slug(attrs.get('Name') or tag)}-{count}"
            node_type, line = self.TYPES.get(tag, "custom"), _line(context.text, f"<{tag}")
            node: dict[str, Any] = {"type": node_type, "component": tag, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line}, "confidence": "high" if node_type != "custom" else "unsupported", "standardRef": f"project.windows.{tag.lower()}", "provenance": {}}
            if node_type != "custom":
                node["inheritsAppearance"] = True
                node["provenance"]["component"] = property_evidence(context.source, line, tag, self.id, "exact")
            else:
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": tag, "reason": "unsupported-xaml-control"})
            mapping = {"Width": ("layout.width", "spacing"), "Height": ("layout.height", "spacing"), "MinWidth": ("layout.minWidth", "spacing"), "MinHeight": ("layout.minHeight", "spacing"), "Margin": ("layout.margin", "spacing"), "Padding": ("layout.padding", "spacing"), "Background": ("style.background", "colors"), "Foreground": ("style.color", "colors"), "FontSize": ("style.fontSize", "typography"), "CornerRadius": ("style.radius", "radii"), "Opacity": ("style.opacity", "spacing")}
            for attr, (path, group) in mapping.items():
                if attr in attrs:
                    _set(node, path, _normalize_ref(attrs[attr], group), context, line, f'{attr}="{attrs[attr]}"', self.id)
            if attrs.get("Orientation") in {"Vertical", "Horizontal"}:
                _set(node, "layout.direction", "column" if attrs["Orientation"] == "Vertical" else "row", context, line, f'Orientation="{attrs["Orientation"]}"', self.id)
            text = attrs.get("Text") or attrs.get("Content") or (element.text or "").strip()
            if text and "{" not in text:
                node["text"] = text
                node["provenance"]["text"] = property_evidence(context.source, line, text, self.id, "exact")
            if attrs.get("Source"):
                node["asset"] = attrs["Source"]
                node["provenance"]["asset"] = property_evidence(context.source, line, attrs["Source"], self.id, "exact")
            node["children"] = [convert(child) for child in element if isinstance(child.tag, str) and "." not in _local(child.tag)]
            result.nodes[node_id] = node
            return node_id

        result.nodes[root_id]["children"] = [convert(root)]
        result.screens.append({"id": screen_id, "name": name, "root": root_id, "route": "", "platform": "windows", "source": {"file": context.source, "line": 1, "symbol": name}, "confidence": "high"})
        return result


DECLARATIVE_TYPES = {
    "VStack": "container", "LazyVStack": "container", "HStack": "container", "LazyHStack": "container", "ZStack": "container",
    "Grid": "list", "LazyVGrid": "list", "LazyHGrid": "list", "NavigationStack": "container", "NavigationSplitView": "container",
    "ScrollView": "container", "Form": "container", "Section": "container", "GroupBox": "card", "List": "list", "Table": "list",
    "Text": "text", "Button": "button", "Link": "button", "Menu": "button", "Picker": "input", "Slider": "input",
    "TextField": "input", "SecureField": "input", "Image": "image", "AsyncImage": "image", "Label": "text", "Spacer": "spacer",
    "Divider": "divider", "Toggle": "button", "ProgressView": "container",
    "SafeArea": "container", "SingleChildScrollView": "container", "Column": "container", "Row": "container", "Stack": "container",
    "Wrap": "container", "Scaffold": "container", "Container": "container", "Padding": "container", "Center": "container",
    "Expanded": "container", "Flexible": "container", "ListView": "list", "GridView": "list", "Card": "card", "ListTile": "card",
    "ElevatedButton": "button", "FilledButton": "button", "OutlinedButton": "button", "TextButton": "button", "IconButton": "button",
    "FloatingActionButton": "button", "CupertinoButton": "button", "TextFormField": "input", "CupertinoTextField": "input",
    "Checkbox": "button", "Switch": "button", "CupertinoSwitch": "button", "Radio": "button", "AppBar": "container",
    "NavigationBar": "container", "BottomNavigationBar": "container", "LinearProgressIndicator": "container",
    "CircularProgressIndicator": "container", "SizedBox": "spacer", "Icon": "icon",
    "CustomPaint": "container", "ClipRRect": "container", "DecoratedBox": "container", "ColoredBox": "container",
    "InkWell": "button", "GestureDetector": "button", "Opacity": "container", "Align": "container",
    "Positioned": "container", "AspectRatio": "container", "ConstrainedBox": "container", "Image": "image",
    "AnimatedContainer": "container", "AnimatedAlign": "container", "AnimatedOpacity": "container",
    "IgnorePointer": "container", "Semantics": "container", "Tooltip": "container", "Material": "container",
    "ClipRect": "container", "RichText": "text",
}


def _declarative_calls(body: str, types: set[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(types, key=len, reverse=True)) + r")\b")
    for match in pattern.finditer(body):
        cursor = match.end()
        while cursor < len(body) and body[cursor].isspace(): cursor += 1
        args, close = "", match.end()
        if cursor < len(body) and body[cursor] == "(":
            end = _balanced_close(body, cursor, "(", ")")
            if end is None: continue
            args, close, cursor = body[cursor + 1:end], end, end + 1
        while cursor < len(body) and body[cursor].isspace(): cursor += 1
        block_end = _balanced_close(body, cursor, "{", "}") if cursor < len(body) and body[cursor] == "{" else None
        contain_end = block_end if block_end is not None else close
        calls.append({"widget": match.group(1), "start": match.start(), "args": args, "close": close, "blockStart": cursor if block_end is not None else None, "containEnd": contain_end})
    return calls


def _modifier_chain(body: str, start: int) -> str:
    cursor, end = start, start
    while cursor < len(body):
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor >= len(body) or body[cursor] != ".":
            break
        match = re.match(r"\.\w+", body[cursor:])
        if not match:
            break
        cursor += match.end()
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor < len(body) and body[cursor] == "(":
            close = _balanced_close(body, cursor, "(", ")")
            if close is None:
                break
            cursor = close + 1
        end = cursor
    return body[start:end]


def _apple_color(expression: str, catalog: AppleResourceCatalog | None) -> tuple[str | None, str]:
    asset = re.search(r'Color\(\s*"([^"]+)"', expression)
    if asset and catalog and (resolved := catalog.color(asset.group(1))):
        return resolved.value, resolved.source
    named = re.search(r"(?:Color\.)?\.(black|white|red|green|blue|gray|orange|yellow|pink|purple|primary|secondary)\b", expression)
    if not named:
        named = re.search(r"\bColor\.(black|white|red|green|blue|gray|orange|yellow|pink|purple|primary|secondary)\b", expression)
    colors = {
        "black": "#000000", "white": "#ffffff", "red": "#ff3b30", "green": "#34c759", "blue": "#007aff",
        "gray": "#8e8e93", "orange": "#ff9500", "yellow": "#ffcc00", "pink": "#ff2d55", "purple": "#af52de",
        "primary": "#000000", "secondary": "#6d6d72",
    }
    return (colors.get(named.group(1)), "apple-semantic-color") if named else (None, "")


def _translate_declarative(
    context: SourceContext,
    adapter: str,
    screen_name: str,
    body: str,
    body_offset: int,
    platform: str,
    standard_prefix: str,
    tokens: dict[str, Any],
    apple_catalog: AppleResourceCatalog | None = None,
    extra_types: dict[str, str] | None = None,
    emit_screen: bool = True,
) -> AdapterResult:
    result = AdapterResult(adapter=adapter, tokens=tokens)
    screen_id, root_id = _slug(screen_name), f"{_slug(screen_name)}-root"
    result.nodes[root_id] = _root_node(context, adapter, f"project.{standard_prefix}.screen", _line(context.text, screen_name))
    types = {**DECLARATIVE_TYPES, **adapter_type_map(platform, adapter), **(extra_types or {})}
    calls = _declarative_calls(body, set(types))
    custom_names = set(extra_types or {})
    calls = [
        call for call in calls
        if not any(
            parent["widget"] in custom_names
            and parent["start"] < call["start"] < parent["close"]
            for parent in calls
        )
    ]
    records: list[tuple[dict[str, Any], str]] = []
    for index, call in enumerate(calls, start=1):
        widget, args = call["widget"], call["args"]
        node_id, node_type = f"{screen_id}-{_slug(widget)}-{index}", types[widget]
        if platform == "flutter" and widget in {"Checkbox", "Switch", "CupertinoSwitch", "Radio"}:
            node_type = "container"
        line = context.text.count("\n", 0, body_offset + call["start"]) + 1
        native_prefix = "apple" if platform == "ios" else "macos" if platform == "macos" else "material3" if platform == "android" else "flutter" if platform == "flutter" else "project"
        node: dict[str, Any] = {"type": node_type, "component": widget, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line, "symbol": screen_name}, "confidence": "high", "standardRef": f"{native_prefix}.{standard_prefix}.{widget.lower()}", "inheritsAppearance": True, "provenance": {"component": property_evidence(context.source, line, widget, adapter, "exact")}}
        if widget in custom_names:
            node["_adapterArgs"] = args
        else:
            node["appearanceSource"] = f"{platform}-framework-default"
        if platform == "flutter" and widget in {"Checkbox", "Switch", "CupertinoSwitch", "Radio"}:
            callback = re.search(r"\bonChanged\s*:\s*([^,\n]+)", args)
            if callback and callback.group(1).strip() != "null":
                role = "switch" if "Switch" in widget else "radio" if widget == "Radio" else "checkbox"
                node["semantics"] = {"role": role}
                node["provenance"]["semantics.role"] = property_evidence(context.source, line, callback.group(0), adapter, "high")
        literal = re.search(r"(?:text\s*:\s*|label\s*:\s*)?[\"']([^\"']+)[\"']", args)
        if literal and node_type in {"text", "button", "input"}:
            display_text = re.sub(
                r"\$\{?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}?",
                lambda match: match.group(1).split(".")[-1].replace("_", " ").title(),
                literal.group(1),
            )
            node["text"] = display_text
            node["provenance"]["text"] = property_evidence(context.source, line, literal.group(0), adapter, "exact")
            if display_text != literal.group(1):
                node["mockData"] = {"source": "unresolved-expression", "seed": "stable"}
                node["confidence"] = "approximate"
        localized = re.search(r'String\(\s*localized\s*:\s*"([^"]+)"', args)
        if localized and apple_catalog and (resolved := apple_catalog.localized(localized.group(1))):
            node["text"] = resolved.value
            node["provenance"]["text"] = property_evidence(resolved.source, 1, localized.group(0), adapter, resolved.confidence)
        if platform == "flutter" and node_type == "text" and not node.get("text"):
            expression = args.split(",", 1)[0].strip()
            identifier = re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", expression)
            if identifier:
                label = expression.split(".")[-1].replace("_", " ").title()
                node["text"] = label
                node["mockData"] = {"source": expression, "seed": "stable"}
                node["confidence"] = "approximate"
                node["provenance"]["text"] = property_evidence(context.source, line, expression, adapter, "approximate")
        if widget in {"VStack", "LazyVStack", "Column", "List", "ListView", "SingleChildScrollView"}:
            _set(node, "layout.direction", "column", context, line, widget, adapter)
        if widget in {"HStack", "LazyHStack", "Row"}:
            _set(node, "layout.direction", "row", context, line, widget, adapter)
        if widget in {"ZStack", "Stack"}:
            _set(node, "layout.direction", "overlay", context, line, widget, adapter)
        alignment = re.search(r"\balignment\s*:\s*\.?(leading|trailing|center|top|bottom)", args)
        if alignment and widget in {"VStack", "LazyVStack", "HStack", "LazyHStack", "ZStack"}:
            mapped = {"leading": "start", "trailing": "end", "top": "start", "bottom": "end", "center": "center"}[alignment.group(1)]
            _set(node, "layout.align", mapped, context, line, alignment.group(0), adapter)
        spacing = re.search(r"\bspacing\s*:\s*(-?\d+(?:\.\d+)?)", args)
        if spacing:
            _set(node, "layout.gap", _normalize_ref(spacing.group(1)), context, line, spacing.group(0), adapter)
        modifier_start = int(call.get("containEnd") or call["close"]) + 1
        expression = args + _modifier_chain(body, modifier_start)
        padding = re.search(r"\.padding\s*\(\s*(?!\.)([\w.]+)", expression)
        flutter_padding = re.search(r"padding\s*:\s*(?:const\s+)?EdgeInsets\.all\s*\(\s*([\w.]+)", expression)
        padding_value = padding.group(1) if padding else flutter_padding.group(1) if flutter_padding else None
        if padding_value: _set(node, "layout.padding", _normalize_ref(padding_value), context, line, (padding or flutter_padding).group(0), adapter)
        directional_padding = re.search(r"\.padding\s*\(\s*\.(horizontal|vertical|top|bottom|leading|trailing)\s*,\s*([\w.]+)", expression)
        if directional_padding:
            key = {"horizontal": "paddingHorizontal", "vertical": "paddingVertical", "top": "paddingTop", "bottom": "paddingBottom", "leading": "paddingLeft", "trailing": "paddingRight"}[directional_padding.group(1)]
            _set(node, f"layout.{key}", _normalize_ref(directional_padding.group(2)), context, line, directional_padding.group(0), adapter)
        width = re.search(r"(?:width\s*:\s*|\.frame\s*\(\s*width\s*:\s*)([\w.]+)", expression)
        height = re.search(r"(?:height\s*:\s*|\.frame\s*\([^)]*height\s*:\s*)([\w.]+)", expression)
        if width: _set(node, "layout.width", _normalize_ref(width.group(1)), context, line, width.group(0), adapter)
        if height: _set(node, "layout.height", _normalize_ref(height.group(1)), context, line, height.group(0), adapter)
        if re.search(r"\.frame\s*\([^)]*maxWidth\s*:\s*\.infinity", expression):
            _set(node, "layout.width", "fill", context, line, "frame maxWidth: .infinity", adapter)
        if re.search(r"\.frame\s*\([^)]*maxHeight\s*:\s*\.infinity", expression):
            _set(node, "layout.height", "fill", context, line, "frame maxHeight: .infinity", adapter)
        if platform in {"ios", "macos"}:
            system_image = re.search(r'systemName\s*:\s*"([^"]+)"', args)
            named_image = re.match(r'\s*"([^"]+)"', args)
            if widget == "Image" and system_image:
                node["type"] = "icon"
                node["iconName"] = system_image.group(1)
                if asset := sf_symbol_asset(system_image.group(1)):
                    node["asset"] = asset
                    node["provenance"]["asset"] = property_evidence("apple-sf-symbol-fallback", 1, system_image.group(0), adapter, "approximate")
            elif widget in {"Image", "AsyncImage"} and named_image and apple_catalog:
                resolved = apple_catalog.image(named_image.group(1))
                if resolved:
                    node["asset"] = resolved.value
                    node["provenance"]["asset"] = property_evidence(resolved.source, 1, named_image.group(0), adapter, resolved.confidence)
            foreground = re.search(r"\.(?:foregroundStyle|foregroundColor)\s*\(([^)]*(?:\([^)]*\)[^)]*)?)\)", expression)
            if foreground:
                color, source = _apple_color(foreground.group(1), apple_catalog)
                if color:
                    node["style"]["color"] = color
                    node["provenance"]["style.color"] = property_evidence(source or context.source, 1 if source else line, foreground.group(0), adapter, "high")
            background = re.search(r"\.background\s*\(([^)]*(?:\([^)]*\)[^)]*)?)\)", expression)
            if background:
                color, source = _apple_color(background.group(1), apple_catalog)
                if color:
                    node["style"]["backgroundColor"] = color
                    node["provenance"]["style.backgroundColor"] = property_evidence(source or context.source, 1 if source else line, background.group(0), adapter, "high")
            radius = re.search(r"\.cornerRadius\s*\(\s*([\d.]+)", expression) or re.search(r"RoundedRectangle\s*\(\s*cornerRadius\s*:\s*([\d.]+)", expression)
            if radius:
                _set(node, "style.radius", _normalize_ref(radius.group(1)), context, line, radius.group(0), adapter)
            font_size = re.search(r"\.font\s*\(\s*\.system\s*\([^)]*size\s*:\s*([\d.]+)", expression)
            if font_size:
                _set(node, "style.fontSize", _normalize_ref(font_size.group(1)), context, line, font_size.group(0), adapter)
            font_weight = re.search(r"(?:weight\s*:\s*|\.fontWeight\s*\()\.?(bold|semibold|medium|regular)", expression)
            if font_weight:
                _set(node, "style.fontWeight", {"bold": 700, "semibold": 600, "medium": 500, "regular": 400}[font_weight.group(1)], context, line, font_weight.group(0), adapter)
            if ".bold()" in expression:
                _set(node, "style.fontWeight", 700, context, line, ".bold()", adapter)
            text_align = re.search(r"\.multilineTextAlignment\s*\(\s*\.(leading|center|trailing)", expression)
            if text_align:
                _set(node, "style.textAlign", {"leading": "start", "center": "center", "trailing": "end"}[text_align.group(1)], context, line, text_align.group(0), adapter)
            if ".scaledToFill()" in expression:
                _set(node, "style.objectFit", "cover", context, line, ".scaledToFill()", adapter)
            elif ".scaledToFit()" in expression:
                _set(node, "style.objectFit", "contain", context, line, ".scaledToFit()", adapter)
        if platform == "flutter":
            main_axis = re.search(r"\bmainAxisAlignment\s*:\s*MainAxisAlignment\.(start|end|center|spaceBetween|spaceAround|spaceEvenly)", args)
            cross_axis = re.search(r"\bcrossAxisAlignment\s*:\s*CrossAxisAlignment\.(start|end|center|stretch|baseline)", args)
            if main_axis:
                _set(node, "layout.justify", {"spaceBetween": "between", "spaceAround": "around", "spaceEvenly": "evenly"}.get(main_axis.group(1), main_axis.group(1)), context, line, main_axis.group(0), adapter)
            if cross_axis:
                _set(node, "layout.align", cross_axis.group(1), context, line, cross_axis.group(0), adapter)
            symmetric = re.search(r"padding\s*:\s*(?:const\s+)?EdgeInsets\.symmetric\s*\(([^)]*)\)", expression)
            if symmetric:
                horizontal = re.search(r"horizontal\s*:\s*([\w.]+)", symmetric.group(1))
                vertical = re.search(r"vertical\s*:\s*([\w.]+)", symmetric.group(1))
                if horizontal: _set(node, "layout.paddingHorizontal", _normalize_ref(horizontal.group(1)), context, line, horizontal.group(0), adapter)
                if vertical: _set(node, "layout.paddingVertical", _normalize_ref(vertical.group(1)), context, line, vertical.group(0), adapter)
            color_match = re.search(r"(?:backgroundColor|color)\s*:\s*((?:const\s+)?Color\s*\(\s*0x[0-9a-fA-F]+\s*\)|Colors\.\w+)", expression)
            if color_match:
                color_value = _flutter_color(color_match.group(1))
                if color_value:
                    target = "color" if node_type in {"text", "icon"} else "backgroundColor"
                    _set(node, f"style.{target}", color_value, context, line, color_match.group(0), adapter)
            radius = re.search(r"BorderRadius\.circular\s*\(\s*([\d.]+)", expression)
            if radius: _set(node, "style.radius", _normalize_ref(radius.group(1)), context, line, radius.group(0), adapter)
            font_size = re.search(r"fontSize\s*:\s*([\d.]+)", expression)
            if font_size: _set(node, "style.fontSize", _normalize_ref(font_size.group(1)), context, line, font_size.group(0), adapter)
            font_weight = re.search(r"fontWeight\s*:\s*FontWeight\.w(\d+)", expression)
            if font_weight: _set(node, "style.fontWeight", int(font_weight.group(1)), context, line, font_weight.group(0), adapter)
            opacity = re.search(r"\bopacity\s*:\s*([\d.]+)", args)
            if opacity: _set(node, "style.opacity", float(opacity.group(1)), context, line, opacity.group(0), adapter)
            for edge in ("top", "right", "bottom", "left"):
                positioned = re.search(rf"\b{edge}\s*:\s*(-?[\d.]+)", args)
                if positioned: _set(node, f"layout.{edge}", _normalize_ref(positioned.group(1)), context, line, positioned.group(0), adapter)
            if widget == "Expanded":
                grow = re.search(r"\bflex\s*:\s*(\d+)", args)
                _set(node, "layout.grow", int(grow.group(1)) if grow else 1, context, line, grow.group(0) if grow else widget, adapter)
            navigation = re.search(r"\b(?:go|push|pushReplacement|replace)\s*\(\s*['\"]([^'\"]+)", args)
            callback = re.search(r"\b(?:onTap|onPressed)\s*:\s*(?!null)", args)
            if navigation and callback:
                node["action"] = {"type": "navigate", "target": navigation.group(1), "route": navigation.group(1)}
                node["semantics"] = {"role": "link", "label": node.get("text") or widget}
            asset = re.search(r"Image\.asset\s*\(\s*['\"]([^'\"]+)", expression)
            if widget == "Image" and asset:
                node["asset"] = asset.group(1)
                node["provenance"]["asset"] = property_evidence(context.source, line, asset.group(0), adapter, "exact")
            icon = re.search(r"Icons\.(\w+)", args)
            if widget == "Icon" and icon:
                node["iconName"] = icon.group(1)
        result.nodes[node_id] = node
        records.append((call, node_id))
    for call, node_id in records:
        parents = [(candidate, candidate_id) for candidate, candidate_id in records if candidate["start"] < call["start"] < candidate["containEnd"]]
        parent_id = max(parents, key=lambda item: item[0]["start"])[1] if parents else root_id
        result.nodes[parent_id]["children"].append(node_id)
    known = set(types) | {
        "Color", "Font", "String", "EdgeInsets", "RoundedRectangle", "MaterialApp", "ThemeData",
        "BoxDecoration", "BoxShadow", "Shadow", "Offset", "LinearGradient", "RadialGradient", "SweepGradient",
        "TextStyle", "TextSpan", "ColorScheme", "BoxConstraints", "Duration", "ValueKey", "InputDecoration",
    }
    for unknown in re.finditer(r"\b([A-Z]\w*)\s*(?:\(|\{)", body):
        unknown_name = unknown.group(1)
        flutter_visual_gap = bool(re.search(r"(?:Widget|View|Card|Tile|Button|Screen|Panel|Header|Footer|Container)$", unknown_name))
        if unknown_name not in known and (platform != "flutter" or flutter_visual_gap):
            result.unsupported.append({"adapter": adapter, "file": context.source, "line": context.text.count("\n", 0, body_offset + unknown.start()) + 1, "expression": unknown.group(1), "reason": "unsupported-declarative-component"})
    if emit_screen:
        result.screens.append({"id": screen_id, "name": screen_name, "root": root_id, "route": "", "platform": platform, "source": {"file": context.source, "line": _line(context.text, screen_name), "symbol": screen_name}, "confidence": "high"})
    return result


def _flutter_color(expression: str) -> str | None:
    raw = re.search(r"0x([0-9a-fA-F]{6,8})", expression)
    if raw:
        value = raw.group(1)
        return f"#{value[-6:]}".lower()
    named = re.search(r"Colors\.(\w+)", expression)
    return {
        "black": "#000000", "white": "#ffffff", "red": "#f44336", "green": "#4caf50",
        "blue": "#2196f3", "grey": "#9e9e9e", "gray": "#9e9e9e", "orange": "#ff9800",
        "yellow": "#ffeb3b", "purple": "#9c27b0", "transparent": "transparent",
    }.get(named.group(1)) if named else None


class SwiftUIAdapter:
    id = "swiftui"
    platforms = ("ios", "macos")
    extensions = (".swift",)
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "deterministic-projection"
    native_evidence_required = True
    native_providers = ("xcode-preview", "swift-snapshot-testing", "apple-simulator")
    resource_resolution = ("Asset Catalog images/colors", "Localizable.strings", "common SF Symbols")
    layout_features = ("stack direction/alignment/spacing", "frame/fill/padding", "overlay stacks", "basic color/type/image modifiers")
    limitations = ("supported SwiftUI primitives and modifiers only", "conditional runtime branches are not executed", "SF Symbol SVGs are structural fallbacks")

    def __init__(self) -> None:
        self._catalogs: dict[str, AppleResourceCatalog] = {}

    def prepare(self, contexts: list[SourceContext]) -> None:
        roots = {str(context.root.resolve()): context.root for context in contexts if self.supports(context)}
        self._catalogs = {key: AppleResourceCatalog.discover(root) for key, root in roots.items()}

    def _catalog(self, context: SourceContext) -> AppleResourceCatalog:
        key = str(context.root.resolve())
        if key not in self._catalogs:
            self._catalogs[key] = AppleResourceCatalog.discover(context.root)
        return self._catalogs[key]

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".swift" and any(value.startswith("swiftui") for value in context.platforms)

    def translate(self, context: SourceContext) -> AdapterResult:
        combined = AdapterResult(adapter=self.id)
        catalog = self._catalog(context)
        tokens = {"colors": {}, "spacing": {}, "radii": {}, "typography": {}}
        for match in re.finditer(r"(?:static\s+)?let\s+(\w+)\s*(?::\s*\w+)?\s*=\s*(Color\([^\n]+\)|\d+(?:\.\d+)?)", context.text):
            group = "colors" if match.group(2).startswith("Color") else "spacing"
            tokens[group][_slug(match.group(1)).replace("-", "_")] = {"value": match.group(2), "source": {"file": context.source, "line": _line(context.text, match.group(0))}, "adapter": self.id}
        platform = "macos" if any(value in {"swiftui-macos", "appkit"} for value in context.platforms) else "ios"
        for struct in re.finditer(r"\bstruct\s+([A-Z]\w*)\s*:\s*View\s*\{", context.text):
            end = _balanced_close(context.text, context.text.find("{", struct.start()), "{", "}")
            if end is None: continue
            segment = context.text[struct.end():end]
            body_match = re.search(r"\bvar\s+body\s*:\s*some\s+View\s*\{", segment)
            if not body_match: continue
            body_start = struct.end() + body_match.end()
            body_end = _balanced_close(context.text, body_start - 1, "{", "}")
            if body_end is None: continue
            current = _translate_declarative(context, self.id, struct.group(1), context.text[body_start:body_end], body_start, platform, "swiftui", tokens, catalog)
            combined.screens.extend(current.screens); combined.nodes.update(current.nodes); combined.unsupported.extend(current.unsupported)
        combined.tokens = tokens
        return combined


class FlutterAdapter:
    id = "flutter"
    platforms = ("flutter",)
    extensions = (".dart",)
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "deterministic-projection"
    native_evidence_required = True
    native_providers = ("flutter-golden", "flutter-device")
    limitations = ("runtime branches are not executed", "custom painters require golden or device evidence")

    WIDGET_BASES = {
        "StatelessWidget", "StatefulWidget", "ConsumerWidget", "ConsumerStatefulWidget",
        "HookWidget", "HookConsumerWidget",
    }

    def __init__(self) -> None:
        self._prepared = False
        self._classes: dict[str, dict[str, Any]] = {}
        self._screen_names: set[str] = set()
        self._localizations: dict[str, str] = {}
        self._constants: dict[str, str] = {}
        self._prepared_sources: set[str] = set()

    @staticmethod
    def _expression_end(text: str, start: int) -> int:
        depths = {"(": 0, "[": 0, "{": 0}
        pairs = {")": "(", "]": "[", "}": "{"}
        quote = ""
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
            elif char in depths:
                depths[char] += 1
            elif char in pairs:
                depths[pairs[char]] = max(0, depths[pairs[char]] - 1)
            elif char == ";" and not any(depths.values()):
                return index
        return len(text)

    @classmethod
    def _build_body(cls, text: str, start: int, end: int) -> tuple[str, int] | None:
        segment = text[start:end]
        block = re.search(r"\bWidget\s+build\s*\([^)]*\)\s*\{", segment)
        if block:
            opening = start + block.end() - 1
            closing = _balanced_close(text, opening, "{", "}")
            if closing is not None:
                body = text[opening + 1:closing]
                returned = re.search(r"\breturn\s+(.+)", body, re.S)
                return ((returned.group(1) if returned else body), opening + 1)
        arrow = re.search(r"\bWidget\s+build\s*\([^)]*\)\s*=>", segment)
        if arrow:
            body_start = start + arrow.end()
            body_end = cls._expression_end(text, body_start)
            return text[body_start:body_end], body_start
        return None

    @staticmethod
    def _fields(class_body: str) -> list[str]:
        return list(dict.fromkeys(
            match.group(1)
            for match in re.finditer(
                r"\bfinal\s+(?:[A-Za-z_][\w<>?,. ]*\s+)([a-zA-Z_]\w*)\s*;",
                class_body,
            )
        ))

    def prepare(self, contexts: list[SourceContext]) -> None:
        self._prepared = True
        self._classes = {}
        self._screen_names = set()
        self._localizations = {}
        self._constants = {}
        flutter_contexts = [context for context in contexts if self.supports(context)]
        self._prepared_sources = {context.source for context in flutter_contexts}
        roots = {context.root.resolve() for context in flutter_contexts}
        for root in roots:
            arb_files = sorted(root.glob("**/*_en.arb")) or sorted(root.glob("**/*.arb"))
            for path in arb_files:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for key, value in payload.items():
                    if not str(key).startswith("@") and isinstance(value, str):
                        self._localizations.setdefault(str(key), value)
        class_pattern = re.compile(r"\bclass\s+(_?[A-Z]\w*)\s+extends\s+([A-Za-z_]\w*)(?:\s*<\s*([^>]+)\s*>)?[^\{]*\{")
        state_builds: dict[str, dict[str, Any]] = {}
        for context in flutter_contexts:
            for constant in re.finditer(r"\b(?:static\s+)?const\s+(?:String|double|int|Color)?\s*(\w+)\s*=\s*([^;]+);", context.text):
                self._constants.setdefault(constant.group(1), constant.group(2).strip())
            for klass in class_pattern.finditer(context.text):
                opening = context.text.find("{", klass.start())
                closing = _balanced_close(context.text, opening, "{", "}")
                if closing is None:
                    continue
                name, base, generic = klass.group(1), klass.group(2), (klass.group(3) or "").strip()
                class_body = context.text[opening + 1:closing]
                build = self._build_body(context.text, opening + 1, closing)
                entry = {
                    "name": name, "base": base, "context": context, "body": build[0] if build else "",
                    "bodyOffset": build[1] if build else opening + 1, "fields": self._fields(class_body),
                }
                if base in self.WIDGET_BASES:
                    self._classes[name] = entry
                elif base in {"State", "ConsumerState"} and generic and build:
                    state_builds[generic.split(",", 1)[0].strip()] = entry
            for route_target in re.finditer(r"\b(?:builder|pageBuilder)\s*:[^=]*=>\s*(?:const\s+)?([A-Z]\w*)\s*\(", context.text):
                self._screen_names.add(route_target.group(1))
            for route_target in re.finditer(r"\breturn\s+(?:const\s+)?([A-Z]\w*)\s*\(", context.text):
                if "GoRoute" in context.text:
                    self._screen_names.add(route_target.group(1))
        for widget_name, state in state_builds.items():
            if widget_name in self._classes:
                self._classes[widget_name]["body"] = state["body"]
                self._classes[widget_name]["bodyOffset"] = state["bodyOffset"]
                self._classes[widget_name]["context"] = state["context"]
        if not self._screen_names:
            self._screen_names.update(
                name for name in self._classes
                if name.endswith(("Page", "Screen", "View", "Dialog"))
            )

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".dart" and "flutter" in context.platforms

    @staticmethod
    def _split_args(args: str) -> list[str]:
        result: list[str] = []
        start = 0
        depths = {"(": 0, "[": 0, "{": 0}
        pairs = {")": "(", "]": "[", "}": "{"}
        quote = ""
        escaped = False
        for index, char in enumerate(args):
            if quote:
                if escaped: escaped = False
                elif char == "\\": escaped = True
                elif char == quote: quote = ""
                continue
            if char in {"'", '"'}: quote = char
            elif char in depths: depths[char] += 1
            elif char in pairs: depths[pairs[char]] = max(0, depths[pairs[char]] - 1)
            elif char == "," and not any(depths.values()):
                result.append(args[start:index].strip())
                start = index + 1
        tail = args[start:].strip()
        if tail: result.append(tail)
        return result

    def _bindings(self, entry: dict[str, Any], args: str) -> dict[str, str]:
        named: dict[str, str] = {}
        positional: list[str] = []
        for item in self._split_args(args):
            match = re.match(r"([A-Za-z_]\w*)\s*:\s*(.+)", item, re.S)
            if match: named[match.group(1)] = match.group(2).strip()
            elif item and not item.startswith(("key:", "super.")): positional.append(item)
        for field, value in zip(entry.get("fields", []), positional):
            named.setdefault(field, value)
        return named

    def _resolve_localizations(self, body: str) -> str:
        pattern = re.compile(r"(?:\bcontext\.)?\bl10n\.(\w+)(?:\s*\(([^()]*)\))?")
        def value(match: re.Match[str]) -> str:
            template = self._localizations.get(match.group(1))
            if template is None:
                return match.group(1).replace("_", " ").strip().title()
            values = self._split_args(match.group(2) or "")
            placeholders = re.findall(r"\{(\w+)\}", template)
            for index, placeholder in enumerate(placeholders):
                raw = values[index].strip() if index < len(values) else placeholder.replace("_", " ").title()
                literal = re.fullmatch(r"['\"](.*)['\"]", raw, re.S)
                template = template.replace("{" + placeholder + "}", literal.group(1) if literal else raw)
            return template
        interpolation = re.compile(r"\$\{((?:context\.)?l10n\.\w+(?:\s*\([^{}]*\))?)\}")
        body = interpolation.sub(lambda match: value(pattern.fullmatch(match.group(1)) or match), body)
        return pattern.sub(lambda match: repr(value(match)), body)

    def _resolved_body(self, entry: dict[str, Any], bindings: dict[str, str]) -> str:
        body = str(entry.get("body") or "")
        for name, value in sorted(bindings.items(), key=lambda item: len(item[0]), reverse=True):
            body = re.sub(rf"\b{re.escape(name)}\b", value, body)
        for name, value in sorted(self._constants.items(), key=lambda item: len(item[0]), reverse=True):
            body = re.sub(rf"\b{re.escape(name)}\b", value, body)
        return self._resolve_localizations(body)

    def _translate_class(
        self,
        class_name: str,
        namespace: str,
        tokens: dict[str, Any],
        bindings: dict[str, str] | None = None,
        stack: tuple[str, ...] = (),
    ) -> AdapterResult:
        entry = self._classes[class_name]
        body = self._resolved_body(entry, bindings or {})
        context = entry["context"]
        custom_types = {name: "container" for name in self._classes}
        current = _translate_declarative(
            context, self.id, namespace, body, int(entry["bodyOffset"]), "flutter", "flutter", tokens,
            extra_types=custom_types,
        )
        for node_id, node in list(current.nodes.items()):
            component = str(node.get("component") or "")
            raw_args = str(node.pop("_adapterArgs", ""))
            if component not in self._classes or component in stack or component == class_name:
                continue
            child_entry = self._classes[component]
            child = self._translate_class(
                component,
                f"{namespace}-{node_id}-{component}",
                tokens,
                self._bindings(child_entry, raw_args),
                (*stack, class_name),
            )
            child_root = str(child.screens[0]["root"])
            node["children"] = [*node.get("children", []), *child.nodes[child_root].get("children", [])]
            for child_id, child_node in child.nodes.items():
                if child_id != child_root:
                    current.nodes[child_id] = child_node
            current.unsupported.extend(child.unsupported)
        return current

    def translate(self, context: SourceContext) -> AdapterResult:
        combined = AdapterResult(adapter=self.id)
        tokens = {"colors": {}, "spacing": {}, "radii": {}, "typography": {}}
        for match in re.finditer(r"(?:static\s+)?const\s+(?:Color|double)\s+(\w+)\s*=\s*([^;]+);", context.text):
            group = "colors" if "Color" in match.group(0).split("=")[0] else "spacing"
            tokens[group][_slug(match.group(1)).replace("-", "_")] = {"value": match.group(2).strip(), "source": {"file": context.source, "line": _line(context.text, match.group(0))}, "adapter": self.id}
        known_source = context.source in self._prepared_sources
        if not self._prepared or not known_source:
            self.prepare([context])
            screen_names = {
                name for name, entry in self._classes.items()
                if entry["context"].source == context.source and entry.get("body")
            }
        else:
            screen_names = {
                name for name in self._screen_names
                if name in self._classes
                and self._classes[name]["context"].source == context.source
                and self._classes[name].get("body")
            }
        for name in sorted(screen_names, key=lambda item: int(self._classes[item]["bodyOffset"])):
            current = self._translate_class(name, name, tokens)
            current.screens[0]["name"] = name
            current.screens[0]["source"]["symbol"] = name
            combined.screens.extend(current.screens)
            combined.nodes.update(current.nodes)
            combined.unsupported.extend(current.unsupported)
        for name, entry in self._classes.items():
            if entry["context"].source != context.source or not entry.get("body"):
                continue
            combined.components.append({
                "id": f'{entry["context"].source}#{name}',
                "name": name,
                "platform": "flutter",
                "kind": "project",
                "source": {"file": entry["context"].source, "line": _line(entry["context"].text, f"class {name}"), "symbol": name},
                "inspection": "mapped",
                "confidence": "high",
                "variants": [], "states": [], "tokenRefs": [],
            })
        combined.tokens = tokens
        return combined


class AppleInterfaceXmlAdapter:
    id = "apple-interface-xml"
    platforms = ("ios", "macos")
    extensions = (".storyboard", ".xib")
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "deterministic-projection"
    native_evidence_required = True
    native_providers = ("swift-snapshot-testing", "apple-simulator")
    resource_resolution = ("Asset Catalog images/colors", "authored interface strings")
    layout_features = ("authored frames", "stack axis/spacing", "basic width/height/center Auto Layout constraints")
    limitations = ("complex Auto Layout equations are not solved", "runtime UIKit/AppKit mutations are unsupported")
    TYPES = {"view": "container", "stackView": "container", "scrollView": "container", "tableView": "list", "collectionView": "list", "label": "text", "button": "button", "textField": "input", "textView": "input", "switch": "button", "slider": "input", "segmentedControl": "input", "datePicker": "input", "navigationBar": "container", "toolbar": "container", "progressView": "container", "imageView": "image", "separator": "divider"}
    TYPES.update(adapter_type_map("ios", "apple-interface-xml"))
    TYPES.update(adapter_type_map("macos", "apple-interface-xml"))

    def __init__(self) -> None:
        self._catalogs: dict[str, AppleResourceCatalog] = {}

    def prepare(self, contexts: list[SourceContext]) -> None:
        roots = {str(context.root.resolve()): context.root for context in contexts if self.supports(context)}
        self._catalogs = {key: AppleResourceCatalog.discover(root) for key, root in roots.items()}

    def _catalog(self, context: SourceContext) -> AppleResourceCatalog:
        key = str(context.root.resolve())
        if key not in self._catalogs:
            self._catalogs[key] = AppleResourceCatalog.discover(context.root)
        return self._catalogs[key]

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() in {".storyboard", ".xib"}

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
        catalog = self._catalog(context)
        try: document = ET.fromstring(context.text)
        except ET.ParseError as exc:
            result.unsupported.append({"adapter": self.id, "file": context.source, "line": getattr(exc, "position", (1,))[0], "expression": str(exc), "reason": "invalid-interface-xml"}); return result
        controllers = [item for item in document.iter() if _local(item.tag) in {"viewController", "windowController"}]
        if not controllers and context.path.suffix.lower() == ".xib": controllers = [document]
        platform = "macos" if "MacOSX" in context.text or any(value == "appkit" for value in context.platforms) else "ios"
        for screen_index, controller in enumerate(controllers, start=1):
            attrs = _attrs(controller); name = attrs.get("customClass") or attrs.get("id") or f"{context.path.stem}-{screen_index}"
            screen_id, root_id = _slug(name), f"{_slug(name)}-root"
            result.nodes[root_id] = _root_node(context, self.id, f"project.{platform}.interface")
            count = 0
            source_ids: dict[str, str] = {}
            def convert(element: ET.Element, parent_tag: str = "") -> str | None:
                nonlocal count
                tag = _local(element.tag)
                if tag in {"connections", "constraints", "resources", "dependencies", "outlet", "segue", "constraint", "color"}: return None
                count += 1; attrs = _attrs(element); node_type = self.TYPES.get(tag, "custom"); line = _line(context.text, f"<{tag}")
                node_id = f"{screen_id}-{_slug(attrs.get('id') or tag)}-{count}"
                if attrs.get("id"):
                    source_ids[attrs["id"]] = node_id
                node: dict[str, Any] = {"type": node_type, "component": tag, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line}, "confidence": "high" if node_type != "custom" else "unsupported", "standardRef": f"project.{platform}.{tag.lower()}", "provenance": {}}
                if node_type != "custom": node["inheritsAppearance"] = True; node["provenance"]["component"] = property_evidence(context.source, line, tag, self.id, "exact")
                else: result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": tag, "reason": "unsupported-interface-node"})
                text = attrs.get("text") or attrs.get("title") or attrs.get("placeholder")
                if text: node["text"] = text; node["provenance"]["text"] = property_evidence(context.source, line, text, self.id, "exact")
                if tag == "view":
                    _set(node, "layout.direction", "overlay", context, line, tag, self.id)
                if tag == "stackView":
                    _set(node, "layout.direction", "column" if attrs.get("axis") == "vertical" else "row", context, line, f'axis={attrs.get("axis", "horizontal")}', self.id)
                    if attrs.get("spacing"):
                        _set(node, "layout.gap", _normalize_ref(attrs["spacing"]), context, line, f'spacing={attrs["spacing"]}', self.id)
                if attrs.get("image"):
                    resolved = catalog.image(attrs["image"])
                    node["asset"] = resolved.value if resolved else attrs["image"]
                    node["provenance"]["asset"] = property_evidence(resolved.source if resolved else context.source, 1 if resolved else line, attrs["image"], self.id, resolved.confidence if resolved else "approximate")
                    if not resolved:
                        result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": attrs["image"], "reason": "unresolved-apple-image"})
                named_color = next((_attrs(child).get("name") for child in element if _local(child.tag) == "color" and _attrs(child).get("name")), None)
                if named_color and (resolved_color := catalog.color(named_color)):
                    node["style"]["color" if node_type in {"text", "button", "input", "icon"} else "backgroundColor"] = resolved_color.value
                    node["provenance"]["style.color" if node_type in {"text", "button", "input", "icon"} else "style.backgroundColor"] = property_evidence(resolved_color.source, 1, named_color, self.id, resolved_color.confidence)
                frame = next((child for child in element if _local(child.tag) == "rect" and _attrs(child).get("key") == "frame"), None)
                if frame is not None:
                    values = _attrs(frame)
                    for attr, key in (("x", "left"), ("y", "top"), ("width", "width"), ("height", "height")):
                        if attr in values: _set(node, f"layout.{key}", _normalize_ref(values[attr]), context, line, f"frame.{attr}={values[attr]}", self.id)
                    if parent_tag and parent_tag != "stackView":
                        _set(node, "layout.position", "absolute", context, line, "authored frame", self.id, "high")
                child_ids: list[str] = []
                for child in element:
                    if not isinstance(child.tag, str) or _local(child.tag) == "rect": continue
                    candidates = list(child) if _local(child.tag) in {"subviews", "objects", "scenes"} else [child]
                    for candidate in candidates:
                        if isinstance(candidate.tag, str) and (child_id := convert(candidate, tag)): child_ids.append(child_id)
                node["children"] = child_ids
                result.nodes[node_id] = node; return node_id
            roots = [child_id for child in controller if isinstance(child.tag, str) and (child_id := convert(child))]
            result.nodes[root_id]["children"] = roots
            for constraint in controller.iter():
                if _local(constraint.tag) != "constraint":
                    continue
                values = _attrs(constraint)
                first_id = source_ids.get(values.get("firstItem", ""))
                if not first_id:
                    continue
                node = result.nodes[first_id]
                attribute = values.get("firstAttribute", "")
                second_attribute = values.get("secondAttribute", "")
                second_item = values.get("secondItem")
                constant = values.get("constant")
                if attribute in {"width", "height"} and not second_item and constant:
                    _set(node, f"layout.{attribute}", _normalize_ref(constant), context, _line(context.text, values.get("id", "constraint")), f"constraint {attribute}={constant}", self.id, "high")
                elif attribute == "centerX" and second_attribute == "centerX":
                    _set(node, "layout.justifySelf", "center", context, _line(context.text, values.get("id", "constraint")), "centerX constraint", self.id, "high")
                elif attribute == "centerY" and second_attribute == "centerY":
                    _set(node, "layout.alignSelf", "center", context, _line(context.text, values.get("id", "constraint")), "centerY constraint", self.id, "high")
                else:
                    result.unsupported.append({"adapter": self.id, "file": context.source, "line": _line(context.text, values.get("id", "constraint")), "expression": values.get("id", "constraint"), "reason": "unsupported-auto-layout-equation"})
            result.screens.append({"id": screen_id, "name": name, "root": root_id, "route": "", "platform": platform, "source": {"file": context.source, "line": _line(context.text, name), "symbol": name}, "confidence": "high"})
        return result


class ProjectedMarkupAdapter:
    def __init__(self, web_adapter: Any, kind: str):
        self.web_adapter, self.id = web_adapter, kind
        self.platforms = ("web",)
        self.extensions = (".jsx", ".tsx", ".js", ".ts") if kind.startswith("react") else (f".{kind}",)
        self.maturity = "golden"
        self.structural_tier = "translated"
        self.visual_tier = "projection"
        self.native_evidence_required = False
        self.native_providers = ()
        self.limitations = ("dynamic expressions are not executed", "project components remain unsupported until mapped")

    def supports(self, context: SourceContext) -> bool:
        suffix = context.path.suffix.lower()
        if self.id == "react-jsx": return suffix in {".jsx", ".tsx", ".js", ".ts"} and "react-web" in context.platforms
        if self.id == "vue": return suffix == ".vue"
        return suffix == ".svelte"

    def translate(self, context: SourceContext) -> AdapterResult:
        text, start = context.text, 0
        if self.id == "vue":
            match = re.search(r"<template\b[^>]*>([\s\S]*?)</template>", text, re.I)
            if not match: return AdapterResult(adapter=self.id, unsupported=[{"adapter": self.id, "file": context.source, "line": 1, "expression": "template", "reason": "missing-template"}])
            markup, start = match.group(1), match.start(1)
        elif self.id == "svelte":
            markup = re.sub(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", "", text, flags=re.I)
        else:
            match = re.search(r"\breturn\s*\(", text)
            if not match: return AdapterResult(adapter=self.id, unsupported=[{"adapter": self.id, "file": context.source, "line": 1, "expression": "return", "reason": "missing-static-jsx-return"}])
            open_index = text.find("(", match.start()); end = _balanced_close(text, open_index, "(", ")")
            if end is None: return AdapterResult(adapter=self.id, unsupported=[{"adapter": self.id, "file": context.source, "line": _line(text, match.group(0)), "expression": "return", "reason": "unbalanced-jsx"}])
            markup, start = text[open_index + 1:end], open_index + 1
        unsupported: list[dict[str, Any]] = []
        for expression in re.finditer(r"\{[^{}]*\}", markup):
            unsupported.append({"adapter": self.id, "file": context.source, "line": text.count("\n", 0, start + expression.start()) + 1, "expression": expression.group(0)[:200], "reason": "dynamic-markup-expression"})
        projected = re.sub(r"\{[^{}]*\}", "", markup)
        projected = projected.replace("className=", "class=").replace("htmlFor=", "for=")
        embedded_css = "\n".join(re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", text, re.I)) if self.id in {"vue", "svelte"} else ""
        padded = "\n" * text.count("\n", 0, start) + projected + ("\n" + embedded_css if embedded_css else "")
        projected_context = SourceContext(context.root, context.path, context.source, padded, context.platforms, context.role)
        result = self.web_adapter.translate(projected_context)
        result.adapter = self.id; result.unsupported.extend(unsupported)
        custom_tags = {value.lower(): value for value in re.findall(r"<([A-Z][A-Za-z0-9_.]*)\b", markup)}
        for node in result.nodes.values():
            for evidence in node.get("provenance", {}).values():
                if isinstance(evidence, dict): evidence["adapter"] = self.id; evidence["confidence"] = "high"
            node["confidence"] = "high"
            ref = str(node.get("standardRef") or "")
            tag = ref.removeprefix("html.")
            if tag in custom_tags:
                node.update({"type": "custom", "component": custom_tags[tag], "confidence": "unsupported", "standardRef": f"project.{self.id}.{tag}"})
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": node.get("source", {}).get("line", 1), "expression": custom_tags[tag], "reason": "untranslated-project-component"})
        target_platform = "web"
        for screen in result.screens: screen["platform"] = target_platform; screen["name"] = context.path.stem
        return result


def builtin_platform_adapters(web_adapter: Any) -> list[Any]:
    return [
        AndroidXmlAdapter(), SwiftUIAdapter(), XamlAdapter(), FlutterAdapter(), AppleInterfaceXmlAdapter(),
        ProjectedMarkupAdapter(web_adapter, "react-jsx"),
        ProjectedMarkupAdapter(web_adapter, "vue"), ProjectedMarkupAdapter(web_adapter, "svelte"),
    ]
