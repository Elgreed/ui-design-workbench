#!/usr/bin/env python3
"""Read-only multi-platform UI inventory scanner.

The scanner intentionally produces a conservative inventory. It does not run,
build, import, or modify the target repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from fidelity_adapters import SourceContext, registered_adapters, translate_sources
from fidelity_core import FIDELITY_SCHEMA_VERSION, property_evidence, seal_baseline


EXCLUDED_DIRS = {
    ".git", ".gradle", ".idea", ".next", ".nuxt", ".dart_tool",
    "build", "dist", "out", "target", "node_modules", "Pods", "DerivedData",
    "vendor", "coverage", ".codegraph", ".worktrees", ".claude", ".lavish", ".codex",
    ".agents", ".cursor", ".gemini", ".opencode", ".ui-design-workbench",
    ".superpowers",
}
SCANNER_VERSION = 8
SOURCE_EXTENSIONS = {
    ".kt", ".kts", ".xml", ".swift", ".storyboard", ".xib", ".dart",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html",
    ".css", ".scss", ".sass", ".less", ".json", ".yaml", ".yml", ".go",
    ".cs", ".xaml", ".csproj", ".m", ".mm", ".cpp", ".h", ".hpp",
}
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif",
    ".ttf", ".otf", ".woff", ".woff2", ".pdf", ".ico", ".icns",
}
MAX_FILE_BYTES = 1_500_000


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def unique_dicts(items: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        identity = tuple(item.get(key) for key in keys)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def detect_platforms(path: Path, text: str) -> list[str]:
    suffix = path.suffix.lower()
    normalized = path.as_posix().lower()
    lower = text.lower()
    found: list[str] = []
    android_tv = any(marker in lower for marker in (
        "androidx.tv.", "androidx.leanback.", "android.software.leanback",
        "leanback_launcher", "tv-material", "compose for tv",
    ))
    android_tv_leanback = "androidx.leanback." in lower or "browsesupportfragment" in lower
    if suffix in {".kt", ".kts"}:
        if "@composable" in lower or "androidx.compose" in text:
            found.append("android-tv-compose" if android_tv else "android-compose")
        if re.search(r"\b(Activity|Fragment|RecyclerView|ViewBinding|BrowseSupportFragment)\b", text):
            found.append("android-tv-leanback" if android_tv_leanback else "android-tv-views" if android_tv else "android-views")
    if suffix == ".xml" and "/res/" in f"/{normalized}":
        if android_tv:
            found.append("android-tv-views")
        elif any(segment in normalized for segment in ("/layout", "/navigation", "/values")):
            found.append("android-views")
    if suffix == ".xml" and android_tv:
        found.append("android-tv-views")
    if suffix in {".swift", ".storyboard", ".xib", ".m", ".mm"}:
        catalyst = any(marker in text for marker in ("targetEnvironment(macCatalyst)", ".macCatalyst"))
        appkit = any(marker in text for marker in ("import AppKit", "NSApplication", "NSWindow", "NSViewController", "#import <Cocoa/Cocoa.h>", "NSWindowController")) or 'targetRuntime="MacOSX.Cocoa"' in text
        macos = appkit or any(marker in text for marker in ("MenuBarExtra", "#if os(macOS)", ".macOS("))
        swiftui = re.search(r"\b(struct|class)\s+\w+\s*:\s*View\b", text) or "import SwiftUI" in text
        if catalyst:
            found.append("mac-catalyst")
        elif swiftui:
            found.append("swiftui-macos" if macos else "swiftui")
        if appkit:
            found.append("appkit")
        elif "UIViewController" in text or "import UIKit" in text or 'targetRuntime="iOS.CocoaTouch"' in text:
            found.append("uikit")
    if suffix in {".cs", ".xaml", ".csproj", ".cpp", ".h", ".hpp"}:
        winui = any(marker in text for marker in ("Microsoft.UI.Xaml", "Microsoft.WindowsAppSDK", "AppWindow", "<NavigationView", "<muxc:", "winrt::Microsoft::UI::Xaml"))
        wpf = any(marker in text for marker in ("System.Windows", "UseWPF", "PresentationFramework"))
        wpf = wpf or (not winui and suffix == ".xaml" and any(marker in text for marker in ("<Window", "<Application")))
        if winui:
            found.append("windows-winui")
        if wpf:
            found.append("windows-wpf")
        if suffix == ".xaml" and not (winui or wpf) and any(marker in text for marker in ("x:Class=", "<Page", "<UserControl", "<ResourceDictionary")):
            found.append("windows-xaml")
    if suffix == ".dart" and ("package:flutter" in text or "extends StatelessWidget" in text or "extends StatefulWidget" in text):
        found.append("flutter")
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        if "react-native-windows" in lower:
            found.append("react-native-windows")
        elif "react-native-macos" in lower:
            found.append("react-native-macos")
        elif "react-native" in text or "StyleSheet.create" in text:
            found.append("react-native")
        elif re.search(r"\b(import|require).*react|<[A-Z][A-Za-z0-9_.]*", text):
            found.append("react-web")
        elif any(marker in text for marker in ("document.querySelector", "querySelectorAll(", ".innerHTML", "getElementById(")):
            found.append("web")
    if suffix == ".json" and path.name.lower() in {"package.json", "package-lock.json"}:
        if "react-native-windows" in lower:
            found.append("react-native-windows")
        if "react-native-macos" in lower:
            found.append("react-native-macos")
    if suffix in {".vue", ".svelte", ".html", ".css", ".scss", ".sass", ".less"}:
        found.append("web")
    if suffix == ".go" and re.search(r"\b(?:http\.(?:Handle|HandleFunc)|HandleFunc|ParseFS|ExecuteTemplate|ServeHTTP)\b", text):
        found.append("web")
    if suffix in {".json", ".yaml", ".yml", ".xml", ".kt", ".swift", ".dart", ".ts"} and any(
        word in path.name.lower() for word in ("theme", "token", "color", "typography", "style")
    ):
        found.append("shared-ui")
    return list(dict.fromkeys(found))


def classify_role(path: Path, text: str) -> str:
    name = path.name.lower()
    normalized = path.as_posix().lower()
    if any(word in name for word in ("route", "router", "navigation", "navgraph")) or "navhost" in text.lower():
        return "navigation"
    if any(word in name for word in ("theme", "token", "color", "typography", "style")) or "/res/values" in normalized:
        return "theme"
    if any(word in name for word in ("screen", "page", "view", "activity", "fragment", "window", "dialog")) or "/res/layout" in normalized:
        return "screen"
    if any(word in name for word in ("component", "widget", "control")):
        return "component"
    return "ui-source"


SYMBOL_RULES: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "android-compose": [
        ("composable", re.compile(r"(?:@Composable\s+)?(?:public\s+|private\s+|internal\s+)?fun\s+([A-Z]\w+)\s*\(")),
        ("component", re.compile(r"\b(?:Row|Column|Box|LazyColumn|LazyRow|Scaffold|Card|Button|Text|Image|Icon|TextField)\s*\(")),
    ],
    "android-views": [
        ("class", re.compile(r"\bclass\s+([A-Z]\w+)\s*(?::|extends)")),
    ],
    "android-tv-compose": [
        ("composable", re.compile(r"(?:@Composable\s+)?(?:public\s+|private\s+|internal\s+)?fun\s+([A-Z]\w+)\s*\(")),
        ("component", re.compile(r"\b(?:LazyColumn|LazyRow|Carousel|ImmersiveList|Surface|Button|Card|Text|Image|Icon)\s*\(")),
    ],
    "android-tv-views": [
        ("class", re.compile(r"\bclass\s+([A-Z]\w+)\s*(?::|extends)")),
    ],
    "android-tv-leanback": [
        ("class", re.compile(r"\bclass\s+([A-Z]\w+)\s*(?::|extends)")),
    ],
    "swiftui": [
        ("view", re.compile(r"\bstruct\s+([A-Z]\w+)\s*:\s*View\b")),
    ],
    "uikit": [
        ("view-controller", re.compile(r"\bclass\s+([A-Z]\w+)\s*:\s*UI\w*ViewController\b")),
    ],
    "swiftui-macos": [
        ("view", re.compile(r"\bstruct\s+([A-Z]\w+)\s*:\s*View\b")),
    ],
    "appkit": [
        ("view", re.compile(r"\bclass\s+([A-Z]\w+)\s*:\s*NS(?:View|Window)Controller\b")),
        ("view", re.compile(r"@interface\s+([A-Z]\w+)\s*:\s*NS(?:View|Window)Controller\b")),
    ],
    "windows-winui": [
        ("class", re.compile(r"\b(?:public\s+|internal\s+|partial\s+)*class\s+([A-Z]\w+)")),
        ("view", re.compile(r"x:Class\s*=\s*[\"'][\w.]*\.?([A-Z]\w+)[\"']")),
    ],
    "windows-wpf": [
        ("class", re.compile(r"\b(?:public\s+|internal\s+|partial\s+)*class\s+([A-Z]\w+)")),
        ("view", re.compile(r"x:Class\s*=\s*[\"'][\w.]*\.?([A-Z]\w+)[\"']")),
    ],
    "windows-xaml": [
        ("view", re.compile(r"x:Class\s*=\s*[\"'][\w.]*\.?([A-Z]\w+)[\"']")),
    ],
    "mac-catalyst": [
        ("view", re.compile(r"\bstruct\s+([A-Z]\w+)\s*:\s*View\b")),
        ("view-controller", re.compile(r"\bclass\s+([A-Z]\w+)\s*:\s*UI\w*ViewController\b")),
    ],
    "react-native-windows": [
        ("component", re.compile(r"\b(?:function|class)\s+([A-Z]\w+)|\bconst\s+([A-Z]\w+)\s*=\s*(?:\([^)]*\)|\w+)\s*=>")),
    ],
    "react-native-macos": [
        ("component", re.compile(r"\b(?:function|class)\s+([A-Z]\w+)|\bconst\s+([A-Z]\w+)\s*=\s*(?:\([^)]*\)|\w+)\s*=>")),
    ],
    "flutter": [
        ("widget", re.compile(r"\bclass\s+([A-Z]\w+)\s+extends\s+(?:StatelessWidget|StatefulWidget)\b")),
    ],
    "react-native": [
        ("component", re.compile(r"\b(?:function|class)\s+([A-Z]\w+)|\bconst\s+([A-Z]\w+)\s*=\s*(?:\([^)]*\)|\w+)\s*=>")),
    ],
    "react-web": [
        ("component", re.compile(r"\b(?:function|class)\s+([A-Z]\w+)|\bconst\s+([A-Z]\w+)\s*=\s*(?:\([^)]*\)|\w+)\s*=>")),
    ],
}


ROUTE_PATTERNS = [
    re.compile(r"\bcomposable\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\bpath\s*[:=]\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\broute\s*[:=]\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\bGoRoute\s*\([^)]*?path\s*:\s*[\"']([^\"']+)[\"']", re.S),
    re.compile(r"\bNavigator\.(?:pushNamed|popAndPushNamed)\s*\([^,]+,\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\b(?:navigate|push|replace)\s*\(\s*[\"']([^\"']+)[\"']"),
]
GO_PAGE_ROUTE_PATTERN = re.compile(
    r"\bHandleFunc\s*\(\s*[\"']GET\s+([^\"']+)[\"']\s*,\s*(.*?)\)",
    re.S,
)

HTML_SECTION_PATTERN = re.compile(r"<section\b(?P<attrs>[^>]*)>", re.I)
HTML_NAV_PATTERN = re.compile(
    r"<a\b(?P<attrs>[^>]*\bhref\s*=\s*[\"']#[^\"']+[\"'][^>]*)>(?P<body>.*?)</a>",
    re.I | re.S,
)
HTML_TAB_PATTERN = re.compile(
    r"<button\b(?P<attrs>[^>]*\bid\s*=\s*[\"']tab-([^\"']+)[\"'][^>]*)>(?P<body>.*?)</button>",
    re.I | re.S,
)
HTML_NAV_BLOCK_PATTERN = re.compile(r"<nav\b(?P<attrs>[^>]*)>(?P<body>.*?)</nav>", re.I | re.S)
HTML_NAV_GROUP_OR_LINK_PATTERN = re.compile(
    r"<div\b(?P<group_attrs>[^>]*\bclass\s*=\s*[\"'][^\"']*\bnav-group-label\b[^\"']*[\"'][^>]*)>(?P<group_body>.*?)</div>"
    r"|<a\b(?P<link_attrs>[^>]*\bhref\s*=\s*[\"']#[^\"']+[\"'][^>]*)>(?P<link_body>.*?)</a>",
    re.I | re.S,
)
HTML_DATA_TAB_PATTERN = re.compile(
    r"<button\b(?P<attrs>[^>]*\bdata-(?P<family>[A-Za-z0-9_-]+)-tab\s*=\s*[\"'](?P<value>[^\"']+)[\"'][^>]*)>(?P<body>.*?)</button>",
    re.I | re.S,
)
HTML_DATA_PANEL_PATTERN = re.compile(
    r"<section\b(?P<attrs>[^>]*\bdata-(?P<family>[A-Za-z0-9_-]+)-panel\s*=\s*[\"'](?P<value>[^\"']+)[\"'][^>]*)>",
    re.I,
)
JS_TAB_ARRAY_PATTERN = re.compile(
    r"(?P<array>\[(?:\s*\[\s*[\"'][^\"']+[\"']\s*,\s*[\"'][^\"']+[\"']\s*\]\s*,?){2,}\s*\])"
    r"(?P<tail>.{0,900}?data-(?P<family>[A-Za-z0-9_-]+)-tab\s*=)",
    re.I | re.S,
)
JS_TAB_ITEM_PATTERN = re.compile(r"\[\s*[\"'](?P<id>[^\"']+)[\"']\s*,\s*[\"'](?P<label>[^\"']+)[\"']\s*\]")
HTML_DIALOG_PATTERN = re.compile(
    r"<dialog\b(?P<attrs>[^>]*)>(?P<body>.*?)</dialog>",
    re.I | re.S,
)
HTML_ELEMENT_PATTERN = re.compile(
    r"<(?P<tag>form|div|section|aside)\b(?P<attrs>[^>]*)>",
    re.I,
)
HTML_SECTION_TOKEN_PATTERN = re.compile(r"<section\b(?P<attrs>[^>]*)>|</section\s*>", re.I)


def html_attr(attrs: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']+)[\"']", attrs, re.I)
    return match.group(1).strip() if match else ""


def visible_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def preferred_html_label(value: str) -> str:
    strong = re.search(r"<strong\b[^>]*>(.*?)</strong>", value, re.I | re.S)
    return visible_html_text(strong.group(1) if strong else value)


def view_name(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", value) if part) + "View"


def html_navigation_groups(text: str) -> dict[str, dict[str, str]]:
    """Map hash destinations to their visible label and nearest sidebar group."""
    result: dict[str, dict[str, str]] = {}
    current_group = ""
    for match in HTML_NAV_GROUP_OR_LINK_PATTERN.finditer(text):
        if match.group("group_attrs") is not None:
            current_group = visible_html_text(match.group("group_body") or "")
            continue
        attrs = match.group("link_attrs") or ""
        href = html_attr(attrs, "href")
        if href:
            result.setdefault(href, {
                "label": preferred_html_label(match.group("link_body") or "") or href,
                "group": current_group,
            })
    return result


def html_tab_groups(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for nav in HTML_NAV_BLOCK_PATTERN.finditer(text):
        group = html_attr(nav.group("attrs"), "aria-label")
        for match in HTML_TAB_PATTERN.finditer(nav.group("body")):
            attrs = match.group("attrs")
            tab_id = html_attr(attrs, "id")
            controlled = html_attr(attrs, "aria-controls")
            target = f"#{controlled}" if controlled else f"#panel-{tab_id.removeprefix('tab-')}"
            result[target] = {
                "label": preferred_html_label(match.group("body")) or tab_id,
                "group": group,
            }
    return result


def html_data_tab_candidates(source: str, text: str, navigation: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Discover source-backed tab panels that represent persistent logical views."""
    panels = {
        (match.group("family").lower(), match.group("value")): match
        for match in HTML_DATA_PANEL_PATTERN.finditer(text)
    }
    candidates: list[dict[str, Any]] = []
    for match in HTML_DATA_TAB_PATTERN.finditer(text):
        family = match.group("family").lower()
        value = match.group("value")
        panel = panels.get((family, value))
        if panel is None:
            continue
        parent_fragment = f"#{family.split('-')[0]}"
        parent_nav = navigation.get(parent_fragment, {})
        label = visible_html_text(match.group("body")) or value
        group_path = [item for item in (parent_nav.get("group", ""), parent_nav.get("label", "")) if item]
        candidates.append({
            "name": view_name(f"{family}-{value}"),
            "label": label,
            "file": source,
            "line": line_number(text, panel.start()),
            "platform": "web",
            "confidence": "high",
            "logicalView": True,
            "fragment": f"{parent_fragment}/{value}",
            "selector": f'section[data-{family}-panel="{value}"]',
            "parentFragment": parent_fragment,
            "groupPath": group_path,
            "sourceKind": "html-tab-panel",
        })
    return candidates


def js_data_tab_candidates(source: str, path: Path, text: str) -> list[dict[str, Any]]:
    """Discover deterministic tab sets rendered from literal JS tuple arrays."""
    candidates: list[dict[str, Any]] = []
    source_hint = re.sub(r"^(?:dashboard|admin|cabinet)[_-]?", "", path.stem, flags=re.I)
    for match in JS_TAB_ARRAY_PATTERN.finditer(text):
        family = match.group("family").lower()
        parent_hint = family.split("-")[0] or source_hint
        if parent_hint in {"queue", "detail"} and source_hint:
            parent_hint = source_hint.split("_")[0].split("-")[0]
        parent_fragment = f"#{parent_hint}"
        for item in JS_TAB_ITEM_PATTERN.finditer(match.group("array")):
            value = item.group("id")
            candidates.append({
                "name": view_name(f"{parent_hint}-{value}"),
                "label": item.group("label"),
                "file": source,
                "line": line_number(text, match.start() + item.start()),
                "platform": "web",
                "confidence": "high",
                "logicalView": True,
                "fragment": f"{parent_fragment}/{value}",
                "selector": f'[data-{family}-tab="{value}"]',
                "parentFragment": parent_fragment,
                "groupPath": [],
                "sourceKind": "js-generated-tab",
            })
    return candidates


def section_fragment_at(text: str, offset: int) -> str:
    """Return the innermost explicitly identified section open at offset."""
    stack: list[str] = []
    for match in HTML_SECTION_TOKEN_PATTERN.finditer(text, 0, offset):
        if match.group("attrs") is not None:
            section_id = html_attr(match.group("attrs"), "id")
            stack.append(f"#{section_id}" if section_id else "")
        elif stack:
            stack.pop()
    return next((item for item in reversed(stack) if item), "")


def extract_surface_candidates(source: str, text: str) -> list[dict[str, Any]]:
    """Discover explicit overlays and view states without inflating screen count."""
    surfaces: list[dict[str, Any]] = []
    for match in HTML_DIALOG_PATTERN.finditer(text):
        attrs = match.group("attrs")
        dialog_id = html_attr(attrs, "id")
        if not dialog_id:
            continue
        label = html_attr(attrs, "aria-label")
        if not label:
            heading = re.search(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", match.group("body"), re.I | re.S)
            label = visible_html_text(heading.group(1)) if heading else dialog_id.replace("-", " ")
        surfaces.append({
            "id": f"{source}#dialog-{dialog_id}",
            "label": label,
            "kind": "overlay",
            "state": "dialog-open",
            "file": source,
            "line": line_number(text, match.start()),
            "selector": f"dialog#{dialog_id}",
            "parentFragment": section_fragment_at(text, match.start()),
            "sourceKind": "html-dialog",
            "confidence": "high",
        })

    view_pairs: dict[str, dict[str, re.Match[str]]] = {}
    state_tokens = {"loading", "empty", "error", "success"}
    for match in HTML_ELEMENT_PATTERN.finditer(text):
        attrs = match.group("attrs")
        element_id = html_attr(attrs, "id")
        classes = set(html_attr(attrs, "class").split())
        if element_id:
            pair = re.fullmatch(r"(.+)-(list|detail)-view", element_id, re.I)
            if pair:
                view_pairs.setdefault(pair.group(1).lower(), {})[pair.group(2).lower()] = match
        semantic_state = next((token for token in state_tokens if token in re.split(r"[^a-z0-9]+", element_id.lower())), "")
        if not semantic_state:
            semantic_state = next((token for token in state_tokens if token in {value.lower() for value in classes}), "")
        role = html_attr(attrs, "role").lower()
        if element_id and semantic_state and ("hidden" in attrs.lower() or role in {"alert", "status"}):
            surfaces.append({
                "id": f"{source}#state-{element_id}",
                "label": element_id.replace("-", " "),
                "kind": "state",
                "state": semantic_state,
                "file": source,
                "line": line_number(text, match.start()),
                "selector": f"#{element_id}",
                "parentFragment": section_fragment_at(text, match.start()),
                "sourceKind": "html-state-marker",
                "confidence": "high",
            })
        login_marker = " ".join([element_id, *classes]).lower()
        if element_id and "login" in login_marker and match.group("tag").lower() in {"form", "section"}:
            surfaces.append({
                "id": f"{source}#auth-{element_id}",
                "label": element_id.replace("-", " "),
                "kind": "state",
                "state": "auth-required",
                "file": source,
                "line": line_number(text, match.start()),
                "selector": f"#{element_id}",
                "parentFragment": section_fragment_at(text, match.start()),
                "sourceKind": "html-auth-gate",
                "confidence": "high",
            })

    for prefix, pair in view_pairs.items():
        if set(pair) != {"list", "detail"}:
            continue
        for state, match in pair.items():
            element_id = html_attr(match.group("attrs"), "id")
            surfaces.append({
                "id": f"{source}#logical-state-{element_id}",
                "label": state.title(),
                "kind": "logical-state",
                "state": state,
                "file": source,
                "line": line_number(text, match.start()),
                "selector": f"#{element_id}",
                "parentFragment": section_fragment_at(text, match.start()),
                "stateGroup": prefix,
                "sourceKind": "html-list-detail-pair",
                "confidence": "high",
            })
    return unique_dicts(surfaces, ("id",))


def extract_theme_candidates(path: Path, text: str, source: str) -> list[dict[str, Any]]:
    """Detect only source-evidenced color themes; light remains the display fallback."""
    normalized = path.as_posix().lower()
    candidates: list[dict[str, Any]] = []

    def add(theme_id: str, kind: str, label: str, offset: int, evidence: str) -> None:
        candidates.append({
            "id": slug(theme_id, "theme"),
            "label": label,
            "kind": kind,
            "confidence": "high",
            "sourceRefs": [{"file": source, "line": line_number(text, offset), "evidence": evidence}],
        })

    custom_pattern = re.compile(r"data-theme\s*=\s*[\"']([A-Za-z][A-Za-z0-9_-]*)[\"']", re.I)
    for match in custom_pattern.finditer(text):
        raw = match.group(1)
        kind = "dark" if raw.lower() == "dark" else "light" if raw.lower() == "light" else "custom"
        add(raw, kind, raw.replace("-", " ").title(), match.start(), "data-theme")

    dark_markers = (
        r"prefers-color-scheme\s*:\s*dark",
        r"\bdarkColorScheme\b",
        r"\bisSystemInDarkTheme\s*\(",
        r"\bThemeMode\.dark\b",
        r"\bdarkTheme\s*[:=]",
        r"\bpreferredColorScheme\s*\(\s*\.dark\s*\)",
        r"\bcolorScheme\s*==\s*\.dark\b",
        r"RequestedTheme\s*=\s*[\"']Dark[\"']",
        r"x:Key\s*=\s*[\"']Dark[\"']",
        r"\bTheme\.Dark\b",
        r"\bDayNight\b",
    )
    dark_match = next((match for pattern in dark_markers if (match := re.search(pattern, text, re.I))), None)
    if "/values-night" in normalized and dark_match is None:
        dark_match = re.match(r"", text)
    if dark_match:
        add("dark", "dark", "Dark", dark_match.start(), "platform-dark-theme")

    light_markers = (
        r"\blightColorScheme\b",
        r"\bThemeMode\.light\b",
        r"\blightTheme\s*[:=]",
        r"\bpreferredColorScheme\s*\(\s*\.light\s*\)",
        r"RequestedTheme\s*=\s*[\"']Light[\"']",
        r"x:Key\s*=\s*[\"']Light[\"']",
    )
    light_match = next((match for pattern in light_markers if (match := re.search(pattern, text, re.I))), None)
    if light_match:
        add("light", "light", "Light", light_match.start(), "platform-light-theme")
    return unique_dicts(candidates, ("id", "kind"))


def extract_symbols(text: str, platforms: list[str]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for platform in platforms:
        for kind, pattern in SYMBOL_RULES.get(platform, []):
            for match in pattern.finditer(text):
                groups = [value for value in match.groups() if value]
                name = groups[0] if groups else match.group(0).split("(", 1)[0].strip()
                symbols.append({"name": name, "kind": kind, "line": line_number(text, match.start())})
    return unique_dicts(symbols, ("name", "line", "kind"))[:100]


def extract_routes(text: str, source: str) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    if source.lower().endswith(".go"):
        for match in GO_PAGE_ROUTE_PATTERN.finditer(text):
            handler = match.group(2)
            if re.search(r"(?:Page|HTML|Login|Index)Handler", handler, re.I):
                routes.append({"route": match.group(1), "file": source, "line": line_number(text, match.start())})
        return unique_dicts(routes, ("route", "file", "line"))[:100]
    for pattern in ROUTE_PATTERNS:
        for match in pattern.finditer(text):
            route = match.group(1).strip()
            if not route.startswith(("/", "#")):
                continue
            routes.append({"route": route, "file": source, "line": line_number(text, match.start())})
    return unique_dicts(routes, ("route", "file", "line"))[:100]


def screen_candidates(source: str, path: Path, text: str, platforms: list[str], symbols: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    screen_suffixes = ("Screen", "Page", "View", "Activity", "Fragment", "ViewController", "Window", "WindowController", "Pane")
    for symbol in symbols:
        if symbol["name"].endswith(screen_suffixes) or role == "screen":
            candidates.append({
                "name": symbol["name"],
                "file": source,
                "line": symbol["line"],
                "platform": platforms[0] if platforms else "unknown",
                "confidence": "high" if symbol["name"].endswith(screen_suffixes) else "approximate",
            })
    normalized = path.as_posix().lower()
    if path.suffix.lower() == ".xml" and "/res/layout" in f"/{normalized}":
        candidates.append({
            "name": "".join(part.capitalize() for part in path.stem.split("_")),
            "file": source,
            "line": 1,
            "platform": "android-views",
            "confidence": "high",
        })
    if path.suffix.lower() in {".html", ".htm"}:
        navigation = html_navigation_groups(text)
        navigation.update(html_tab_groups(text))
        for match in HTML_SECTION_PATTERN.finditer(text):
            attrs = match.group("attrs")
            section_id = html_attr(attrs, "id")
            data_section = html_attr(attrs, "data-section")
            classes = set(html_attr(attrs, "class").split())
            if not section_id or not (data_section or {"panel", "view", "screen"} & classes):
                continue
            label = data_section or section_id
            nav_item = navigation.get(f"#{section_id}", {})
            candidates.append({
                "name": view_name(label),
                "label": nav_item.get("label") or label,
                "file": source,
                "line": line_number(text, match.start()),
                "platform": "web",
                "confidence": "high",
                "logicalView": True,
                "fragment": f"#{section_id}",
                "selector": f"section#{section_id}",
                "groupPath": [nav_item["group"]] if nav_item.get("group") else [],
                "sourceKind": "html-section",
            })
        candidates.extend(html_data_tab_candidates(source, text, navigation))
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        candidates.extend(js_data_tab_candidates(source, path, text))
    return unique_dicts(candidates, ("name", "file", "line"))


def extract_navigation_targets(text: str, source: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for match in HTML_NAV_PATTERN.finditer(text):
        href = html_attr(match.group("attrs"), "href")
        if href:
            targets.append({
                "target": href,
                "label": visible_html_text(match.group("body")) or href,
                "file": source,
                "line": line_number(text, match.start()),
            })
    section_ids = {
        html_attr(match.group("attrs"), "id") for match in HTML_SECTION_PATTERN.finditer(text)
        if html_attr(match.group("attrs"), "id")
    }
    for match in HTML_TAB_PATTERN.finditer(text):
        tab_id = html_attr(match.group("attrs"), "id")
        suffix = tab_id.removeprefix("tab-")
        target = f"#panel-{suffix}"
        if target[1:] in section_ids:
            targets.append({
                "target": target,
                "label": visible_html_text(match.group("body")) or suffix,
                "file": source,
                "line": line_number(text, match.start()),
            })
    return unique_dicts(targets, ("target", "file", "line"))


def component_candidates(source: str, platforms: list[str], symbols: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    """Return conservative project-component candidates for later source inspection."""
    candidates: list[dict[str, Any]] = []
    screen_suffixes = ("Screen", "Page", "Activity", "Fragment", "ViewController", "Window", "WindowController", "Pane")
    primitive_names = {
        "Row", "Column", "Box", "LazyColumn", "LazyRow", "Scaffold", "Card",
        "Button", "Text", "Image", "Icon", "TextField",
        "Carousel", "ImmersiveList", "Surface", "NavigationView",
    }
    component_kinds = {"composable", "component", "view", "widget", "class"}
    for symbol in symbols:
        name = str(symbol.get("name", ""))
        if (
            not name
            or name in primitive_names
            or name.endswith(screen_suffixes)
            or symbol.get("kind") not in component_kinds
        ):
            continue
        confidence = "high" if role == "component" else "approximate"
        platform = platforms[0] if platforms else "unknown"
        candidates.append({
            "id": f"{source}#{name}",
            "name": name,
            "platform": platform,
            "kind": "project",
            "source": {"file": source, "line": symbol.get("line", 1), "symbol": name},
            "inspection": "pending",
            "confidence": confidence,
            "variants": [],
            "states": [],
            "tokenRefs": [],
        })
    return unique_dicts(candidates, ("id",))


def iter_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_DIRS]
        current_path = Path(current)
        for filename in files:
            yield current_path / filename


def analyze_file(root: Path, path: Path) -> dict[str, Any] | None:
    """Analyze one candidate file so callers can cache results by content hash."""
    suffix = path.suffix.lower()
    source = relative(path, root)
    if suffix in ASSET_EXTENSIONS:
        return {"path": source, "kind": "asset", "asset": {"path": source, "type": suffix.lstrip(".")}}
    if suffix not in SOURCE_EXTENSIONS:
        return None
    text = read_text(path)
    if text is None:
        return {"path": source, "kind": "skipped", "reason": "large-or-unreadable"}
    platforms = detect_platforms(path, text)
    if not platforms:
        return {"path": source, "kind": "source", "platforms": [], "uiFile": None}
    role = classify_role(path, text)
    symbols = extract_symbols(text, platforms)
    file_routes = extract_routes(text, source)
    file_navigation_targets = extract_navigation_targets(text, source) if suffix in {".html", ".htm"} else []
    surfaces = extract_surface_candidates(source, text) if suffix in {".html", ".htm"} else []
    themes = extract_theme_candidates(path, text, source)
    return {
        "path": source,
        "kind": "source",
        "platforms": platforms,
        "uiFile": {
            "path": source,
            "platforms": platforms,
            "role": role,
            "symbols": symbols,
            "routes": file_routes,
            "navigationTargets": file_navigation_targets,
        },
        "screens": screen_candidates(source, path, text, platforms, symbols, role),
        "routes": file_routes,
        "navigationTargets": file_navigation_targets,
        "surfaces": surfaces,
        "components": component_candidates(source, platforms, symbols, role),
        "themes": themes,
        "tokenFile": source if role == "theme" else None,
    }


def assemble_scan(root: Path, file_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a repository inventory from cached per-file analyses."""
    ui_files: list[dict[str, Any]] = []
    screens: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    navigation_targets: list[dict[str, Any]] = []
    surfaces: list[dict[str, Any]] = []
    theme_candidates: list[dict[str, Any]] = []
    token_files: list[str] = []
    detected: list[str] = []
    skipped_large = 0
    policy_file = ""
    for candidate in (
        root / ".agents" / "ui-policy.json",
        root / ".codex" / "ui-policy.json",
        root / "ui-policy.json",
    ):
        if candidate.is_file():
            policy_file = relative(candidate, root)
            break

    for record in file_records:
        if not isinstance(record, dict):
            continue
        if record.get("kind") == "asset" and isinstance(record.get("asset"), dict):
            assets.append(record["asset"])
            continue
        if record.get("kind") == "skipped":
            skipped_large += 1
            continue
        platforms = record.get("platforms", [])
        if not platforms:
            continue
        detected.extend(platforms)
        if isinstance(record.get("uiFile"), dict):
            ui_files.append(record["uiFile"])
        routes.extend(record.get("routes", []))
        navigation_targets.extend(record.get("navigationTargets", []))
        surfaces.extend(record.get("surfaces", []))
        screens.extend(record.get("screens", []))
        components.extend(record.get("components", []))
        theme_candidates.extend(record.get("themes", []))
        if record.get("tokenFile"):
            token_files.append(str(record["tokenFile"]))

    role_order = {"navigation": 0, "theme": 1, "screen": 2, "component": 3, "ui-source": 4}
    ui_files.sort(key=lambda item: (role_order.get(item["role"], 9), item["path"]))
    screens = unique_dicts(screens, ("name", "file", "line"))
    by_fragment: dict[str, list[dict[str, Any]]] = {}
    for candidate in screens:
        if candidate.get("fragment"):
            by_fragment.setdefault(str(candidate["fragment"]), []).append(candidate)
    for item in screens:
        parent_options = by_fragment.get(str(item.get("parentFragment") or ""), [])
        same_file = [candidate for candidate in parent_options if candidate.get("file") == item.get("file")]
        parent = same_file[0] if len(same_file) == 1 else parent_options[0] if len(parent_options) == 1 else None
        if parent is None:
            continue
        inherited = [str(value) for value in parent.get("groupPath", []) if value]
        parent_label = str(parent.get("label") or parent.get("name") or "")
        item["groupPath"] = list(dict.fromkeys([*inherited, parent_label, *item.get("groupPath", [])]))
    routes = unique_dicts(routes, ("route", "file", "line"))
    components = unique_dicts(components, ("id",))
    navigation_targets = unique_dicts(navigation_targets, ("target", "file", "line"))
    surfaces = unique_dicts(surfaces, ("id",))
    themes_by_id: dict[str, dict[str, Any]] = {
        "light": {"id": "light", "label": "Light", "kind": "light", "confidence": "default", "sourceRefs": []}
    }
    for candidate in theme_candidates:
        theme_id = str(candidate.get("id") or "").strip()
        if not theme_id:
            continue
        current = themes_by_id.setdefault(theme_id, {
            "id": theme_id,
            "label": candidate.get("label") or theme_id,
            "kind": candidate.get("kind") or "custom",
            "confidence": candidate.get("confidence") or "high",
            "sourceRefs": [],
        })
        for source_ref in candidate.get("sourceRefs", []):
            if source_ref not in current["sourceRefs"]:
                current["sourceRefs"].append(source_ref)
        if current["sourceRefs"]:
            current["confidence"] = "high"
    themes = list(themes_by_id.values())
    assets.sort(key=lambda item: item["path"])
    platforms = [platform for platform in dict.fromkeys(detected) if platform != "shared-ui"]
    warnings: list[str] = []
    if not platforms:
        warnings.append("No supported UI platform markers were found.")
    if skipped_large:
        warnings.append(f"Skipped {skipped_large} source files larger than {MAX_FILE_BYTES} bytes or unreadable.")
    if len(screens) > 100:
        warnings.append("More than 100 screen candidates found; starter IR contains the first 100.")

    return {
        "version": 1,
        "repoRoot": str(root.resolve()),
        "policyFile": policy_file,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "detectedPlatforms": platforms,
        "summary": {
            "uiFiles": len(ui_files),
            "screenCandidates": len(screens),
            "routes": len(routes),
            "assets": len(assets),
            "tokenFiles": len(set(token_files)),
            "componentCandidates": len(components),
            "navigationTargets": len(navigation_targets),
            "surfaces": len(surfaces),
            "themes": len(themes),
        },
        "screens": screens,
        "routes": routes,
        "tokenFiles": sorted(set(token_files)),
        "assets": assets[:2000],
        "components": components[:2000],
        "themes": themes,
        "navigationTargets": navigation_targets[:2000],
        "surfaces": surfaces[:2000],
        "uiFiles": ui_files[:2000],
        "warnings": warnings,
    }


def scan(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in iter_files(root):
        record = analyze_file(root, path)
        if record is not None:
            records.append(record)
    return assemble_scan(root, records)


def slug(value: str, fallback: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or fallback


def evidence_for_screen(screen: dict[str, Any], discovered: list[dict[str, Any]]) -> dict[str, Any]:
    source_file = str(screen.get("source", {}).get("file") or "")
    fragment = str(screen.get("fragment") or "")
    symbol = str(screen.get("source", {}).get("symbol") or screen.get("name") or "")
    return next((
        candidate for candidate in discovered
        if str(candidate.get("file") or candidate.get("source", {}).get("file") or "") == source_file
        and (
            (fragment and str(candidate.get("fragment") or "") == fragment)
            or str(candidate.get("name") or candidate.get("source", {}).get("symbol") or "") == symbol
        )
    ), {})


def build_screen_tree(screens: list[dict[str, Any]], discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compile a deterministic platform → evidence group path → screen tree."""
    tree_groups: dict[str, dict[str, Any]] = {}
    for screen in screens:
        platform_label = str(screen.get("platform") or "unknown")
        source_file = str(screen.get("source", {}).get("file") or "inventory")
        metadata = evidence_for_screen(screen, discovered)
        group_path = [str(value) for value in metadata.get("groupPath", screen.get("groupPath", [])) if value]
        if not group_path:
            group_path = [Path(source_file).stem or "Screens"]
        root = tree_groups.setdefault(platform_label, {"children": {}, "leaves": []})
        current = root
        for label in group_path:
            current = current["children"].setdefault(label, {"children": {}, "leaves": []})
        current["leaves"].append({
            "screenId": str(screen["id"]),
            "label": str(metadata.get("label") or screen.get("label") or screen["name"]),
        })

    def children_for(branch: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
        groups = [
            {
                "id": f"group-{slug(prefix + '-' + label, 'screens')}-{hashlib.sha1((prefix + '/' + label).encode('utf-8')).hexdigest()[:8]}",
                "label": label,
                "children": children_for(child, f"{prefix}-{label}"),
            }
            for label, child in branch["children"].items()
        ]
        return [*groups, *branch["leaves"]]

    return [
        {
            "id": f"platform-{slug(platform_label, 'unknown')}",
            "label": platform_label,
            "children": children_for(branch, platform_label),
        }
        for platform_label, branch in tree_groups.items()
    ]


def build_navigation_graph(
    screens: list[dict[str, Any]],
    discovered: list[dict[str, Any]],
    navigation_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile source-evidenced logical transitions separately from rendered actions."""
    evidence_by_fragment = {
        str(item.get("fragment")): item for item in discovered if item.get("fragment")
    }
    screen_by_fragment = {
        str(screen.get("fragment")): str(screen.get("id")) for screen in screens if screen.get("fragment")
    }
    screen_metadata = {str(screen.get("id")): evidence_for_screen(screen, discovered) for screen in screens}

    def flow_for(screen: dict[str, Any]) -> str:
        metadata = screen_metadata.get(str(screen.get("id")), {})
        seen: set[str] = set()
        while metadata.get("parentFragment") and str(metadata["parentFragment"]) not in seen:
            seen.add(str(metadata["parentFragment"]))
            parent = evidence_by_fragment.get(str(metadata["parentFragment"]))
            if not parent:
                break
            metadata = parent
        source_file = str(metadata.get("file") or screen.get("source", {}).get("file") or "screens")
        return slug(Path(source_file).stem, "screens")

    nodes = []
    flow_ids: dict[str, str] = {}
    for screen in screens:
        screen_id = str(screen.get("id"))
        flow_id = flow_for(screen)
        flow_ids[screen_id] = flow_id
        metadata = screen_metadata.get(screen_id, {})
        nodes.append({
            "screenId": screen_id,
            "label": str(metadata.get("label") or screen.get("name") or screen_id),
            "fragment": str(screen.get("fragment") or ""),
            "flowId": flow_id,
            "entry": not bool(metadata.get("parentFragment")),
        })

    edges: list[dict[str, Any]] = []
    for screen in screens:
        screen_id = str(screen.get("id"))
        metadata = screen_metadata.get(screen_id, {})
        parent_id = screen_by_fragment.get(str(metadata.get("parentFragment") or ""))
        if not parent_id:
            continue
        evidence = {
            "file": metadata.get("file", ""),
            "line": metadata.get("line", 1),
            "sourceKind": metadata.get("sourceKind", ""),
        }
        edges.extend([
            {"from": parent_id, "to": screen_id, "kind": "open-logical-view", "evidence": evidence},
            {"from": screen_id, "to": parent_id, "kind": "return-to-parent", "evidence": evidence},
        ])

    target_screen_ids = {
        str(item.get("target")): screen_by_fragment.get(str(item.get("target")))
        for item in navigation_targets if item.get("target")
    }
    unresolved = sorted(target for target, screen_id in target_screen_ids.items() if not screen_id)
    flows = []
    for flow_id in dict.fromkeys(flow_ids.values()):
        flow_nodes = [node for node in nodes if node["flowId"] == flow_id]
        flows.append({
            "id": flow_id,
            "screenIds": [node["screenId"] for node in flow_nodes],
            "entryScreenIds": [node["screenId"] for node in flow_nodes if node["entry"]],
        })
    return {
        "version": 1,
        "source": "scan-evidence",
        "nodes": nodes,
        "edges": edges,
        "flows": flows,
        "navigationTargets": [
            {"target": target, "screenId": screen_id}
            for target, screen_id in target_screen_ids.items() if screen_id
        ],
        "unresolvedTargets": unresolved,
    }


def starter_ir(scan_result: dict[str, Any]) -> dict[str, Any]:
    repo_root = Path(scan_result["repoRoot"])
    adapter_contexts: list[SourceContext] = []
    for item in scan_result.get("uiFiles", []):
        source = str(item.get("path") or "")
        path = repo_root / source
        if not source or not path.is_file():
            continue
        text = read_text(path)
        if text is None:
            continue
        adapter_contexts.append(SourceContext(
            root=repo_root,
            path=path,
            source=source,
            text=text,
            platforms=tuple(str(value) for value in item.get("platforms", [])),
            role=str(item.get("role") or "ui-source"),
        ))
    translated = translate_sources(adapter_contexts)
    raw_scan_screens = scan_result.get("screens", [])[:100]
    scan_screens = raw_scan_screens
    if not scan_screens:
        fallback_ui_file = next((str(item.get("path") or "") for item in scan_result.get("uiFiles", []) if item.get("path")), "")
        scan_screens = [{
            "name": Path(fallback_ui_file).stem or "UI inventory",
            "file": fallback_ui_file,
            "line": 1,
            "platform": scan_result.get("detectedPlatforms", ["unknown"])[0] if scan_result.get("detectedPlatforms") else "unknown",
            "confidence": "unsupported",
        }]
    screens: list[dict[str, Any]] = []
    nodes: dict[str, Any] = {}
    used_ids: set[str] = set()

    def target_family(platform: str) -> str | None:
        if platform.startswith("android-tv"):
            return "android-tv"
        if platform.startswith("android"):
            return "android"
        if platform.startswith("windows") or platform == "react-native-windows":
            return "windows"
        if platform in {"swiftui-macos", "appkit", "mac-catalyst", "react-native-macos"}:
            return "macos"
        if platform in {"swiftui", "uikit"}:
            return "ios"
        if platform in {"web", "react-web"}:
            return "web"
        return None

    for index, candidate in enumerate(scan_screens, start=1):
        base = slug(candidate.get("name", "screen"), f"screen-{index}")
        screen_id = base
        suffix = 2
        while screen_id in used_ids:
            screen_id = f"{base}-{suffix}"
            suffix += 1
        used_ids.add(screen_id)
        root_id = f"{screen_id}-root"
        title_id = f"{screen_id}-title"
        source_id = f"{screen_id}-source"
        inventory_id = f"{screen_id}-inventory"
        source = {
            "file": candidate.get("file", ""),
            "line": candidate.get("line", 1),
            "symbol": candidate.get("name", ""),
        }
        screens.append({
            "id": screen_id,
            "name": candidate.get("name", screen_id),
            "route": "",
            "source": source,
            "confidence": candidate.get("confidence", "approximate"),
            "root": root_id,
            "platform": target_family(candidate.get("platform", "")) or candidate.get("platform", "unknown"),
            "fragment": candidate.get("fragment", ""),
            "logicalView": candidate.get("logicalView", False),
            "label": candidate.get("label", candidate.get("name", screen_id)),
            "groupPath": candidate.get("groupPath", []),
            "parentFragment": candidate.get("parentFragment", ""),
        })
        root_provenance = {}
        title_provenance = {}
        source_provenance = {}
        if source["file"]:
            root_provenance = {
                "component": property_evidence(source["file"], source["line"], source["symbol"], "inventory", "approximate"),
                "layout.direction": property_evidence(source["file"], source["line"], "source screen container", "inventory", "approximate"),
                "layout.width": property_evidence(source["file"], source["line"], "source screen bounds", "inventory", "approximate"),
                "layout.height": property_evidence(source["file"], source["line"], "source screen bounds", "inventory", "approximate"),
            }
            title_provenance = {"text": property_evidence(source["file"], source["line"], source["symbol"], "inventory", candidate.get("confidence", "approximate"))}
            source_provenance = {"text": property_evidence(source["file"], source["line"], "source location", "inventory", "exact")}
        nodes[root_id] = {
            "type": "container",
            "component": "DiscoveredScreen",
            "layout": {"direction": "column", "width": "fill", "height": "fill"},
            "style": {},
            "children": [title_id, source_id, inventory_id],
            "source": source,
            "confidence": "approximate",
            "provenance": root_provenance,
        }
        nodes[title_id] = {"type": "text", "text": candidate.get("name", "Screen"), "style": {}, "source": source, "confidence": candidate.get("confidence", "approximate"), "provenance": title_provenance}
        nodes[source_id] = {"type": "text", "text": f"{candidate.get('file', '')}:{candidate.get('line', 1)}", "style": {}, "source": source, "confidence": "exact", "provenance": source_provenance}
        nodes[inventory_id] = {"type": "custom", "text": "The AI agent should inspect this source file and replace this inventory placeholder with translated UI nodes.", "component": "UntranslatedSource", "source": source, "confidence": "unsupported"}

    if translated.screens:
        inventory_screens = screens
        inventory_nodes = nodes
        logical_files = {
            str(candidate.get("file") or "")
            for candidate in raw_scan_screens
            if candidate.get("logicalView")
        }
        screens = [
            item for item in translated.screens
            if str(item.get("source", {}).get("file") or "") not in logical_files
        ]
        nodes = {}
        for screen in screens:
            stack = [str(screen.get("root") or "")]
            while stack:
                node_id = stack.pop()
                if not node_id or node_id in nodes or node_id not in translated.nodes:
                    continue
                node = translated.nodes[node_id]
                nodes[node_id] = node
                stack.extend(str(child) for child in node.get("children", []))
        represented = {
            (str(item.get("source", {}).get("file") or ""), str(item.get("fragment") or ""))
            for item in screens
        }
        for inventory in inventory_screens:
            key = (str(inventory.get("source", {}).get("file") or ""), str(inventory.get("fragment") or ""))
            if key in represented:
                continue
            screens.append(inventory)
            stack = [str(inventory.get("root") or "")]
            while stack:
                node_id = stack.pop()
                if not node_id or node_id in nodes or node_id not in inventory_nodes:
                    continue
                node = inventory_nodes[node_id]
                nodes[node_id] = node
                stack.extend(str(child) for child in node.get("children", []))

    detected_platforms = scan_result.get("detectedPlatforms", [])
    tv = any(platform.startswith("android-tv") for platform in detected_platforms)
    handheld_native = any(platform in {"android-compose", "android-views", "swiftui", "uikit", "flutter", "react-native"} for platform in detected_platforms)
    target_platforms = list(dict.fromkeys(
        family for platform in scan_result.get("detectedPlatforms", [])
        if (family := target_family(platform))
    ))
    default_profiles = {
        "android": "material3",
        "android-tv": "android-tv",
        "ios": "apple-hig",
        "macos": "macos-hig",
        "windows": "windows-fluent",
        "web": "web-platform",
    }
    standard_profiles = {
        family: {"id": default_profiles[family], "source": "official-default"}
        for family in target_platforms
        if family in default_profiles
    }
    screen_tree = build_screen_tree(screens, raw_scan_screens)
    navigation_graph = build_navigation_graph(screens, raw_scan_screens, scan_result.get("navigationTargets", []))
    translated_themes = {str(item.get("id")): item for item in translated.themes if isinstance(item, dict) and item.get("id")}
    theme_items: list[dict[str, Any]] = []
    for theme in scan_result.get("themes", [{"id": "light", "label": "Light", "kind": "light", "sourceRefs": []}]):
        merged_theme = {**theme, "tokenOverrides": {}, "nodeOverrides": {}}
        translated_theme = translated_themes.pop(str(theme.get("id")), None)
        if translated_theme:
            merged_theme.update(translated_theme)
        theme_items.append(merged_theme)
    theme_items.extend(translated_themes.values())
    translated_screen_keys = {
        (str(item.get("source", {}).get("file") or ""), str(item.get("source", {}).get("symbol") or item.get("name") or ""))
        for item in translated.screens
    }
    catalog_components = [
        item for item in scan_result.get("components", [])
        if (str(item.get("source", {}).get("file") or ""), str(item.get("source", {}).get("symbol") or item.get("name") or "")) not in translated_screen_keys
    ]
    ir = {
        "version": 1,
        "project": {"name": Path(scan_result["repoRoot"]).name, "root": scan_result["repoRoot"]},
        "platforms": scan_result.get("detectedPlatforms", []),
        "design": {
            "mode": "reconstruct",
            "targetPlatforms": target_platforms,
            "standardProfiles": standard_profiles,
        },
        "screenTree": screen_tree,
        "navigationGraph": navigation_graph,
        "policyFile": scan_result.get("policyFile", ""),
        "discoveredScreens": [
            {
                "name": candidate.get("name", ""),
                "file": candidate.get("file", candidate.get("source", {}).get("file", "")),
                "line": candidate.get("line", candidate.get("source", {}).get("line", 1)),
                "platform": candidate.get("platform", "unknown"),
                "logicalView": candidate.get("logicalView", False),
                "fragment": candidate.get("fragment", ""),
                "selector": candidate.get("selector", ""),
                "label": candidate.get("label", candidate.get("name", "")),
                "groupPath": candidate.get("groupPath", []),
                "parentFragment": candidate.get("parentFragment", ""),
                "sourceKind": candidate.get("sourceKind", ""),
            }
            for candidate in (raw_scan_screens if raw_scan_screens else translated.screens)
        ],
        "discoveredRoutes": scan_result.get("routes", []),
        "discoveredNavigationTargets": scan_result.get("navigationTargets", []),
        "discoveredSurfaces": scan_result.get("surfaces", []),
        "viewport": {
            "width": 960 if tv else 390 if handheld_native else 1280,
            "height": 540 if tv else 844 if handheld_native else 800,
            "device": "tv" if tv else "phone" if handheld_native else "desktop",
        },
        "fidelity": {
            "schemaVersion": FIDELITY_SCHEMA_VERSION,
            "status": "translated" if translated.screens else "inventory",
            "sourceDerived": bool(translated.screens),
            "adapters": [adapter.id for adapter in registered_adapters()],
            "unsupported": translated.unsupported,
        },
        "tokens": translated.tokens,
        "themes": {
            "defaultThemeId": "light",
            "items": theme_items,
        },
        "componentCatalog": {
            "status": "inventory" if catalog_components else "ready",
            "enforce": bool(catalog_components),
            "components": catalog_components,
        },
        "review": {
            "sessionId": "initial-review",
            "baselineVersion": "baseline",
            "activeVersion": "baseline",
            "diagnostics": {
                "profiles": [
                    {"id": "current", "label": "Current window", "viewport": "current", "zoomLevels": [0.2, 1, 2]},
                    {"id": "desktop", "label": "Desktop", "viewport": {"width": 1440, "height": 900}, "zoomLevels": [0.5, 1, 2]},
                    {"id": "compact", "label": "Compact", "viewport": {"width": 768, "height": 900}, "zoomLevels": [0.5, 1, 1.5]},
                ],
                "scenarios": [
                    {"id": "zoom-reset", "label": "Zoom reset", "kind": "zoom-reset"},
                    {"id": "overview-geometry", "label": "Overview geometry", "kind": "overview-geometry"},
                    {"id": "menu-exclusivity", "label": "Menu exclusivity", "kind": "menu-exclusivity"},
                    {"id": "layout-integrity", "label": "Layout integrity", "kind": "layout-integrity"},
                    {"id": "accessibility-basics", "label": "Accessibility basics", "kind": "accessibility-basics"},
                ],
            },
            "versions": [
                {"id": "baseline", "label": "Before", "kind": "baseline", "status": "approved", "nodeOverrides": {}}
            ],
            "annotations": [],
        },
        "screens": screens,
        "nodes": nodes,
        "warnings": ["Starter IR is an inventory skeleton and must be enriched from prioritized source files before fidelity review."] + scan_result.get("warnings", []),
    }
    if translated.screens:
        ir["warnings"] = ([f"Adapters left {len(translated.unsupported)} source expressions explicitly unsupported."] if translated.unsupported else []) + scan_result.get("warnings", [])
    seal_baseline(ir)
    return ir


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find UI source in a repository without running it.")
    parser.add_argument("repo", type=Path, help="Repository or project root to scan")
    parser.add_argument("--output", type=Path, required=True, help="Path for ui-scan.json")
    parser.add_argument("--starter-ir", type=Path, help="Optional path for a conservative starter ui-ir.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo.resolve()
    if not root.is_dir():
        print(f"Repository directory does not exist: {root}", file=sys.stderr)
        return 2
    result = scan(root)
    write_json(args.output.resolve(), result)
    if args.starter_ir:
        write_json(args.starter_ir.resolve(), starter_ir(result))
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
