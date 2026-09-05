"""Static argument substitution for bounded local Compose component instances."""

from __future__ import annotations

import re
import os

from compose_syntax import arguments, closing, mask_literals, named_argument


def substitute(expression: str, bindings: dict[str, str]) -> str:
    masked = mask_literals(expression)
    edits = []
    for match in re.finditer(r"\b[A-Za-z_]\w*\b", masked):
        if match.start() > 0 and masked[match.start() - 1] == ".":
            continue
        # Named argument keys and lambda parameter declarations are not values.
        tail = masked[match.end():]
        if re.match(r"\s*=(?!=)", tail) or re.match(r"\s*->", tail):
            continue
        value = bindings.get(match.group())
        if value is not None and value != match.group():
            edits.append((match.start(), match.end(), value))
    for start, end, value in reversed(edits):
        expression = expression[:start] + value + expression[end:]
    return expression


def static_value(expression: str, bindings: dict[str, str]) -> str:
    expression = substitute(expression, bindings).strip()
    # Read authored constructor fixtures such as ScreenState(selected = Choice.ONE).selected.
    for match in reversed(list(re.finditer(r"\b[A-Z]\w*\s*\(", mask_literals(expression)))):
        start = expression.find("(", match.start())
        end = closing(expression, start)
        member = re.match(r"\.(\w+)", expression[end + 1:]) if end is not None else None
        if member:
            value = named_argument(expression[start + 1:end], member.group(1))
            if value is not None:
                expression = expression[:match.start()] + value + expression[end + 1 + member.end():]
    equality = re.fullmatch(r"([A-Z]\w*\.\w+|true|false|null)\s*==\s*([A-Z]\w*\.\w+|true|false|null)", expression)
    if equality:
        return "true" if equality.group(1) == equality.group(2) else "false"
    condition = re.match(r"if\s*\(\s*([^()]+)\s*\)\s*", expression)
    if condition:
        test = condition.group(1).strip()
        equality = re.fullmatch(r"([A-Z]\w*\.\w+|true|false)\s*==\s*([A-Z]\w*\.\w+|true|false)", test)
        selected = test == "true" if test in {"true", "false"} else equality.group(1) == equality.group(2) if equality else None
        if selected is not None:
            branch_start = condition.end()
            if expression[branch_start:branch_start + 1] == "{":
                branch_end = closing(expression, branch_start)
                if branch_end is not None:
                    alternative = re.match(r"\s*else\s*", expression[branch_end + 1:])
                    if alternative:
                        second = expression[branch_end + 1 + alternative.end():].strip()
                        return (expression[branch_start + 1:branch_end] if selected else second.removeprefix("{").removesuffix("}")).strip()
            inline = re.fullmatch(r"([^\n]+?)\s+else\s+([^\n]+)", expression[branch_start:])
            if inline:
                return inline.group(1 if selected else 2).strip()
    choice = re.match(r"when\s*\(\s*([A-Z]\w*\.\w+)\s*\)\s*\{", expression)
    if choice:
        branches = list(re.finditer(r"(?:^|\n)\s*([A-Z]\w*\.\w+|else)\s*->\s*", expression))
        for index, branch in enumerate(branches):
            if branch.group(1) in {choice.group(1), "else"}:
                end = branches[index + 1].start() if index + 1 < len(branches) else expression.rfind("}")
                return expression[branch.end():end].strip()
    return expression


def bind_parameters(parameters: str, args: str) -> dict[str, str]:
    result = {}
    names = []
    for parameter in arguments(parameters):
        match = re.match(r"(\w+)\s*:", parameter.strip())
        if not match:
            continue
        name = match.group(1)
        names.append(name)
        default = re.search(r"(?<![=!])=(?!=)", parameter)
        if default:
            result[name] = parameter[default.end():].strip()
    position = 0
    for argument in arguments(args):
        named = re.match(r"(\w+)\s*=\s*([\s\S]+)", argument)
        if named:
            if named.group(1) in names:
                result[named.group(1)] = named.group(2)
        elif position < len(names):
            result[names[position]] = argument
            position += 1
    return result


class StaticImports:
    def __init__(self):
        self.cache = {}
        self.paths = {}

    def source_paths(self, root):
        if root not in self.paths:
            paths = []
            for directory, subdirs, files in os.walk(root):
                subdirs[:] = [name for name in subdirs if name not in {
                    "build", "node_modules", ".git", ".gradle", ".idea", ".codegraph", ".ui-design-workbench"}]
                for name in files:
                    if name.endswith(".kt"):
                        path = root / os.path.relpath(os.path.join(directory, name), root)
                        if "/src/" in path.as_posix():
                            paths.append(path)
            self.paths[root] = paths
        return self.paths[root]

    def sources(self, name, context):
        key = (str(context.root), context.source, name)
        if key not in self.cache:
            imports = re.findall(rf"^import\s+([\w.]+\.{re.escape(name)})\s*$", context.text, re.M)
            paths = []
            for imported in imports:
                package = imported.rsplit(".", 1)[0].replace(".", "/")
                paths.extend(path for path in self.source_paths(context.root)
                             if any(path.parent.as_posix().endswith(f"/{language}/{package}") for language in ("java", "kotlin")))
            self.cache[key] = [(path, path.read_text(encoding="utf-8")) for path in sorted(set(paths)) if path.is_file()]
        return self.cache[key]

    def enum_entries(self, name, context):
        matches = []
        for path, text in self.sources(name, context):
            match = re.search(rf"\benum\s+class\s+{re.escape(name)}\s*\{{([^{{}};]*)}}", mask_literals(text))
            if match:
                entries = [item.strip() for item in match.group(1).split(",") if item.strip()]
                if all(re.fullmatch(r"[A-Z]\w*", item) for item in entries) and len(entries) <= 32:
                    matches.append([f"{name}.{item}" for item in entries])
        return matches[0] if len(matches) == 1 else []

    def resolve_properties(self, expression, context):
        for match in reversed(list(re.finditer(r"\b([A-Z]\w*\.\w+)\.(\w+)\b", expression))):
            values = []
            for path, text in self.sources(match.group(2), context):
                owner = match.group(1).split(".")[0]
                declaration = re.search(rf"\bval\s+{owner}\.{match.group(2)}\s*:\s*\w+\s+get\(\)\s*=\s*when\s*\(this\)\s*\{{", text)
                if declaration:
                    end = closing(text, text.find("{", declaration.start()))
                    body = text[declaration.end():end] if end is not None else ""
                    branch = re.search(rf"\b{re.escape(match.group(1))}\s*->\s*(R\.string\.\w+)\b", body)
                    if branch:
                        values.append(branch.group(1))
            if len(values) == 1:
                expression = expression[:match.start()] + values[0] + expression[match.end():]
        return expression

    def expand_calls(self, calls, body, context):
        result = calls
        for loop in re.finditer(r"\b(\w+)\.entries\.forEach\s*\{\s*(\w+)\s*->", mask_literals(body)):
            end = closing(body, body.find("{", loop.start()))
            entries = self.enum_entries(loop.group(1), context)
            if end is None or not entries:
                continue
            enclosed = [call for call in result if loop.end() <= call["start"] < end]
            if enclosed:
                position = result.index(enclosed[0])
                expanded = [{**call, "loopBindings": {**call.get("loopBindings", {}), loop.group(2): entry}, "loopInstance": entry}
                            for entry in entries for call in enclosed]
                result = [call for call in result if call not in enclosed]
                result[position:position] = expanded
        return result
