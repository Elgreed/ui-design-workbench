"""Resolve literal Compose theme values and local font assets without executing Kotlin."""

from __future__ import annotations

import re
from collections import defaultdict

from compose_syntax import arguments, closing, mask_literals, named_argument
from fidelity_core import property_evidence


WEIGHTS = {"Thin": 100, "ExtraLight": 200, "Light": 300, "Normal": 400, "Medium": 500,
           "SemiBold": 600, "Bold": 700, "ExtraBold": 800, "Black": 900}


def expression_at(text: str, start: int) -> str:
    masked = mask_literals(text)
    depth = 0
    for index in range(start, len(text)):
        char = masked[index]
        if char in "({[":
            depth += 1
        elif char in ")}]":
            if depth == 0:
                return text[start:index].strip()
            depth -= 1
        elif char in "\n;," and depth == 0:
            return text[start:index].strip()
    return text[start:].strip()


class ComposeResources:
    def __init__(self, contexts):
        self.definitions = defaultdict(list)
        self.aliases = {}
        self.fonts = []
        self.bindings = defaultdict(set)
        self._resolved = {}
        self.contexts = [context for context in contexts if context.path.suffix == ".kt" and
                         (context.role == "theme" or "/theme/" in context.source)]
        for context in self.contexts:
            text = context.text
            for match in re.finditer(r"\bval\s+(\w+)\s*(?::\s*[\w<>?.]+)?\s*=\s*", mask_literals(text)):
                self.definitions[match.group(1)].append((expression_at(text, match.end()), context, match.start()))
            for function in re.finditer(r"\bfun\s+(\w+)\s*\(\s*\)\s*:\s*Brush\s*\{", mask_literals(text)):
                end = closing(text, text.find("{", function.start()))
                body = text[function.end():end] if end is not None else ""
                gradients = list(re.finditer(r"Brush\.verticalGradient\s*\(", mask_literals(body)))
                if len(gradients) == 1:
                    start = gradients[0].start()
                    gradient_end = closing(body, body.find("(", start))
                    if gradient_end is not None:
                        from compose_instances import substitute
                        bindings = {match.group(1): expression_at(body, match.end()) for match in
                                    re.finditer(r"\bval\s+(\w+)\s*=\s*", mask_literals(body[:start]))}
                        gradient = substitute(body[start:gradient_end + 1], bindings)
                        self.definitions[function.group(1) + "()"].append((gradient, context, function.start()))
            for match in re.finditer(r"\bval\s+Typography\.(\w+)\s*:\s*TextStyle\s+get\(\)\s*=\s*(\w+)", text):
                self.aliases[f"MaterialTheme.typography.{match.group(1)}"] = match.group(2)
            for match in re.finditer(r"\bobject\s+(\w+)\s*\{", mask_literals(text)):
                end = closing(text, text.find("{", match.start()))
                body = text[match.end():end] if end is not None else ""
                for prop in re.finditer(r"\bval\s+(\w+)\s*:\s*\w+[\s\S]*?get\(\)\s*=\s*(\w+)\.current", body):
                    self.aliases[f"{match.group(1)}.{prop.group(1)}"] = prop.group(2)
            for match in re.finditer(r"\bMaterialTheme\s*\(", mask_literals(text)):
                start = text.find("(", match.start())
                end = closing(text, start)
                if end is None:
                    continue
                for name in ("typography", "colorScheme", "shapes"):
                    value = named_argument(text[start + 1:end], name)
                    if value:
                        self.bindings[name].add(value)
        for name, values in self.bindings.items():
            if len(values) == 1:
                self.aliases[f"MaterialTheme.{name}"] = next(iter(values))
        for name, definitions in self.definitions.items():
            if len(definitions) != 1 or not definitions[0][0].startswith("FontFamily("):
                continue
            expression, context, offset = definitions[0]
            for match in re.finditer(r"\bFont\s*\(", expression):
                start = expression.find("(", match.start())
                end = closing(expression, start)
                if end is None:
                    continue
                args = expression[start + 1:end]
                resource = re.search(r"R\.font\.(\w+)", args)
                if resource is None:
                    continue
                assets = [path for path in context.root.glob(f"**/src/main/res/font/{resource.group(1)}.*")
                          if path.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}]
                if len(assets) != 1:
                    continue
                weight = (named_argument(args, "weight") or "FontWeight.Normal").split(".")[-1]
                self.fonts.append({"family": name, "asset": assets[0].relative_to(context.root).as_posix(),
                                   "weight": WEIGHTS.get(weight, 400), "style": "normal"})

    def resolve(self, expression, dark=False, seen=None):
        if not isinstance(expression, str) or seen is not None:
            return self._resolve(expression, dark, seen)
        key = (expression.strip(), dark)
        if key not in self._resolved:
            self._resolved[key] = self._resolve(expression, dark, set())
        return self._resolved[key]

    def _resolve(self, expression, dark=False, seen=None):
        if not isinstance(expression, str):
            return expression
        expression = expression.strip()
        from compose_instances import static_value
        selected = static_value(expression, {})
        if selected != expression:
            return self.resolve(selected, dark, seen)
        seen = set(seen or ())
        if expression in seen or len(seen) > 24:
            return None
        seen.add(expression)
        dimension = re.fullmatch(r"(-?\d+(?:\.\d+)?)\.(?:dp|sp)", expression)
        if dimension:
            return f"{dimension.group(1)}px"
        if expression.startswith("FontWeight."):
            return WEIGHTS.get(expression.split(".")[-1])
        color = re.fullmatch(r"Color\(0x([\da-fA-F]{8})\)", expression)
        if color:
            value = color.group(1).lower()
            return "#" + value[2:] + (value[:2] if value[:2] != "ff" else "")
        if expression in {"Color.White", "Color.Black", "Color.Transparent"}:
            return {"Color.White": "#ffffff", "Color.Black": "#000000", "Color.Transparent": "transparent"}[expression]
        conditional = re.fullmatch(r"if\s*\(\s*darkTheme\s*\)\s*(\w+)\s+else\s+(\w+)", expression)
        if conditional:
            return self.resolve(conditional.group(1 if dark else 2), dark, seen)
        for alias in sorted(self.aliases, key=len, reverse=True):
            if expression == alias or expression.startswith(alias + "."):
                value = self.resolve(self.aliases[alias], dark, seen)
                for part in expression[len(alias):].strip(".").split(".") if expression != alias else []:
                    value = value.get(part) if isinstance(value, dict) else None
                return value
        if expression in self.definitions:
            definitions = self.definitions[expression]
            if len(definitions) != 1:
                return None
            value = definitions[0][0]
            if value.startswith("FontFamily("):
                return expression if any(font["family"] == expression for font in self.fonts) else None
            local = re.fullmatch(r"staticCompositionLocalOf\s*\{\s*(\w+)\s*}", value, re.S)
            return self.resolve(local.group(1) if local else value, dark, seen)
        if re.fullmatch(r"\w+(?:\.\w+)+", expression):
            parts = expression.split(".")
            value = self.resolve(parts[0], dark, seen)
            for part in parts[1:]:
                value = value.get(part) if isinstance(value, dict) else None
            return value
        call = re.match(r"\w+\s*\(", expression)
        if expression.startswith("RoundedCornerShape("):
            values = arguments(expression[len("RoundedCornerShape("):-1])
            if len(values) == 1 and "=" not in values[0]:
                return self.resolve(values[0], dark, seen)
        if expression.startswith("Brush.verticalGradient("):
            args = expression[len("Brush.verticalGradient("):-1]
            colors = named_argument(args, "colors")
            if colors and colors.startswith("listOf("):
                values = [self.resolve(value, dark, seen) for value in arguments(colors[7:-1])]
                if len(values) >= 2 and all(isinstance(value, str) and value.startswith("#") for value in values):
                    return "linear-gradient(to bottom, " + ", ".join(values) + ")"
        if call and closing(expression, expression.find("(")) == len(expression) - 1:
            values = {}
            for argument in arguments(expression[expression.find("(") + 1:-1]):
                field = re.match(r"(\w+)\s*=\s*([\s\S]+)", argument)
                if field:
                    value = self.resolve(field.group(2), dark, seen)
                    if value is not None:
                        values[field.group(1)] = value
            return values or None
        return None

    def resolve_local(self, expression, context, dark=False):
        value = self.resolve(expression, dark)
        if value is not None or not re.fullmatch(r"\w+", expression.strip()):
            return value
        definitions = list(re.finditer(rf"\bval\s+{re.escape(expression.strip())}\s*=\s*", mask_literals(context.text)))
        if len(definitions) == 1:
            return self.resolve(expression_at(context.text, definitions[0].end()), dark)
        return None

    def apply(self, result, context):
        from fidelity_adapters import _compose_named_value
        for node in result.nodes.values():
            for group in ("layout", "style"):
                for key, expression in list(node.get(group, {}).items()):
                    resolved = self.resolve(expression)
                    if resolved is not None and not isinstance(resolved, dict):
                        node[group][key] = resolved
            # Node call arguments are kept local to this translation pass.
            args = node.pop("_composeArguments", "")
            style_expression = _compose_named_value(args, "style")
            typography = self.resolve(style_expression)
            if isinstance(typography, dict):
                for key in ("fontSize", "fontFamily", "fontWeight", "lineHeight", "letterSpacing"):
                    if key in typography and key not in node["style"]:
                        node["style"][key] = typography[key]
                        node["provenance"][f"style.{key}"] = property_evidence(context.source, node["source"]["line"], style_expression, "compose", "high")
            color_expression = _compose_named_value(args, "color")
            color = self.resolve(color_expression)
            if isinstance(color, str) and color.startswith("#"):
                key = "backgroundColor" if node.get("component") == "Surface" else "color"
                node["style"][key] = color
                node["provenance"][f"style.{key}"] = property_evidence(context.source, node["source"]["line"], color_expression, "compose", "high")
                dark_color = self.resolve(color_expression, dark=True)
                if isinstance(dark_color, str) and dark_color != color:
                    node.setdefault("_composeDarkStyle", {})[key] = dark_color
            def assign(group, key, value, expression):
                if value is not None:
                    node[group][key] = value
                    node["provenance"][f"{group}.{key}"] = property_evidence(context.source, node["source"]["line"], expression, "compose", "high")
                    dark_value = self.resolve(expression, dark=True)
                    if isinstance(dark_value, dict):
                        dark_value = dark_value.get({"borderColor": "color", "borderWidth": "width"}.get(key, key))
                    if group == "style" and isinstance(dark_value, (str, int, float)) and dark_value != value:
                        node.setdefault("_composeDarkStyle", {})[key] = dark_value
            shape = _compose_named_value(args, "shape")
            radius = self.resolve(shape)
            if isinstance(radius, str):
                assign("style", "radius", radius, shape)
            border_expression = _compose_named_value(args, "border")
            border = self.resolve(border_expression)
            if isinstance(border, dict):
                assign("style", "borderWidth", border.get("width"), border_expression)
                assign("style", "borderColor", border.get("color"), border_expression)
                assign("style", "borderStyle", "solid", border_expression)
            padding_expression = _compose_named_value(args, "contentPadding")
            padding = self.resolve(padding_expression)
            if isinstance(padding, dict):
                for key in ("horizontal", "vertical", "top", "bottom", "start", "end"):
                    target = {"start": "Left", "end": "Right"}.get(key, key.title())
                    assign("layout", "padding" + target, padding.get(key), padding_expression)
            if node.get("component") == "Button":
                for key, role in (("backgroundColor", "primary"), ("color", "onPrimary")):
                    if key not in node["style"]:
                        assign("style", key, self.resolve("MaterialTheme.colorScheme." + role), "MaterialTheme.colorScheme." + role)
            if node.get("component") == "RadioButton":
                role = "primary" if node.get("checked") else "onSurfaceVariant"
                assign("style", "color", self.resolve("MaterialTheme.colorScheme." + role), "MaterialTheme.colorScheme." + role)
