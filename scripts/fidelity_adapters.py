#!/usr/bin/env python3
"""Provider-neutral source adapter API with built-in Web and Compose adapters."""

from __future__ import annotations

import html.parser
import re
from typing import Any

from android_resource_resolver import AndroidResourceCatalog, material_icon_asset
from fidelity_adapter_api import AdapterResult, SourceContext, UiSourceAdapter, adapter_capabilities, register_adapter, registered_adapters, translate_sources
from fidelity_core import property_evidence, stable_id
from platform_component_catalog import adapter_type_map


def _slug(value: str, fallback: str = "node") -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", value)
    return re.sub(r"[^a-z0-9]+", "-", separated.lower()).strip("-") or fallback


def _css_value(value: str, group: str, tokens: dict[str, Any]) -> Any:
    match = re.fullmatch(r"var\(\s*--([\w-]+)\s*(?:,[^)]+)?\)", value.strip())
    if not match:
        return value.strip()
    name = _slug(match.group(1)).replace("-", "_")
    if name in tokens.get(group, {}):
        return f"${group}.{name}"
    for candidate_group, entries in tokens.items():
        if name in entries:
            return f"${candidate_group}.{name}"
    return value.strip()


CSS_PROPERTY_MAP = {
    "display": ("layout", "display"), "flex-direction": ("layout", "direction"), "gap": ("layout", "gap"),
    "width": ("layout", "width"), "height": ("layout", "height"), "min-width": ("layout", "minWidth"),
    "min-height": ("layout", "minHeight"), "max-width": ("layout", "maxWidth"), "padding": ("layout", "padding"),
    "margin": ("layout", "margin"), "align-items": ("layout", "align"), "justify-content": ("layout", "justify"),
    "background": ("style", "background"), "background-color": ("style", "backgroundColor"), "color": ("style", "color"),
    "border": ("style", "border"), "border-color": ("style", "borderColor"), "border-width": ("style", "borderWidth"),
    "border-radius": ("style", "radius"), "box-shadow": ("style", "boxShadow"), "font-family": ("style", "fontFamily"),
    "font-size": ("style", "fontSize"), "font-weight": ("style", "fontWeight"), "line-height": ("style", "lineHeight"),
    "text-align": ("style", "textAlign"), "opacity": ("style", "opacity"),
}


def _token_group(name: str, value: str) -> str:
    lower = name.lower()
    if value.strip().startswith(("#", "rgb", "hsl")) or any(part in lower for part in ("color", "bg", "surface", "text", "accent")):
        return "colors"
    if "radius" in lower:
        return "radii"
    if any(part in lower for part in ("font", "line-height", "type")):
        return "typography"
    return "spacing"


class _HtmlTreeParser(html.parser.HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.counter = 0
        self.roots: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.counter += 1
        node = {"tag": tag.lower(), "attrs": dict(attrs), "children": [], "text": "", "line": self.getpos()[0], "index": self.counter}
        (self.stack[-1]["children"] if self.stack else self.roots).append(node)
        if tag.lower() not in {"img", "input", "br", "hr", "meta", "link"}:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]["tag"] == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag.lower():
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.stack and data.strip():
            self.stack[-1]["text"] += (" " if self.stack[-1]["text"] else "") + " ".join(data.split())


class WebAdapter:
    id = "web"
    platforms = ("web",)
    extensions = (".html", ".htm", ".css")
    maturity = "golden"
    structural_tier = "translated"
    visual_tier = "projection"
    native_evidence_required = False
    limitations = ("simple CSS selectors only", "runtime-generated DOM is unsupported")

    def supports(self, context: SourceContext) -> bool:
        return context.path.suffix.lower() in {".html", ".htm"}

    @staticmethod
    def _css(context: SourceContext) -> tuple[dict[str, dict[str, tuple[str, int, str]]], dict[str, Any], list[dict[str, Any]]]:
        rules: dict[str, dict[str, tuple[str, int, str]]] = {}
        tokens: dict[str, Any] = {"colors": {}, "spacing": {}, "radii": {}, "typography": {}}
        unsupported: list[dict[str, Any]] = []
        texts: list[tuple[str, str]] = [(context.source, context.text)]
        for css_path in sorted(context.path.parent.glob("*.css")):
            try:
                texts.append((css_path.relative_to(context.root).as_posix(), css_path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
        for source, text in texts:
            for token in re.finditer(r"--([\w-]+)\s*:\s*([^;{}]+);", text):
                name, value = token.group(1), token.group(2).strip()
                group = _token_group(name, value)
                tokens[group][_slug(name).replace("-", "_")] = {"value": value, "source": {"file": source, "line": text.count("\n", 0, token.start()) + 1}, "adapter": "web"}
            for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", text, re.S):
                selectors, body = block.group(1).strip(), block.group(2)
                line = text.count("\n", 0, block.start()) + 1
                for selector in (part.strip() for part in selectors.split(",")):
                    if not re.fullmatch(r"(?:[a-zA-Z][\w-]*|\.[\w-]+|#[\w-]+|:root)", selector):
                        unsupported.append({"adapter": "web", "file": source, "line": line, "expression": selector, "reason": "unsupported-css-selector"})
                        continue
                    bucket = rules.setdefault(selector, {})
                    for declaration in re.finditer(r"([\w-]+)\s*:\s*([^;]+)", body):
                        prop, value = declaration.group(1).lower(), declaration.group(2).strip()
                        if prop.startswith("--"):
                            continue
                        if prop not in CSS_PROPERTY_MAP:
                            unsupported.append({"adapter": "web", "file": source, "line": line, "expression": f"{prop}: {value}", "reason": "unsupported-css-property"})
                            continue
                        bucket[prop] = (value, line, source)
        return rules, tokens, unsupported

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
        rules, result.tokens, result.unsupported = self._css(context)
        parser = _HtmlTreeParser(context.source)
        parser.feed(context.text)
        body = next((item for item in parser.roots if item["tag"] == "html"), None)
        roots = body["children"] if body else parser.roots
        body_node = next((item for item in roots if item["tag"] == "body"), None)
        roots = body_node["children"] if body_node else roots
        screen_id = _slug(context.path.stem, "web-screen")
        root_id = f"{screen_id}-root"
        used: set[str] = set()

        def convert(item: dict[str, Any]) -> str | None:
            tag = item["tag"]
            if tag in {"script", "style", "head", "title", "meta", "link"}:
                return None
            attrs = item["attrs"]
            base = _slug(attrs.get("id") or f"{tag}-{item['index']}")
            node_id = f"{screen_id}-{base}"
            while node_id in used:
                node_id += "-2"
            used.add(node_id)
            node_type = adapter_type_map("web", "web").get(tag, "container")
            if tag in {"ul", "ol"}: node_type = "list"
            elif tag == "li": node_type = "card"
            elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "label", "small", "strong"}: node_type = "text"
            elif tag in {"button", "a"}: node_type = "button"
            elif tag in {"input", "textarea", "select"}: node_type = "input"
            elif tag == "img": node_type = "image"
            elif tag == "hr": node_type = "divider"
            node: dict[str, Any] = {"type": node_type, "component": tag, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": item["line"]}, "confidence": "high", "standardRef": f"html.{tag}", "inheritsAppearance": True, "provenance": {"component": property_evidence(context.source, item["line"], tag, self.id, "exact")}}
            if item["text"]:
                node["text"] = item["text"]
                node["provenance"]["text"] = property_evidence(context.source, item["line"], item["text"], self.id, "exact")
            if node_type == "image" and attrs.get("src"):
                node["asset"] = attrs["src"]
                node["provenance"]["asset"] = property_evidence(context.source, item["line"], attrs["src"], self.id, "exact")
            if tag == "a" and attrs.get("href"):
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": item["line"], "expression": attrs["href"], "reason": "route-resolution-required"})
            selectors = [tag]
            if attrs.get("id"): selectors.append(f"#{attrs['id']}")
            selectors.extend(f".{name}" for name in str(attrs.get("class") or "").split())
            declarations: dict[str, tuple[str, int, str]] = {}
            for selector in selectors:
                declarations.update(rules.get(selector, {}))
            inline = attrs.get("style") or ""
            for declaration in re.finditer(r"([\w-]+)\s*:\s*([^;]+)", inline):
                declarations[declaration.group(1).lower()] = (declaration.group(2).strip(), item["line"], context.source)
            for prop, (value, line, source) in declarations.items():
                if prop not in CSS_PROPERTY_MAP:
                    continue
                group, key = CSS_PROPERTY_MAP[prop]
                if prop == "flex-direction": value = "column" if value == "column" else "row"
                node[group][key] = _css_value(value, "colors" if group == "style" else "spacing", result.tokens)
                node["provenance"][f"{group}.{key}"] = property_evidence(source, line, f"{prop}: {value}", self.id, "exact")
            child_ids = [child_id for child in item["children"] if (child_id := convert(child))]
            node["children"] = child_ids
            result.nodes[node_id] = node
            return node_id

        child_ids = [node_id for item in roots if (node_id := convert(item))]
        result.nodes[root_id] = {
            "type": "container", "layout": {"direction": "column", "width": "fill", "height": "fill"}, "style": {}, "children": child_ids,
            "source": {"file": context.source, "line": 1}, "confidence": "high", "standardRef": "html.document",
            "provenance": {
                "layout.direction": property_evidence(context.source, 1, "document flow", self.id, "high"),
                "layout.width": property_evidence(context.source, 1, "viewport width", self.id, "high"),
                "layout.height": property_evidence(context.source, 1, "viewport height", self.id, "high"),
            },
        }
        result.screens.append({"id": screen_id, "name": context.path.stem, "root": root_id, "route": "", "platform": "web", "source": {"file": context.source, "line": 1, "symbol": context.path.stem}, "confidence": "high"})
        return result


COMPOSE_TYPES = {
    "Column": "container", "Row": "container", "Box": "container", "LazyColumn": "list", "LazyRow": "list",
    "Scaffold": "container", "Card": "card", "ElevatedCard": "card", "OutlinedCard": "card", "Surface": "card",
    "Text": "text", "Button": "button", "FilledTonalButton": "button", "OutlinedButton": "button", "TextButton": "button",
    "IconButton": "button", "FloatingActionButton": "button", "ExtendedFloatingActionButton": "button",
    "TextField": "input", "OutlinedTextField": "input", "SearchBar": "input", "Image": "image", "Icon": "icon",
    "Checkbox": "container", "Switch": "container", "RadioButton": "container", "ListItem": "card",
    "NavigationBar": "container", "NavigationRail": "container", "TopAppBar": "container", "CenterAlignedTopAppBar": "container",
    "LinearProgressIndicator": "container", "CircularProgressIndicator": "container", "Spacer": "spacer",
}

COMPOSE_PROJECT_LAYOUTS = {"Column", "Row", "Box", "LazyColumn", "LazyRow", "Spacer"}
COMPOSE_TYPES.update(adapter_type_map("android", "compose"))


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


def _compose_calls(body: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(COMPOSE_TYPES, key=len, reverse=True)) + r")\s*\(")
    for match in pattern.finditer(body):
        open_paren = body.find("(", match.start())
        close_paren = _balanced_close(body, open_paren, "(", ")")
        if close_paren is None:
            continue
        cursor = close_paren + 1
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        block_end = _balanced_close(body, cursor, "{", "}") if cursor < len(body) and body[cursor] == "{" else None
        calls.append({"widget": match.group(1), "start": match.start(), "args": body[open_paren + 1:close_paren], "blockStart": cursor if block_end is not None else None, "blockEnd": block_end})
    return calls


def _compose_modifier_calls(value: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for match in re.finditer(r"\.(\w+)\s*\(", value):
        open_paren = value.find("(", match.start())
        close_paren = _balanced_close(value, open_paren, "(", ")")
        if close_paren is not None:
            calls.append((match.group(1), value[open_paren + 1:close_paren]))
    return calls


def _compose_length(value: str, tokens: dict[str, Any], group: str = "spacing") -> Any:
    clean = value.strip()
    dimension = re.fullmatch(r"(-?\d+(?:\.\d+)?)\.(?:dp|sp)", clean)
    if dimension:
        return f"{dimension.group(1)}px"
    number = re.fullmatch(r"-?\d+(?:\.\d+)?", clean)
    if number:
        return float(clean) if "." in clean else int(clean)
    token_name = _slug(clean).replace("-", "_")
    if token_name in tokens.get(group, {}):
        return f"${group}.{token_name}"
    for candidate, entries in tokens.items():
        if token_name in entries:
            return f"${candidate}.{token_name}"
    return clean


def _compose_color(value: str) -> str | None:
    clean = value.strip()
    argb = re.fullmatch(r"Color\(0x([0-9a-fA-F]{8})\)", clean)
    if argb:
        alpha, red, green, blue = (argb.group(1)[index:index + 2] for index in (0, 2, 4, 6))
        return f"#{red}{green}{blue}" if alpha.lower() == "ff" else f"#{red}{green}{blue}{alpha}"
    rgb = re.fullmatch(r"Color\(0x([0-9a-fA-F]{6})\)", clean)
    if rgb:
        return f"#{rgb.group(1)}"
    named = {"Black": "#000000", "White": "#ffffff", "Red": "#f44336", "Green": "#4caf50", "Blue": "#2196f3", "Transparent": "transparent"}
    match = re.fullmatch(r"Color\.(\w+)", clean)
    return named.get(match.group(1)) if match else None


def _compose_named_value(args: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([^,\n]+)", args)
    return match.group(1).strip() if match else None


def _set_compose(node: dict[str, Any], path: str, value: Any, context: SourceContext, line: int, expression: str, adapter: str, confidence: str = "exact") -> None:
    group, key = path.split(".", 1)
    node.setdefault(group, {})[key] = value
    node.setdefault("provenance", {})[path] = property_evidence(context.source, line, expression, adapter, confidence)


class ComposeAdapter:
    id = "compose"
    platforms = ("android",)
    extensions = (".kt", ".kts")
    maturity = "structural"
    structural_tier = "translated"
    visual_tier = "none"
    native_evidence_required = True
    native_providers = ("android-compose-screenshot", "paparazzi", "roborazzi", "android-emulator")
    resource_resolution = ("R.string", "R.drawable", "R.mipmap", "common Material Icons")
    layout_features = ("size/fill/weight/aspectRatio", "directional padding", "Row/Column arrangement", "Box alignment", "basic typography")
    limitations = ("supported Compose primitives and modifiers only", "custom composables remain explicit unsupported entries")

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
        return context.path.suffix.lower() in {".kt", ".kts"} and ("@Composable" in context.text or "androidx.compose" in context.text)

    def translate(self, context: SourceContext) -> AdapterResult:
        result = AdapterResult(adapter=self.id)
        catalog = self._catalog(context)
        platform = "android"
        for match in re.finditer(r"(?:val|const\s+val)\s+(\w+)\s*=\s*(Color\([^\n]+?\)|[^\s]+\.(?:dp|sp))", context.text):
            name, value = match.group(1), match.group(2).strip()
            group = "colors" if value.startswith("Color") else "typography" if value.endswith(".sp") else "spacing"
            normalized = re.sub(r"(\d+(?:\.\d+)?)\.(?:dp|sp)", r"\1px", value)
            result.tokens[group][_slug(name).replace("-", "_")] = {"value": normalized, "source": {"file": context.source, "line": context.text.count("\n", 0, match.start()) + 1}, "adapter": self.id}
        functions = list(re.finditer(r"@Composable[\s\S]*?fun\s+([A-Z]\w*)\s*\([^)]*\)\s*\{", context.text))
        for function_index, function in enumerate(functions):
            name = function.group(1)
            start = function.end()
            depth, end = 1, start
            while end < len(context.text) and depth:
                depth += (context.text[end] == "{") - (context.text[end] == "}")
                end += 1
            body = context.text[start:max(start, end - 1)]
            screen_id = _slug(name)
            root_id = f"{screen_id}-root"
            result.nodes[root_id] = {"type": "container", "layout": {"direction": "column", "width": "fill", "height": "fill"}, "style": {}, "children": [], "source": {"file": context.source, "line": context.text.count("\n", 0, function.start()) + 1, "symbol": name}, "confidence": "high", "standardRef": f"project.{platform}.compose.screen", "provenance": {
                "layout.direction": property_evidence(context.source, context.text.count("\n", 0, function.start()) + 1, f"@Composable fun {name}", self.id, "high"),
                "layout.width": property_evidence(context.source, context.text.count("\n", 0, function.start()) + 1, f"@Composable fun {name}", self.id, "high"),
                "layout.height": property_evidence(context.source, context.text.count("\n", 0, function.start()) + 1, f"@Composable fun {name}", self.id, "high"),
            }}
            calls = _compose_calls(body)
            call_nodes: list[tuple[dict[str, Any], str]] = []
            for count, call in enumerate(calls, start=1):
                widget, args = call["widget"], call["args"]
                node_id = f"{screen_id}-{_slug(widget)}-{count}"
                line = context.text.count("\n", 0, start + call["start"]) + 1
                native_prefix = "material3"
                standard = f"project.{platform}.compose.{widget.lower()}" if widget in COMPOSE_PROJECT_LAYOUTS else f"{native_prefix}.{widget.lower()}"
                node: dict[str, Any] = {"type": COMPOSE_TYPES[widget], "component": widget, "layout": {}, "style": {}, "children": [], "source": {"file": context.source, "line": line, "symbol": name}, "confidence": "high", "standardRef": standard, "provenance": {"component": property_evidence(context.source, line, widget, self.id, "exact")}}
                if standard.startswith("material3."):
                    node["inheritsAppearance"] = True
                conditional_roles = {"Checkbox": "checkbox", "Switch": "switch", "RadioButton": "radio"}
                if widget in conditional_roles:
                    callback_name = "onCheckedChange" if widget in {"Checkbox", "Switch"} else "onClick"
                    callback = _compose_named_value(args, callback_name)
                    if callback and callback != "null":
                        node["semantics"] = {"role": conditional_roles[widget]}
                        node["provenance"]["semantics.role"] = property_evidence(context.source, line, f"{callback_name} = {callback}", self.id, "high")
                literal = re.search(r"(?:text\s*=\s*)?\"([^\"]*)\"", args)
                if literal and node["type"] in {"text", "button", "input"}:
                    node["text"] = literal.group(1)
                    node["provenance"]["text"] = property_evidence(context.source, line, literal.group(0), self.id, "exact")
                string_resource = re.search(r"stringResource\s*\(\s*R\.string\.(\w+)\s*\)", args)
                if string_resource and node["type"] in {"text", "button", "input"}:
                    resolved = catalog.resolve(f"@string/{string_resource.group(1)}", "string")
                    if resolved.resolved:
                        node["text"] = resolved.value
                        node["provenance"]["text"] = property_evidence(resolved.source, resolved.line, string_resource.group(0), self.id, resolved.confidence)
                    else:
                        result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": string_resource.group(0), "reason": "unresolved-android-string"})
                if widget in {"Column", "LazyColumn"}:
                    node["layout"]["direction"] = "column"
                    node["provenance"]["layout.direction"] = property_evidence(context.source, line, widget, self.id, "exact")
                if widget in {"Row", "LazyRow"}:
                    node["layout"]["direction"] = "row"
                    node["provenance"]["layout.direction"] = property_evidence(context.source, line, widget, self.id, "exact")
                if widget == "Box":
                    node["layout"]["direction"] = "overlay"
                    node["provenance"]["layout.direction"] = property_evidence(context.source, line, widget, self.id, "exact")
                alignments = {
                    "Alignment.Start": "start", "Alignment.CenterHorizontally": "center", "Alignment.End": "end",
                    "Alignment.Top": "start", "Alignment.CenterVertically": "center", "Alignment.Bottom": "end",
                }
                arrangements = {
                    "Arrangement.Start": "start", "Arrangement.Top": "start", "Arrangement.End": "end", "Arrangement.Bottom": "end",
                    "Arrangement.Center": "center", "Arrangement.SpaceBetween": "between", "Arrangement.SpaceAround": "around", "Arrangement.SpaceEvenly": "evenly",
                }
                if widget in {"Column", "LazyColumn"}:
                    alignment = _compose_named_value(args, "horizontalAlignment")
                    arrangement = _compose_named_value(args, "verticalArrangement")
                    if alignment in alignments: _set_compose(node, "layout.align", alignments[alignment], context, line, f"horizontalAlignment = {alignment}", self.id)
                    if arrangement in arrangements: _set_compose(node, "layout.justify", arrangements[arrangement], context, line, f"verticalArrangement = {arrangement}", self.id)
                if widget in {"Row", "LazyRow"}:
                    alignment = _compose_named_value(args, "verticalAlignment")
                    arrangement = _compose_named_value(args, "horizontalArrangement")
                    if alignment in alignments: _set_compose(node, "layout.align", alignments[alignment], context, line, f"verticalAlignment = {alignment}", self.id)
                    if arrangement in arrangements: _set_compose(node, "layout.justify", arrangements[arrangement], context, line, f"horizontalArrangement = {arrangement}", self.id)
                if widget == "Box":
                    content_alignment = _compose_named_value(args, "contentAlignment")
                    if content_alignment and "Center" in content_alignment:
                        _set_compose(node, "layout.align", "center", context, line, f"contentAlignment = {content_alignment}", self.id)
                        _set_compose(node, "layout.justify", "center", context, line, f"contentAlignment = {content_alignment}", self.id)
                for method, value in _compose_modifier_calls(args):
                    expression = f".{method}({value})"
                    if method in {"size", "width", "height", "requiredSize", "requiredWidth", "requiredHeight"}:
                        normalized = _compose_length(value.split(",", 1)[0], result.tokens)
                        keys = ("width", "height") if method in {"size", "requiredSize"} else ("width",) if "Width" in method or method == "width" else ("height",)
                        for key in keys: _set_compose(node, f"layout.{key}", normalized, context, line, expression, self.id)
                    elif method == "padding":
                        named = {name: _compose_named_value(value, name) for name in ("horizontal", "vertical", "start", "end", "top", "bottom")}
                        if any(named.values()):
                            key_map = {"horizontal": "paddingHorizontal", "vertical": "paddingVertical", "start": "paddingLeft", "end": "paddingRight", "top": "paddingTop", "bottom": "paddingBottom"}
                            for side_name, raw in named.items():
                                if raw: _set_compose(node, f"layout.{key_map[side_name]}", _compose_length(raw, result.tokens), context, line, expression, self.id)
                        else:
                            _set_compose(node, "layout.padding", _compose_length(value.split(",", 1)[0], result.tokens), context, line, expression, self.id)
                    elif method in {"fillMaxWidth", "fillMaxHeight", "fillMaxSize"}:
                        keys = ("width", "height") if method == "fillMaxSize" else ("width",) if method == "fillMaxWidth" else ("height",)
                        for key in keys: _set_compose(node, f"layout.{key}", "fill", context, line, expression, self.id)
                    elif method == "weight":
                        _set_compose(node, "layout.grow", _compose_length(value.split(",", 1)[0], result.tokens), context, line, expression, self.id)
                    elif method == "aspectRatio":
                        _set_compose(node, "layout.aspectRatio", _compose_length(value.split(",", 1)[0], result.tokens), context, line, expression, self.id)
                    elif method in {"verticalScroll", "horizontalScroll"}:
                        _set_compose(node, "layout.overflowY" if method == "verticalScroll" else "layout.overflowX", "auto", context, line, expression, self.id)
                    elif method == "align":
                        target = next((mapped for source, mapped in alignments.items() if source in value), None)
                        if target: _set_compose(node, "layout.alignSelf", target, context, line, expression, self.id)
                    elif method == "background":
                        color = _compose_color(value.split(",", 1)[0])
                        if color: _set_compose(node, "style.backgroundColor", color, context, line, expression, self.id)
                    elif method == "clip":
                        radius = re.search(r"RoundedCornerShape\s*\(\s*([^)]+)\)", value)
                        if radius: _set_compose(node, "style.radius", _compose_length(radius.group(1), result.tokens), context, line, expression, self.id)
                font_size = _compose_named_value(args, "fontSize")
                if font_size: _set_compose(node, "style.fontSize", _compose_length(font_size, result.tokens, "typography"), context, line, f"fontSize = {font_size}", self.id)
                line_height = _compose_named_value(args, "lineHeight")
                if line_height: _set_compose(node, "style.lineHeight", _compose_length(line_height, result.tokens, "typography"), context, line, f"lineHeight = {line_height}", self.id)
                letter_spacing = _compose_named_value(args, "letterSpacing")
                if letter_spacing: _set_compose(node, "style.letterSpacing", _compose_length(letter_spacing, result.tokens, "typography"), context, line, f"letterSpacing = {letter_spacing}", self.id)
                font_weight = _compose_named_value(args, "fontWeight")
                weight_map = {"FontWeight.Normal": 400, "FontWeight.Medium": 500, "FontWeight.SemiBold": 600, "FontWeight.Bold": 700, "FontWeight.ExtraBold": 800}
                if font_weight in weight_map: _set_compose(node, "style.fontWeight", weight_map[font_weight], context, line, f"fontWeight = {font_weight}", self.id)
                color_value = _compose_named_value(args, "color")
                color = _compose_color(color_value) if color_value else None
                if color: _set_compose(node, "style.color", color, context, line, f"color = {color_value}", self.id)
                text_align = _compose_named_value(args, "textAlign")
                if text_align:
                    _set_compose(node, "style.textAlign", text_align.rsplit(".", 1)[-1].lower(), context, line, f"textAlign = {text_align}", self.id)
                if widget == "Icon":
                    icon = re.search(r"Icons\.(?:Default|Filled|Outlined|Rounded|Sharp|TwoTone)\.(\w+)", args)
                    if icon:
                        node["iconName"] = icon.group(1)
                        asset = material_icon_asset(icon.group(1))
                        if asset:
                            node["asset"] = asset
                            node["provenance"]["asset"] = property_evidence(context.source, line, icon.group(0), self.id, "high")
                        else:
                            result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": icon.group(0), "reason": "unsupported-material-icon"})
                painter = re.search(r"painterResource\s*\(\s*(?:id\s*=\s*)?R\.(drawable|mipmap)\.(\w+)\s*\)", args)
                if painter:
                    drawable = catalog.drawable(f"@{painter.group(1)}/{painter.group(2)}")
                    if drawable.asset:
                        node["asset"] = drawable.asset
                        node["provenance"]["asset"] = property_evidence(drawable.source, drawable.line, painter.group(0), self.id, drawable.confidence)
                    else:
                        result.unsupported.append({"adapter": self.id, "file": context.source, "line": line, "expression": painter.group(0), "reason": "unsupported-android-drawable"})
                description = _compose_named_value(args, "contentDescription")
                if description and description != "null":
                    node["alt"] = description.strip('"')
                    node["semantics"] = {"label": node["alt"], "role": "image" if node["type"] in {"image", "icon"} else "button"}
                result.nodes[node_id] = node
                call_nodes.append((call, node_id))
            for call, node_id in call_nodes:
                parents = [
                    (candidate, candidate_id) for candidate, candidate_id in call_nodes
                    if candidate["blockStart"] is not None and candidate["blockEnd"] is not None
                    and candidate["blockStart"] < call["start"] < candidate["blockEnd"]
                ]
                parent_id = max(parents, key=lambda item: item[0]["blockStart"])[1] if parents else root_id
                result.nodes[parent_id]["children"].append(node_id)
                if result.nodes[parent_id].get("layout", {}).get("direction") == "overlay":
                    result.nodes[node_id].setdefault("layout", {})["gridArea"] = "1 / 1"
            supported_names = set(COMPOSE_TYPES) | {"Modifier", "Color", "RoundedCornerShape"}
            for unknown in re.finditer(r"\b([A-Z]\w*)\s*\(", body):
                if unknown.group(1) in supported_names:
                    continue
                result.unsupported.append({"adapter": self.id, "file": context.source, "line": context.text.count("\n", 0, start + unknown.start()) + 1, "expression": unknown.group(1), "reason": "unsupported-compose-call"})
            result.screens.append({"id": screen_id, "name": name, "root": root_id, "route": "", "platform": platform, "source": {"file": context.source, "line": context.text.count("\n", 0, function.start()) + 1, "symbol": name}, "confidence": "high"})
        return result


register_adapter(WebAdapter())
register_adapter(ComposeAdapter())
from fidelity_platform_adapters import builtin_platform_adapters

for _adapter in builtin_platform_adapters(WebAdapter()):
    register_adapter(_adapter)
