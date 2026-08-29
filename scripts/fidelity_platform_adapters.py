#!/usr/bin/env python3
"""Built-in platform adapters beyond static Web and Jetpack Compose."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from android_xml_support import android_layout_metadata
from fidelity_adapter_api import AdapterResult, SourceContext
from fidelity_core import property_evidence


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
    platforms = ("android", "android-tv")
    extensions = (".xml",)
    maturity = "golden"
    limitations = (
        "custom views and include resources are preserved as unsupported source evidence",
        "constraint equations and Data Binding expressions are not executed",
        "theme/style inheritance is not resolved without Android resource tooling",
    )
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

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".xml" and any(value.startswith("android-") for value in context.platforms)

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
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
        layout_metadata = android_layout_metadata(context.path)
        if context.role not in {"screen", "partial"} or not layout_metadata:
            return result
        emit_screen = context.role == "screen"
        content_root = root
        if _local(root.tag) == "layout":
            content_root = next((child for child in root if isinstance(child.tag, str) and _local(child.tag) != "data"), None)
            if content_root is None:
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": 1, "expression": "<layout>", "reason": "data-binding-layout-without-view-root"})
                return result
        platform = "android-tv" if any(value.startswith("android-tv") for value in context.platforms) else "android"
        qualifier = layout_metadata.get("qualifier", "")
        screen_id = _slug(f"{context.path.stem}-{qualifier}" if qualifier else context.path.stem, "android-layout")
        root_id = f"{screen_id}-root"
        result.nodes[root_id] = _root_node(context, self.id, "project.android.layout")
        count = 0
        search_offset = 0

        def convert(element: ET.Element) -> str:
            nonlocal count, search_offset
            count += 1
            raw_tag, attrs = _local(element.tag), _attrs(element)
            short = raw_tag.rsplit(".", 1)[-1]
            node_id = f"{screen_id}-{_slug(attrs.get('id', '').split('/')[-1] or short)}-{count}"
            opening = f"<{raw_tag}"
            offset = context.text.find(opening, search_offset)
            if offset < 0 and attrs.get("id"):
                offset = context.text.find(attrs["id"], search_offset)
            line = context.text.count("\n", 0, offset) + 1 if offset >= 0 else 1
            if offset >= 0:
                search_offset = offset + 1
            if short == "include":
                include_layout = attrs.get("layout", "")
                node = {
                    "type": "container", "component": "include", "includeLayout": include_layout,
                    "text": f"Include: {include_layout or 'unknown layout'}", "layout": {}, "style": {}, "children": [],
                    "source": {"file": context.source, "line": line}, "confidence": "approximate",
                    "standardRef": "project.android.include", "provenance": {
                        "component": property_evidence(context.source, line, "<include>", self.id, "exact"),
                        "text": property_evidence(context.source, line, include_layout or "<include>", self.id, "approximate"),
                    },
                }
                for attr, path in (("layout_width", "layout.width"), ("layout_height", "layout.height"), ("layout_margin", "layout.margin")):
                    if attr in attrs:
                        _set(node, path, _normalize_ref(attrs[attr], "spacing"), context, line, f'{attr}="{attrs[attr]}"', self.id)
                result.nodes[node_id] = node
                return node_id
            node_type = self.TYPES.get(short, "custom")
            standard_prefix = "androidtv" if platform == "android-tv" else "material3" if short.startswith("Material") or "TextInput" in short else "project"
            node: dict[str, Any] = {
                "type": node_type, "component": raw_tag, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line},
                "confidence": "high" if node_type != "custom" else "unsupported", "standardRef": f"{standard_prefix}.android-xml.{short.lower()}", "provenance": {},
            }
            if node_type != "custom":
                node["provenance"]["component"] = property_evidence(context.source, line, raw_tag, self.id, "exact")
            else:
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": raw_tag, "reason": "unsupported-android-view"})
            mapping = {
                "layout_width": ("layout.width", "spacing"), "layout_height": ("layout.height", "spacing"), "padding": ("layout.padding", "spacing"),
                "paddingHorizontal": ("layout.paddingHorizontal", "spacing"), "paddingVertical": ("layout.paddingVertical", "spacing"),
                "paddingStart": ("layout.paddingLeft", "spacing"), "paddingEnd": ("layout.paddingRight", "spacing"),
                "paddingLeft": ("layout.paddingLeft", "spacing"), "paddingRight": ("layout.paddingRight", "spacing"),
                "paddingTop": ("layout.paddingTop", "spacing"), "paddingBottom": ("layout.paddingBottom", "spacing"),
                "layout_margin": ("layout.margin", "spacing"), "layout_marginHorizontal": ("layout.marginHorizontal", "spacing"),
                "layout_marginVertical": ("layout.marginVertical", "spacing"), "layout_marginStart": ("layout.marginLeft", "spacing"),
                "layout_marginEnd": ("layout.marginRight", "spacing"), "layout_marginLeft": ("layout.marginLeft", "spacing"),
                "layout_marginRight": ("layout.marginRight", "spacing"), "layout_marginTop": ("layout.marginTop", "spacing"),
                "layout_marginBottom": ("layout.marginBottom", "spacing"), "minWidth": ("layout.minWidth", "spacing"),
                "minHeight": ("layout.minHeight", "spacing"), "background": ("style.background", "colors"),
                "backgroundTint": ("style.backgroundColor", "colors"), "textColor": ("style.color", "colors"),
                "textSize": ("style.fontSize", "typography"), "fontFamily": ("style.fontFamily", "typography"),
                "alpha": ("style.opacity", "spacing"), "elevation": ("style.elevation", "spacing"),
                "cardElevation": ("style.elevation", "spacing"), "cardCornerRadius": ("style.radius", "radii"),
                "strokeColor": ("style.borderColor", "colors"), "strokeWidth": ("style.borderWidth", "spacing"),
            }
            for attr, (path, group) in mapping.items():
                if attr in attrs:
                    _set(node, path, _normalize_ref(attrs[attr], group), context, line, f'{attr}="{attrs[attr]}"', self.id)
                    if attrs[attr].startswith("?attr/"):
                        node["confidence"] = "approximate" if node["confidence"] != "unsupported" else "unsupported"
                        result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": f'{attr}="{attrs[attr]}"', "reason": "unresolved-theme-attribute"})
            if attrs.get("orientation") in {"vertical", "horizontal"}:
                _set(node, "layout.direction", "column" if attrs["orientation"] == "vertical" else "row", context, line, f'orientation="{attrs["orientation"]}"', self.id)
            elif short in {"FrameLayout", "CoordinatorLayout", "ConstraintLayout", "RelativeLayout"}:
                _set(node, "layout.direction", "overlay", context, line, raw_tag, self.id, "approximate" if short in {"ConstraintLayout", "RelativeLayout"} else "high")
            gravity = attrs.get("gravity", "")
            if "center" in gravity:
                _set(node, "layout.align", "center", context, line, f'gravity="{gravity}"', self.id, "approximate")
                _set(node, "layout.justify", "center", context, line, f'gravity="{gravity}"', self.id, "approximate")
            if attrs.get("layout_gravity"):
                _set(node, "layout.alignSelf", attrs["layout_gravity"], context, line, f'layout_gravity="{attrs["layout_gravity"]}"', self.id, "approximate")
            if attrs.get("visibility") == "gone":
                _set(node, "layout.display", "none", context, line, 'visibility="gone"', self.id)
            constraints = {key: value for key, value in attrs.items() if key.startswith("layout_constraint")}
            if constraints:
                node["androidConstraints"] = constraints
                if node["confidence"] != "unsupported":
                    node["confidence"] = "approximate"
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": ", ".join(sorted(constraints)), "reason": "unresolved-constraint-equations"})
            if attrs.get("text"):
                node["text"] = _normalize_ref(attrs["text"], "strings")
                text_confidence = "approximate" if attrs["text"].startswith("@{") else "exact"
                node["provenance"]["text"] = property_evidence(context.source, line, f'text="{attrs["text"]}"', self.id, text_confidence)
                if text_confidence == "approximate":
                    node["confidence"] = "approximate" if node["confidence"] != "unsupported" else "unsupported"
                    result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": attrs["text"], "reason": "unresolved-data-binding-expression"})
            if attrs.get("hint"):
                node["placeholder"] = _normalize_ref(attrs["hint"], "strings")
                node["provenance"]["placeholder"] = property_evidence(context.source, line, f'hint="{attrs["hint"]}"', self.id, "exact")
            if attrs.get("src") or attrs.get("srcCompat"):
                asset = attrs.get("srcCompat") or attrs.get("src")
                node["asset"] = asset
                node["provenance"]["asset"] = property_evidence(context.source, line, str(asset), self.id, "exact")
            if attrs.get("contentDescription"):
                node["semantics"] = {"label": _normalize_ref(attrs["contentDescription"], "strings")}
            if attrs.get("inputType"):
                node["inputType"] = attrs["inputType"]
            if attrs.get("style") or attrs.get("theme") or attrs.get("textAppearance"):
                expression = attrs.get("style") or attrs.get("theme") or attrs.get("textAppearance")
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": expression, "reason": "unresolved-android-style-reference"})
            if attrs.get("focusable") == "true" or platform == "android-tv" and node_type in {"button", "input"}:
                node["states"] = {"default": {}, "focused": {"style": {"outline": "source-focus"}}}
            node["children"] = [convert(child) for child in element if isinstance(child.tag, str)]
            result.nodes[node_id] = node
            return node_id

        if _local(content_root.tag) == "merge":
            result.nodes[root_id]["children"] = [convert(child) for child in content_root if isinstance(child.tag, str)]
        else:
            result.nodes[root_id]["children"] = [convert(content_root)]
        screen = {
            "id": screen_id, "name": layout_metadata["name"], "root": root_id, "route": "", "platform": platform,
            "source": {"file": context.source, "line": 1, "symbol": context.path.stem}, "confidence": "high",
            "androidLayout": layout_metadata["resource"], "resourceQualifier": qualifier, "translationStatus": "translated",
        }
        if qualifier:
            screen["variantOf"] = _slug(context.path.stem, "android-layout")
        if emit_screen:
            result.screens.append(screen)
        else:
            result.components.append({
                "id": f"android-layout:{screen_id}", "name": layout_metadata["name"], "root": root_id,
                "resource": layout_metadata["resource"], "resourceQualifier": qualifier,
                "source": {"file": context.source, "line": 1, "symbol": context.path.stem},
            })
        return result


class XamlAdapter:
    id = "xaml"
    platforms = ("windows",)
    extensions = (".xaml",)
    maturity = "golden"
    limitations = ("templates and bindings are not evaluated", "custom controls remain unsupported")
    TYPES = {"Page": "container", "Window": "container", "UserControl": "container", "Grid": "container", "StackPanel": "container", "Canvas": "container", "Border": "card", "NavigationView": "container", "Frame": "container", "ScrollViewer": "container", "ListView": "list", "GridView": "list", "ItemsControl": "list", "TextBlock": "text", "Label": "text", "Button": "button", "HyperlinkButton": "button", "TextBox": "input", "PasswordBox": "input", "Image": "image", "SymbolIcon": "icon", "FontIcon": "icon", "Rectangle": "divider"}

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
    "VStack": "container", "HStack": "container", "ZStack": "container", "NavigationStack": "container", "ScrollView": "container", "Form": "container", "Section": "container", "List": "list", "Text": "text", "Button": "button", "TextField": "input", "SecureField": "input", "Image": "image", "AsyncImage": "image", "Label": "text", "Spacer": "spacer", "Divider": "divider", "Toggle": "button",
    "Column": "container", "Row": "container", "Stack": "container", "Scaffold": "container", "Container": "container", "Padding": "container", "Center": "container", "Expanded": "container", "ListView": "list", "GridView": "list", "Card": "card", "ElevatedButton": "button", "TextButton": "button", "IconButton": "button", "TextFormField": "input", "SizedBox": "spacer", "Icon": "icon",
}


def _declarative_calls(body: str, types: set[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"\b(" + "|".join(sorted(types, key=len, reverse=True)) + r")\b")
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


def _translate_declarative(context: SourceContext, adapter: str, screen_name: str, body: str, body_offset: int, platform: str, standard_prefix: str, tokens: dict[str, Any]) -> AdapterResult:
    result = AdapterResult(adapter=adapter, tokens=tokens)
    screen_id, root_id = _slug(screen_name), f"{_slug(screen_name)}-root"
    result.nodes[root_id] = _root_node(context, adapter, f"project.{standard_prefix}.screen", _line(context.text, screen_name))
    calls = _declarative_calls(body, set(DECLARATIVE_TYPES))
    records: list[tuple[dict[str, Any], str]] = []
    for index, call in enumerate(calls, start=1):
        widget, args = call["widget"], call["args"]
        node_id, node_type = f"{screen_id}-{_slug(widget)}-{index}", DECLARATIVE_TYPES[widget]
        line = context.text.count("\n", 0, body_offset + call["start"]) + 1
        native_prefix = "apple" if platform in {"ios", "macos"} else "material3" if platform == "android" else "project"
        node: dict[str, Any] = {"type": node_type, "component": widget, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line, "symbol": screen_name}, "confidence": "high", "standardRef": f"{native_prefix}.{standard_prefix}.{widget.lower()}", "inheritsAppearance": True, "provenance": {"component": property_evidence(context.source, line, widget, adapter, "exact")}}
        literal = re.search(r"(?:text\s*:\s*|label\s*:\s*)?[\"']([^\"']+)[\"']", args)
        if literal and node_type in {"text", "button", "input"}:
            node["text"] = literal.group(1)
            node["provenance"]["text"] = property_evidence(context.source, line, literal.group(0), adapter, "exact")
        if widget in {"VStack", "Column", "List", "ListView"}:
            _set(node, "layout.direction", "column", context, line, widget, adapter)
        if widget in {"HStack", "Row"}:
            _set(node, "layout.direction", "row", context, line, widget, adapter)
        modifier_end = min([value for value in (call.get("blockStart"), body.find("\n", call["close"])) if isinstance(value, int) and value >= call["close"]] or [min(len(body), call["close"] + 240)])
        expression = args + body[call["close"] + 1:modifier_end]
        padding = re.search(r"(?:\.padding\s*\(|padding\s*:\s*(?:const\s+)?EdgeInsets\.all\s*\()\s*([\w.]+)", expression)
        if padding: _set(node, "layout.padding", _normalize_ref(padding.group(1)), context, line, padding.group(0), adapter)
        width = re.search(r"(?:width\s*:\s*|\.frame\s*\(\s*width\s*:\s*)([\w.]+)", expression)
        height = re.search(r"(?:height\s*:\s*|\.frame\s*\([^)]*height\s*:\s*)([\w.]+)", expression)
        if width: _set(node, "layout.width", _normalize_ref(width.group(1)), context, line, width.group(0), adapter)
        if height: _set(node, "layout.height", _normalize_ref(height.group(1)), context, line, height.group(0), adapter)
        result.nodes[node_id] = node
        records.append((call, node_id))
    for call, node_id in records:
        parents = [(candidate, candidate_id) for candidate, candidate_id in records if candidate["start"] < call["start"] < candidate["containEnd"]]
        parent_id = max(parents, key=lambda item: item[0]["start"])[1] if parents else root_id
        result.nodes[parent_id]["children"].append(node_id)
    known = set(DECLARATIVE_TYPES) | {"Color", "Font", "EdgeInsets", "RoundedRectangle", "MaterialApp", "ThemeData"}
    for unknown in re.finditer(r"\b([A-Z]\w*)\s*(?:\(|\{)", body):
        if unknown.group(1) not in known:
            result.unsupported.append({"adapter": adapter, "file": context.source, "line": context.text.count("\n", 0, body_offset + unknown.start()) + 1, "expression": unknown.group(1), "reason": "unsupported-declarative-component"})
    result.screens.append({"id": screen_id, "name": screen_name, "root": root_id, "route": "", "platform": platform, "source": {"file": context.source, "line": _line(context.text, screen_name), "symbol": screen_name}, "confidence": "high"})
    return result


class SwiftUIAdapter:
    id = "swiftui"
    platforms = ("ios", "macos")
    extensions = (".swift",)
    maturity = "golden"
    limitations = ("supported SwiftUI primitives and modifiers only", "conditional runtime branches are not executed")

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".swift" and any(value.startswith("swiftui") for value in context.platforms)

    def translate(self, context: SourceContext) -> AdapterResult:
        combined = AdapterResult(adapter=self.id)
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
            current = _translate_declarative(context, self.id, struct.group(1), context.text[body_start:body_end], body_start, platform, "swiftui", tokens)
            combined.screens.extend(current.screens); combined.nodes.update(current.nodes); combined.unsupported.extend(current.unsupported)
        combined.tokens = tokens
        return combined


class FlutterAdapter:
    id = "flutter"
    platforms = ("flutter",)
    extensions = (".dart",)
    maturity = "golden"
    limitations = ("target OS family must be supplied separately", "custom widgets remain unsupported")

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() == ".dart" and "flutter" in context.platforms

    def translate(self, context: SourceContext) -> AdapterResult:
        combined = AdapterResult(adapter=self.id)
        tokens = {"colors": {}, "spacing": {}, "radii": {}, "typography": {}}
        for match in re.finditer(r"(?:static\s+)?const\s+(?:Color|double)\s+(\w+)\s*=\s*([^;]+);", context.text):
            group = "colors" if "Color" in match.group(0).split("=")[0] else "spacing"
            tokens[group][_slug(match.group(1)).replace("-", "_")] = {"value": match.group(2).strip(), "source": {"file": context.source, "line": _line(context.text, match.group(0))}, "adapter": self.id}
        for klass in re.finditer(r"\bclass\s+([A-Z]\w*)\s+extends\s+(?:StatelessWidget|StatefulWidget)\s*\{", context.text):
            class_end = _balanced_close(context.text, context.text.find("{", klass.start()), "{", "}")
            if class_end is None: continue
            segment = context.text[klass.end():class_end]
            build = re.search(r"\bWidget\s+build\s*\([^)]*\)\s*\{", segment)
            if not build: continue
            build_start = klass.end() + build.end()
            build_end = _balanced_close(context.text, build_start - 1, "{", "}")
            if build_end is None: continue
            current = _translate_declarative(context, self.id, klass.group(1), context.text[build_start:build_end], build_start, "flutter", "flutter", tokens)
            combined.screens.extend(current.screens); combined.nodes.update(current.nodes); combined.unsupported.extend(current.unsupported)
        combined.tokens = tokens
        return combined


class AppleInterfaceXmlAdapter:
    id = "apple-interface-xml"
    platforms = ("ios", "macos")
    extensions = (".storyboard", ".xib")
    maturity = "golden"
    limitations = ("Auto Layout constraints are not solved", "runtime UIKit/AppKit mutations are unsupported")
    TYPES = {"view": "container", "stackView": "container", "scrollView": "container", "tableView": "list", "collectionView": "list", "label": "text", "button": "button", "textField": "input", "textView": "input", "imageView": "image", "separator": "divider"}

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() in {".storyboard", ".xib"}

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
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
            def convert(element: ET.Element) -> str | None:
                nonlocal count
                tag = _local(element.tag)
                if tag in {"connections", "constraints", "resources", "dependencies", "outlet", "segue", "constraint"}: return None
                count += 1; attrs = _attrs(element); node_type = self.TYPES.get(tag, "custom"); line = _line(context.text, f"<{tag}")
                node_id = f"{screen_id}-{_slug(attrs.get('id') or tag)}-{count}"
                node: dict[str, Any] = {"type": node_type, "component": tag, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line}, "confidence": "high" if node_type != "custom" else "unsupported", "standardRef": f"project.{platform}.{tag.lower()}", "provenance": {}}
                if node_type != "custom": node["inheritsAppearance"] = True; node["provenance"]["component"] = property_evidence(context.source, line, tag, self.id, "exact")
                else: result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": tag, "reason": "unsupported-interface-node"})
                text = attrs.get("text") or attrs.get("title") or attrs.get("placeholder")
                if text: node["text"] = text; node["provenance"]["text"] = property_evidence(context.source, line, text, self.id, "exact")
                frame = next((child for child in element if _local(child.tag) == "rect" and _attrs(child).get("key") == "frame"), None)
                if frame is not None:
                    values = _attrs(frame)
                    for attr, key in (("x", "x"), ("y", "y"), ("width", "width"), ("height", "height")):
                        if attr in values: _set(node, f"layout.{key}", _normalize_ref(values[attr]), context, line, f"frame.{attr}={values[attr]}", self.id)
                child_ids: list[str] = []
                for child in element:
                    if not isinstance(child.tag, str) or _local(child.tag) == "rect": continue
                    candidates = list(child) if _local(child.tag) in {"subviews", "objects", "scenes"} else [child]
                    for candidate in candidates:
                        if isinstance(candidate.tag, str) and (child_id := convert(candidate)): child_ids.append(child_id)
                node["children"] = child_ids
                result.nodes[node_id] = node; return node_id
            roots = [child_id for child in controller if isinstance(child.tag, str) and (child_id := convert(child))]
            result.nodes[root_id]["children"] = roots
            result.screens.append({"id": screen_id, "name": name, "root": root_id, "route": "", "platform": platform, "source": {"file": context.source, "line": _line(context.text, name), "symbol": name}, "confidence": "high"})
        return result


class ProjectedMarkupAdapter:
    def __init__(self, web_adapter: Any, kind: str):
        self.web_adapter, self.id = web_adapter, kind
        self.platforms = ("react-native",) if kind == "react-native" else ("web",)
        self.extensions = (".jsx", ".tsx", ".js", ".ts") if kind.startswith("react") else (f".{kind}",)
        self.maturity = "golden"
        self.limitations = ("dynamic expressions are not executed", "project components remain unsupported until mapped")

    def supports(self, context: SourceContext) -> bool:
        suffix = context.path.suffix.lower()
        if self.id == "react-jsx": return suffix in {".jsx", ".tsx", ".js", ".ts"} and "react-web" in context.platforms
        if self.id == "react-native": return suffix in {".jsx", ".tsx", ".js", ".ts"} and any(value.startswith("react-native") for value in context.platforms)
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
        if self.id == "react-native":
            mapping = {"View": "div", "SafeAreaView": "div", "ScrollView": "div", "Text": "span", "Pressable": "button", "TouchableOpacity": "button", "Button": "button", "TextInput": "input", "Image": "img", "FlatList": "ul"}
            for source_tag, target_tag in mapping.items():
                projected = re.sub(fr"(<\/?){source_tag}\b", fr"\1{target_tag}", projected)
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
        if self.id == "react-native":
            target_platform = "windows" if "react-native-windows" in context.platforms else "macos" if "react-native-macos" in context.platforms else "react-native"
            for node in result.nodes.values():
                node["inheritsAppearance"] = True
                node["standardRef"] = f"project.react-native.{str(node.get('component') or node.get('type') or 'view').lower()}"
        else:
            target_platform = "web"
        for screen in result.screens: screen["platform"] = target_platform; screen["name"] = context.path.stem
        return result


def builtin_platform_adapters(web_adapter: Any) -> list[Any]:
    return [
        AndroidXmlAdapter(), SwiftUIAdapter(), XamlAdapter(), FlutterAdapter(), AppleInterfaceXmlAdapter(),
        ProjectedMarkupAdapter(web_adapter, "react-native"), ProjectedMarkupAdapter(web_adapter, "react-jsx"),
        ProjectedMarkupAdapter(web_adapter, "vue"), ProjectedMarkupAdapter(web_adapter, "svelte"),
    ]
