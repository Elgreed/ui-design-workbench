#!/usr/bin/env python3
"""Read-only Apple asset, color, localization, and symbol resolution."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".build", ".swiftpm", ".ui-design-workbench", "build", "DerivedData", "Pods", "vendor"}
FILE_LIMIT = 30000


@dataclass(frozen=True)
class AppleResource:
    value: str
    source: str
    confidence: str = "high"


def _component(value: Any) -> int:
    raw = str(value or "0").strip()
    try:
        number = int(raw, 16) / 255 if raw.lower().startswith("0x") else float(raw)
    except ValueError:
        number = 0
    return max(0, min(255, round(number * 255)))


def _color_value(payload: dict[str, Any]) -> str | None:
    components = payload.get("components", {}) if isinstance(payload, dict) else {}
    if not isinstance(components, dict):
        return None
    red, green, blue = (_component(components.get(key)) for key in ("red", "green", "blue"))
    alpha = _component(components.get("alpha", 1))
    return f"#{red:02x}{green:02x}{blue:02x}" if alpha == 255 else f"#{red:02x}{green:02x}{blue:02x}{alpha:02x}"


class AppleResourceCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.images: dict[str, AppleResource] = {}
        self.colors: dict[str, AppleResource] = {}
        self.strings: dict[str, AppleResource] = {}
        self.diagnostics: list[dict[str, Any]] = []

    @classmethod
    def discover(cls, root: Path) -> "AppleResourceCatalog":
        catalog = cls(root)
        seen = 0
        for directory, names, files in os.walk(catalog.root):
            names[:] = [name for name in names if name not in IGNORED_DIRS and not name.startswith(".")]
            folder = Path(directory)
            for filename in files:
                seen += 1
                if seen > FILE_LIMIT:
                    catalog.diagnostics.append({"reason": "apple-resource-file-limit", "limit": FILE_LIMIT})
                    return catalog
                path = folder / filename
                if filename == "Contents.json" and folder.suffix.lower() in {".imageset", ".colorset"}:
                    catalog._read_asset(path)
                elif path.suffix.lower() == ".strings" and folder.name.lower().endswith(".lproj"):
                    catalog._read_strings(path)
        return catalog

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    def _read_asset(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.diagnostics.append({"reason": "invalid-apple-asset-catalog", "file": self._relative(path)})
            return
        name = path.parent.stem
        if path.parent.suffix.lower() == ".imageset":
            candidates = [item for item in payload.get("images", []) if isinstance(item, dict) and item.get("filename")]
            candidates.sort(key=lambda item: ({"1x": 0, "2x": 1, "3x": 2}.get(str(item.get("scale")), -1), item.get("idiom") == "universal"), reverse=True)
            if candidates:
                image = path.parent / str(candidates[0]["filename"])
                if image.is_file():
                    self.images[name] = AppleResource(self._relative(image), self._relative(path))
        else:
            candidates = [item for item in payload.get("colors", []) if isinstance(item, dict) and isinstance(item.get("color"), dict)]
            universal = next((item for item in candidates if item.get("idiom") == "universal"), candidates[0] if candidates else None)
            value = _color_value(universal["color"]) if universal else None
            if value:
                self.colors[name] = AppleResource(value, self._relative(path))

    def _read_strings(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        source = self._relative(path)
        for match in re.finditer(r'"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)"\s*;', text):
            try:
                key = json.loads(f'"{match.group(1)}"')
                value = json.loads(f'"{match.group(2)}"')
            except json.JSONDecodeError:
                continue
            self.strings.setdefault(key, AppleResource(value, source))

    def image(self, name: str) -> AppleResource | None:
        return self.images.get(str(name or "").strip())

    def color(self, name: str) -> AppleResource | None:
        return self.colors.get(str(name or "").strip())

    def localized(self, key: str) -> AppleResource | None:
        return self.strings.get(str(key or "").strip())


SF_SYMBOL_PATHS = {
    "plus": "M12 5v14M5 12h14",
    "xmark": "M6 6l12 12M18 6L6 18",
    "checkmark": "M5 12l4 4L19 6",
    "magnifyingglass": "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13M15.5 15.5L21 21",
    "house": "M3 11.5L12 4l9 7.5V21h-6v-6H9v6H3z",
    "gearshape": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2",
    "trash": "M5 7h14M9 7V4h6v3M7 7l1 14h8l1-14M10 10v7M14 10v7",
    "pencil": "M4 20l4-1 11-11-3-3L5 16zM14 7l3 3",
}


def sf_symbol_asset(name: str) -> str | None:
    key = str(name or "").split(".", 1)[0].lower()
    path = SF_SYMBOL_PATHS.get(key)
    if not path:
        return None
    fill = ' fill="currentColor"' if key == "house" else ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path}"{fill}/></svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
