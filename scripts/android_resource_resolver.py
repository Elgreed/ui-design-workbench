#!/usr/bin/env python3
"""Deterministic Android resource resolution for structural HTML projection.

The resolver reads source resources only. It never invokes aapt, Gradle, or
Layoutlib and therefore keeps unresolved qualifiers/runtime attributes explicit.
"""

from __future__ import annotations

import base64
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".gradle", ".idea", ".ui-design-workbench", "build", "dist", "node_modules", "out", "vendor"}
FILE_LIMIT = 30000
TEXT_LIMIT = 2 * 1024 * 1024

ANDROID_SCREEN_LAYOUT_PREFIXES = (
    "activity_", "fragment_", "dialog_", "scene_", "screen_", "page_",
    "bottom_sheet_", "sheet_",
)
ANDROID_COMPONENT_LAYOUT_PREFIXES = (
    "cell_", "item_", "row_", "list_item_", "grid_item_", "include_",
    "partial_", "content_", "merge_", "component_", "widget_",
)


def _local(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attrs(element: ET.Element) -> dict[str, str]:
    return {_local(key): str(value) for key, value in element.attrib.items()}


def _line(text: str, expression: str) -> int:
    offset = text.find(expression)
    return text.count("\n", 0, max(0, offset)) + 1 if offset >= 0 else 1


def _normalize_dimension(value: str) -> str:
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)(dp|dip|sp|pt|px)", value.strip())
    return f"{match.group(1)}px" if match else value.strip()


def _color_literal(value: str) -> str:
    raw = value.strip()
    argb = re.fullmatch(r"#([0-9a-fA-F]{8})", raw)
    if argb:
        alpha, red, green, blue = (argb.group(1)[index:index + 2] for index in (0, 2, 4, 6))
        if alpha.lower() == "ff":
            return f"#{red}{green}{blue}"
        return f"#{red}{green}{blue}{alpha}"
    return raw


def android_layout_role(path: Path, text: str) -> str:
    """Conservatively distinguish Android screens from reusable layouts.

    Unprefixed layouts remain screens for backwards compatibility. Explicit
    component/partial prefixes and ``<merge>`` roots are never promoted into
    the screen tree merely because they live under ``res/layout``.
    """
    normalized = path.as_posix().lower()
    if path.suffix.lower() != ".xml" or "/res/layout" not in f"/{normalized}":
        return "unknown"
    stem = path.stem.lower()
    if stem.startswith(ANDROID_COMPONENT_LAYOUT_PREFIXES):
        return "component"
    if stem.startswith(ANDROID_SCREEN_LAYOUT_PREFIXES):
        return "screen"
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "screen"
    if _local(root.tag) == "merge":
        return "component"
    return "screen"


@dataclass(frozen=True)
class ResolvedAndroidValue:
    value: Any
    source: str
    line: int
    kind: str
    confidence: str = "exact"
    resolved: bool = True


@dataclass
class AndroidDrawable:
    asset: str | None = None
    style: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    line: int = 1
    kind: str = "unresolved"
    confidence: str = "exact"


@dataclass
class _ResourceEntry:
    value: str
    source: str
    line: int
    qualifier: str
    priority: int


@dataclass
class _StyleEntry:
    name: str
    parent: str
    items: dict[str, str]
    source: str
    line: int
    priority: int


class AndroidResourceCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.values: dict[tuple[str, str], _ResourceEntry] = {}
        self.styles: dict[str, _StyleEntry] = {}
        self.drawables: dict[tuple[str, str], Path] = {}
        self.layouts: dict[str, Path] = {}
        self.theme_items: dict[str, str] = {}
        self.diagnostics: list[dict[str, Any]] = []

    @classmethod
    def discover(cls, root: Path) -> "AndroidResourceCatalog":
        catalog = cls(root)
        seen = 0
        for directory, names, files in os.walk(catalog.root):
            names[:] = [name for name in names if name not in IGNORED_DIRS and not name.startswith(".")]
            folder = Path(directory)
            resource_dir = folder.name.lower()
            if not (resource_dir.startswith("values") or resource_dir.startswith("drawable") or resource_dir.startswith("mipmap") or resource_dir.startswith("layout")):
                continue
            qualifier = resource_dir.split("-", 1)[1] if "-" in resource_dir else ""
            priority = 0 if not qualifier else 10
            for name in files:
                seen += 1
                if seen > FILE_LIMIT:
                    catalog.diagnostics.append({"reason": "android-resource-file-limit", "limit": FILE_LIMIT})
                    break
                path = folder / name
                if resource_dir.startswith("values") and path.suffix.lower() == ".xml":
                    catalog._read_values(path, qualifier, priority)
                elif resource_dir.startswith("layout") and path.suffix.lower() == ".xml":
                    catalog._prefer_path(catalog.layouts, path.stem, path, priority)
                elif resource_dir.startswith(("drawable", "mipmap")):
                    kind = "mipmap" if resource_dir.startswith("mipmap") else "drawable"
                    catalog._prefer_path(catalog.drawables, (kind, path.stem), path, priority)
        catalog._select_theme_items()
        return catalog

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _prefer_path(bucket: dict[Any, Path], key: Any, path: Path, priority: int) -> None:
        current = bucket.get(key)
        if current is None or (priority == 0 and "-" in current.parent.name):
            bucket[key] = path

    def _read_text(self, path: Path) -> str:
        try:
            if path.stat().st_size > TEXT_LIMIT:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _read_values(self, path: Path, qualifier: str, priority: int) -> None:
        text = self._read_text(path)
        if not text:
            return
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            self.diagnostics.append({"reason": "invalid-android-resource-xml", "file": self._relative(path), "line": getattr(exc, "position", (1,))[0]})
            return
        if _local(root.tag) != "resources":
            return
        source = self._relative(path)
        for child in root:
            tag, attrs = _local(child.tag), _attrs(child)
            name = attrs.get("name")
            if not name:
                continue
            if tag == "style":
                items = {
                    _attrs(item).get("name", ""): (item.text or "").strip()
                    for item in child if _local(item.tag) == "item" and _attrs(item).get("name")
                }
                current = self.styles.get(name)
                if current is None or priority < current.priority:
                    self.styles[name] = _StyleEntry(name, attrs.get("parent", ""), items, source, _line(text, name), priority)
                continue
            kind = attrs.get("type") if tag == "item" else tag
            value = "".join(child.itertext()).strip()
            if not kind or not value:
                continue
            key = (kind, name)
            current = self.values.get(key)
            if current is None or priority < current.priority:
                self.values[key] = _ResourceEntry(value, source, _line(text, name), qualifier, priority)

    def _style_items(self, name: str, seen: set[str] | None = None) -> dict[str, str]:
        clean = name.removeprefix("@style/")
        if not clean:
            return {}
        seen = seen or set()
        if clean in seen:
            return {}
        seen.add(clean)
        entry = self.styles.get(clean)
        if not entry:
            return {}
        parent = entry.parent.removeprefix("@style/")
        if not parent and "." in clean:
            parent = clean.rsplit(".", 1)[0]
        merged = self._style_items(parent, seen) if parent else {}
        merged.update(entry.items)
        return merged

    def style(self, reference: str | None) -> tuple[dict[str, str], _StyleEntry | None]:
        name = str(reference or "").removeprefix("@style/")
        return self._style_items(name), self.styles.get(name)

    def _select_theme_items(self) -> None:
        candidates = sorted((entry for name, entry in self.styles.items() if "theme" in name.lower()), key=lambda item: (item.priority, item.name))
        if candidates:
            self.theme_items = self._style_items(candidates[0].name)

    def resolve(self, raw: Any, preferred_kind: str = "", style_items: dict[str, str] | None = None, _seen: set[tuple[str, str]] | None = None) -> ResolvedAndroidValue:
        value = str(raw or "").strip()
        if not value:
            return ResolvedAndroidValue(value, "", 1, preferred_kind or "literal", resolved=False)
        attr = re.fullmatch(r"\?(?:android:)?attr/([\w.-]+)", value)
        if attr:
            name = attr.group(1)
            candidate = (style_items or {}).get(name) or self.theme_items.get(name)
            if candidate:
                resolved = self.resolve(candidate, preferred_kind, style_items, _seen)
                return ResolvedAndroidValue(resolved.value, resolved.source, resolved.line, resolved.kind, "approximate", resolved.resolved)
            return ResolvedAndroidValue(value, "", 1, "attr", "approximate", False)
        match = re.fullmatch(r"@(?:(android):)?([\w.-]+)/([\w.-]+)", value)
        if not match:
            normalized = _normalize_dimension(_color_literal(value))
            return ResolvedAndroidValue(normalized, "", 1, preferred_kind or "literal")
        system, kind, name = match.groups()
        if system:
            system_values = {("color", "transparent"): "transparent", ("color", "black"): "#000000", ("color", "white"): "#ffffff"}
            if (kind, name) in system_values:
                return ResolvedAndroidValue(system_values[(kind, name)], "android", 1, kind, "high")
            return ResolvedAndroidValue(value, "android", 1, kind, "approximate", False)
        key = (kind, name)
        seen = _seen or set()
        if key in seen:
            return ResolvedAndroidValue(value, "", 1, kind, "approximate", False)
        seen.add(key)
        entry = self.values.get(key)
        if not entry:
            return ResolvedAndroidValue(value, "", 1, kind, "approximate", False)
        resolved = self.resolve(entry.value, kind, style_items, seen)
        return ResolvedAndroidValue(resolved.value, entry.source, entry.line, kind, resolved.confidence, resolved.resolved)

    def layout(self, reference: str) -> Path | None:
        match = re.fullmatch(r"@layout/([\w.-]+)", str(reference or "").strip())
        return self.layouts.get(match.group(1)) if match else None

    def drawable(self, reference: str, style_items: dict[str, str] | None = None) -> AndroidDrawable:
        match = re.fullmatch(r"@(?:(drawable|mipmap))/([\w.-]+)", str(reference or "").strip())
        if not match:
            return AndroidDrawable(kind="unresolved", confidence="approximate")
        kind, name = match.groups()
        path = self.drawables.get((kind, name)) or self.drawables.get(("drawable", name))
        if not path:
            return AndroidDrawable(source="", kind="unresolved", confidence="approximate")
        source = self._relative(path)
        if path.suffix.lower() != ".xml":
            return AndroidDrawable(asset=source, source=source, kind="bitmap")
        text = self._read_text(path)
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return AndroidDrawable(source=source, kind="unresolved", confidence="approximate")
        tag = _local(root.tag)
        if tag == "vector":
            asset = self._vector_data_uri(root, style_items)
            return AndroidDrawable(asset=asset, source=source, line=1, kind="vector", confidence="high" if asset else "approximate")
        if tag == "shape":
            return AndroidDrawable(style=self._shape_style(root, style_items), source=source, line=1, kind="shape", confidence="high")
        return AndroidDrawable(source=source, kind=tag, confidence="approximate")

    def _vector_data_uri(self, root: ET.Element, style_items: dict[str, str] | None) -> str | None:
        attrs = _attrs(root)
        width = _normalize_dimension(attrs.get("width", "24dp"))
        height = _normalize_dimension(attrs.get("height", "24dp"))
        viewport_width = attrs.get("viewportWidth", "24")
        viewport_height = attrs.get("viewportHeight", "24")
        paths: list[str] = []
        for child in root:
            if _local(child.tag) != "path":
                return None
            item = _attrs(child)
            data = item.get("pathData")
            if not data:
                continue
            fill = self.resolve(item.get("fillColor", "#000000"), "color", style_items)
            stroke = self.resolve(item.get("strokeColor", ""), "color", style_items) if item.get("strokeColor") else None
            attributes = [f'd="{data}"', f'fill="{fill.value if fill.resolved else "currentColor"}"']
            if item.get("fillAlpha"): attributes.append(f'fill-opacity="{item["fillAlpha"]}"')
            if stroke and stroke.resolved: attributes.append(f'stroke="{stroke.value}"')
            if item.get("strokeWidth"): attributes.append(f'stroke-width="{item["strokeWidth"]}"')
            paths.append(f"<path {' '.join(attributes)}/>")
        if not paths:
            return None
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {viewport_width} {viewport_height}">{"".join(paths)}</svg>'
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")

    def _shape_style(self, root: ET.Element, style_items: dict[str, str] | None) -> dict[str, Any]:
        style: dict[str, Any] = {}
        for child in root:
            tag, attrs = _local(child.tag), _attrs(child)
            if tag == "solid" and attrs.get("color"):
                resolved = self.resolve(attrs["color"], "color", style_items)
                if resolved.resolved: style["backgroundColor"] = resolved.value
            elif tag == "corners":
                radius = attrs.get("radius")
                if radius: style["radius"] = _normalize_dimension(radius)
            elif tag == "stroke":
                if attrs.get("width"): style["borderWidth"] = _normalize_dimension(attrs["width"])
                if attrs.get("color"):
                    resolved = self.resolve(attrs["color"], "color", style_items)
                    if resolved.resolved: style["borderColor"] = resolved.value
                style["borderStyle"] = "solid"
        return style


MATERIAL_ICON_PATHS = {
    "add": "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    "check": "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    "close": "M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.41 4.29 19.71 2.88 18.3 9.17 12 2.88 5.7 4.29 4.29 10.59 10.59 16.89 4.29z",
    "delete": "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM8 9h8v10H8V9zm7.5-5-1-1h-5l-1 1H5v2h14V4z",
    "edit": "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34a.9959.995 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
    "home": "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
    "menu": "M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z",
    "search": "M9.5 3a6.5 6.5 0 1 0 3.98 11.64L19.85 21 21 19.85l-6.36-6.37A6.5 6.5 0 0 0 9.5 3zm0 2a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9z",
    "settings": "M19.43 12.98c.04-.32.07-.65.07-.98s-.03-.66-.08-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.37-.31-.6-.22l-2.49 1c-.52-.4-1.08-.73-1.69-.98L14.5 2.42A.488.488 0 0 0 14 2h-4c-.25 0-.46.18-.49.42L9.13 5.07c-.61.25-1.18.59-1.69.98l-2.49-1a.49.49 0 0 0-.6.22l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.05.32-.08.66-.08.98s.03.66.08.98l-2.11 1.65a.49.49 0 0 0-.12.64l2 3.46c.12.22.37.31.6.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.18-.58 1.69-.98l2.49 1c.23.08.48 0 .6-.22l2-3.46a.49.49 0 0 0-.12-.64l-2.11-1.65zM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5z",
}


def material_icon_asset(name: str) -> str | None:
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).replace("_", " ").strip().lower().replace(" ", "")
    path = MATERIAL_ICON_PATHS.get(key)
    if not path:
        return None
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="currentColor" d="{path}"/></svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
