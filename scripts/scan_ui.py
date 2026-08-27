#!/usr/bin/env python3
"""Read-only multi-platform UI inventory scanner.

The scanner intentionally produces a conservative inventory. It does not run,
build, import, or modify the target repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_DIRS = {
    ".git", ".gradle", ".idea", ".next", ".nuxt", ".dart_tool",
    "build", "dist", "out", "target", "node_modules", "Pods", "DerivedData",
    "vendor", "coverage", ".codegraph", ".worktrees", ".claude", ".lavish", ".codex",
    ".agents", ".cursor", ".gemini", ".opencode", ".ui-design-workbench",
}
SCANNER_VERSION = 3
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


def html_attr(attrs: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']+)[\"']", attrs, re.I)
    return match.group(1).strip() if match else ""


def visible_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


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
            routes.append({"route": match.group(1), "file": source, "line": line_number(text, match.start())})
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
        for match in HTML_SECTION_PATTERN.finditer(text):
            attrs = match.group("attrs")
            section_id = html_attr(attrs, "id")
            data_section = html_attr(attrs, "data-section")
            classes = set(html_attr(attrs, "class").split())
            if not section_id or not (data_section or {"panel", "view", "screen"} & classes):
                continue
            label = data_section or section_id
            candidates.append({
                "name": "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", label) if part) + "View",
                "file": source,
                "line": line_number(text, match.start()),
                "platform": "web",
                "confidence": "high",
                "logicalView": True,
                "fragment": f"#{section_id}",
                "selector": f"section#{section_id}",
            })
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
        "components": component_candidates(source, platforms, symbols, role),
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
        screens.extend(record.get("screens", []))
        components.extend(record.get("components", []))
        if record.get("tokenFile"):
            token_files.append(str(record["tokenFile"]))

    role_order = {"navigation": 0, "theme": 1, "screen": 2, "component": 3, "ui-source": 4}
    ui_files.sort(key=lambda item: (role_order.get(item["role"], 9), item["path"]))
    screens = unique_dicts(screens, ("name", "file", "line"))
    routes = unique_dicts(routes, ("route", "file", "line"))
    components = unique_dicts(components, ("id",))
    navigation_targets = unique_dicts(navigation_targets, ("target", "file", "line"))
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
        },
        "screens": screens,
        "routes": routes,
        "tokenFiles": sorted(set(token_files)),
        "assets": assets[:2000],
        "components": components[:2000],
        "navigationTargets": navigation_targets[:2000],
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


def starter_ir(scan_result: dict[str, Any]) -> dict[str, Any]:
    scan_screens = scan_result.get("screens", [])[:100]
    if not scan_screens:
        scan_screens = [{
            "name": "UI inventory",
            "file": "",
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
        })
        nodes[root_id] = {
            "type": "container",
            "component": "DiscoveredScreen",
            "layout": {"direction": "column", "width": "fill", "height": "fill"},
            "style": {},
            "children": [title_id, source_id, inventory_id],
            "source": source,
            "confidence": "approximate",
        }
        nodes[title_id] = {"type": "text", "text": candidate.get("name", "Screen"), "style": {}, "source": source, "confidence": candidate.get("confidence", "approximate")}
        nodes[source_id] = {"type": "text", "text": f"{candidate.get('file', '')}:{candidate.get('line', 1)}", "style": {}, "source": source, "confidence": "exact"}
        nodes[inventory_id] = {"type": "custom", "text": "The AI agent should inspect this source file and replace this inventory placeholder with translated UI nodes.", "component": "UntranslatedSource", "source": source, "confidence": "unsupported"}

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
    tree_groups: dict[str, dict[str, list[dict[str, str]]]] = {}
    for screen in screens:
        platform_label = str(screen.get("platform") or "unknown")
        source_file = str(screen.get("source", {}).get("file") or "inventory")
        source_label = Path(source_file).stem or "Screens"
        tree_groups.setdefault(platform_label, {}).setdefault(source_label, []).append({
            "screenId": str(screen["id"]),
            "label": str(screen["name"]),
        })
    screen_tree = [
        {
            "id": f"platform-{slug(platform_label, 'unknown')}",
            "label": platform_label,
            "children": [
                {
                    "id": f"source-{slug(platform_label + '-' + source_label, 'screens')}",
                    "label": source_label,
                    "children": children,
                }
                for source_label, children in source_groups.items()
            ],
        }
        for platform_label, source_groups in tree_groups.items()
    ]
    return {
        "version": 1,
        "project": {"name": Path(scan_result["repoRoot"]).name, "root": scan_result["repoRoot"]},
        "platforms": scan_result.get("detectedPlatforms", []),
        "design": {
            "mode": "reconstruct",
            "targetPlatforms": target_platforms,
            "standardProfiles": standard_profiles,
        },
        "screenTree": screen_tree,
        "policyFile": scan_result.get("policyFile", ""),
        "discoveredScreens": [
            {
                "name": candidate.get("name", ""),
                "file": candidate.get("file", ""),
                "line": candidate.get("line", 1),
                "platform": candidate.get("platform", "unknown"),
                "logicalView": candidate.get("logicalView", False),
                "fragment": candidate.get("fragment", ""),
                "selector": candidate.get("selector", ""),
            }
            for candidate in scan_screens
        ],
        "discoveredRoutes": scan_result.get("routes", []),
        "discoveredNavigationTargets": scan_result.get("navigationTargets", []),
        "viewport": {
            "width": 960 if tv else 390 if handheld_native else 1280,
            "height": 540 if tv else 844 if handheld_native else 800,
            "device": "tv" if tv else "phone" if handheld_native else "desktop",
        },
        "fidelity": {"status": "inventory", "sourceDerived": False},
        "tokens": {"colors": {}, "spacing": {}, "radii": {}, "typography": {}},
        "componentCatalog": {
            "status": "inventory",
            "enforce": bool(scan_result.get("components")),
            "components": scan_result.get("components", []),
        },
        "review": {
            "sessionId": "initial-review",
            "baselineVersion": "baseline",
            "activeVersion": "baseline",
            "versions": [
                {"id": "baseline", "label": "Before", "kind": "baseline", "status": "approved", "nodeOverrides": {}}
            ],
            "annotations": [],
        },
        "screens": screens,
        "nodes": nodes,
        "warnings": ["Starter IR is an inventory skeleton and must be enriched from prioritized source files before fidelity review."] + scan_result.get("warnings", []),
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
