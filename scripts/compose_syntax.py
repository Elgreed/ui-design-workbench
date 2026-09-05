"""Bounded Kotlin syntax helpers; offsets always refer to the original source."""

from __future__ import annotations

import re
from typing import Iterator


from source_syntax import arguments, closing, mask_literals, named_argument


def composable_functions(text: str) -> Iterator[dict]:
    masked = mask_literals(text)
    # A declaration may have visibility modifiers, annotations and function-typed parameters.
    pattern = re.compile(r"@Composable\b(?:(?!\bfun\b)[\s\S])*?\bfun\s+([A-Z]\w*)\s*\(")
    cursor = 0
    while match := pattern.search(masked, cursor):
        open_paren = masked.find("(", match.start(1))
        end_args = closing(text, open_paren)
        if end_args is None:
            break
        body_start = end_args + 1
        while body_start < len(text) and masked[body_start].isspace():
            body_start += 1
        if masked[body_start:body_start + 1] == ":":
            return_type = re.match(r":\s*Unit\s*", masked[body_start:])
            body_start += len(return_type.group()) if return_type else 0
        if masked[body_start:body_start + 1] != "{":
            cursor = end_args + 1
            continue
        body_end = closing(text, body_start)
        if body_end is None:
            break
        yield {"name": match.group(1), "start": match.start(), "bodyStart": body_start + 1,
               "bodyEnd": body_end, "parameters": text[open_paren + 1:end_args]}
        cursor = body_end + 1
