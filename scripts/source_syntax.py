"""Bounded source syntax helpers; offsets always refer to the original source."""

from __future__ import annotations

import re
from typing import Iterator


def mask_literals(text: str) -> str:
    """Hide comments and quoted contents without changing offsets or newlines."""
    output = list(text)
    index = 0
    while index < len(text):
        start = index
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
        elif text.startswith("/*", index):
            depth = 1
            index += 2
            while index < len(text) and depth:
                if text.startswith("/*", index):
                    depth += 1
                    index += 2
                elif text.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
        elif text[index] in {chr(34), chr(39)}:
            quote = text[index]
            delimiter = quote * 3 if text.startswith(quote * 3, index) else quote
            index += len(delimiter)
            while index < len(text):
                if text[index] == chr(92):
                    index += 2
                elif text.startswith(delimiter, index):
                    index += len(delimiter)
                    break
                else:
                    index += 1
        else:
            index += 1
            continue
        for position in range(start, min(index, len(text))):
            if text[position] != "\n":
                output[position] = " "
    return "".join(output)


def closing(text: str, start: int) -> int | None:
    masked = mask_literals(text)
    pairs = {"(": ")", "{": "}", "[": "]"}
    if start >= len(text) or masked[start] not in pairs:
        return None
    stack = []
    for index in range(start, len(masked)):
        char = masked[index]
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")}]":
            if not stack or char != stack.pop():
                return None
            if not stack:
                return index
    return None


def arguments(text: str) -> list[str]:
    masked = mask_literals(text)
    depth = 0
    start = 0
    result = []
    for index, char in enumerate(masked):
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    if text[start:].strip():
        result.append(text[start:].strip())
    return result


def named_argument(text: str, name: str, separator: str = "=") -> str | None:
    for argument in arguments(text):
        match = re.match(rf"{re.escape(name)}\s*{re.escape(separator)}\s*([\s\S]*)", argument)
        if match:
            return match.group(1).strip()
    return None


def modifier_calls(text: str) -> list[tuple[str, str]]:
    result = []
    cursor = 0
    masked = mask_literals(text)
    while match := re.search(r"\.(\w+)\s*\(", masked[cursor:]):
        start = cursor + match.end() - 1
        end = closing(text, start)
        if end is None:
            break
        result.append((match.group(1), text[start + 1:end]))
        cursor = end + 1
    return result


def substitute_identifiers(text: str, bindings: dict[str, str]) -> str:
    masked = mask_literals(text)
    for match in reversed(list(re.finditer(r"\b[A-Za-z_]\w*\b", masked))):
        if match.start() and masked[match.start()-1] == ".":
            continue
        if re.match(r"\s*(?::|=(?!=))", masked[match.end():]):
            continue
        if match.group() in bindings:
            text = text[:match.start()] + bindings[match.group()] + text[match.end():]
    return text
