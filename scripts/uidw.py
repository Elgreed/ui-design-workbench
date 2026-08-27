#!/usr/bin/env python3
"""Provider-neutral UI Design Workbench command line interface.

The cache is lazy and deterministic: source contents are read only on the
initial scan or after a candidate UI file fingerprint changes. No watcher,
server, application runtime, emulator, or development server is started.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from quality_common import node_screen_map
from scan_ui import (
    ASSET_EXTENSIONS,
    SCANNER_VERSION,
    SOURCE_EXTENSIONS,
    analyze_file,
    assemble_scan,
    iter_files,
    starter_ir,
    write_json,
)


CACHE_VERSION = 2
CLI_VERSION = "0.1.0"
STATE_DIR_NAME = ".ui-design-workbench"
CONFIG_NAME = "config.json"
UI_MODE_KEY = "uiMode"
MOCK_DATA_KEY = "mockData"
CACHE_NAME = "cache-state.json"
SCAN_NAME = "ui-scan.json"
IR_NAME = "ui-ir.json"
GRAPH_NAME = "ui-graph.json"
CONTEXT_NAME = "ui-context.json"
SYNC_REPORT_NAME = "sync-report.json"
STATE_GITIGNORE = "*\n!.gitignore\n!config.json\n"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_paths(root: Path) -> dict[str, Path]:
    project_config_path = root / STATE_DIR_NAME / CONFIG_NAME
    project_config = read_json(project_config_path, {})
    if not isinstance(project_config, dict):
        project_config = {}
    if project_config.get("cacheMode") == "project":
        directory = root / STATE_DIR_NAME
        config_path = project_config_path
    else:
        override = os.environ.get("UIDW_CACHE_HOME")
        if override:
            cache_root = Path(override).expanduser()
        elif os.name == "nt":
            cache_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "UI Design Workbench" / "Cache"
        elif sys.platform == "darwin":
            cache_root = Path.home() / "Library" / "Caches" / "ui-design-workbench"
        else:
            cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ui-design-workbench"
        normalized = str(root.resolve()).replace("\\", "/")
        if os.name == "nt":
            normalized = normalized.lower()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        label = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "project"
        directory = cache_root / "projects" / f"{label}-{digest}"
        config_path = project_config_path if project_config_path.is_file() else directory / CONFIG_NAME
    return {
        "dir": directory,
        "config": config_path,
        "cache": directory / CACHE_NAME,
        "scan": directory / SCAN_NAME,
        "ir": directory / IR_NAME,
        "graph": directory / GRAPH_NAME,
        "context": directory / CONTEXT_NAME,
        "sync": directory / SYNC_REPORT_NAME,
        "gitignore": directory / ".gitignore",
    }


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "autoSync": True,
        "cacheMode": "user",
        "compactContext": True,
        "maxContextScreens": 100,
        "maxContextComponents": 200,
        "handoffProvider": "generic",
        UI_MODE_KEY: {"enabled": False},
        MOCK_DATA_KEY: {"mode": "none", "seed": "stable"},
    }


def config_hash(config: dict[str, Any]) -> str:
    scan_config = {key: value for key, value in config.items() if key not in {UI_MODE_KEY, MOCK_DATA_KEY}}
    payload = json.dumps(scan_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_config(value: Any) -> dict[str, Any]:
    config = default_config()
    if isinstance(value, dict):
        config.update(value)
    mode = config.get(UI_MODE_KEY)
    config[UI_MODE_KEY] = {"enabled": bool(mode.get("enabled", False))} if isinstance(mode, dict) else {"enabled": False}
    mock_data = config.get(MOCK_DATA_KEY)
    mock_mode = mock_data.get("mode", "none") if isinstance(mock_data, dict) else "none"
    if mock_mode not in {"none", "representative", "exhaustive"}:
        mock_mode = "none"
    config[MOCK_DATA_KEY] = {"mode": mock_mode, "seed": "stable"}
    return config


def mock_data_context(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get(MOCK_DATA_KEY, {}).get("mode", "none"))
    enabled = mode != "none"
    result: dict[str, Any] = {"enabled": enabled, "mode": mode, "default": "off", "seed": "stable"}
    if enabled:
        result["instruction"] = (
            "Create deterministic, non-sensitive, platform-appropriate screen scenarios only when supported by "
            "the screen task or source branches. Use reusable scenarioFixtures plus sparse screen.scenarios; do "
            "not stamp the same loading/error/success set onto every screen. Representative mode keeps one "
            "populated fixture and only critical alternate states; exhaustive mode also covers evidenced boundary states."
        )
    return result


def ui_mode_context(config: dict[str, Any], detected_platforms: list[str] | None = None) -> dict[str, Any]:
    enabled = bool(config.get(UI_MODE_KEY, {}).get("enabled", False))
    result: dict[str, Any] = {"enabled": enabled, "default": "off"}
    if enabled:
        result.update({
            "scope": "ui-related tasks only",
            "detectedPlatforms": detected_platforms or [],
            "instruction": (
                "For UI-related implementation tasks, preserve the project design system and apply the matching "
                "platform conventions, accessibility, states, input methods, and adaptive behavior. Read only the "
                "relevant platform guidance. Do not start a full review, redesign, or HTML workbench unless requested."
            ),
        })
    return result


def candidate_files(root: Path) -> list[Path]:
    result: list[Path] = []
    supported = SOURCE_EXTENSIONS | ASSET_EXTENSIONS
    for path in iter_files(root):
        if path.suffix.lower() in supported:
            result.append(path)
    return sorted(result, key=lambda item: item.relative_to(root).as_posix())


def build_manifest(
    root: Path,
    previous: dict[str, Any] | None = None,
    verify_content: bool = False,
) -> dict[str, dict[str, Any]]:
    previous = previous or {}
    manifest: dict[str, dict[str, Any]] = {}
    for path in candidate_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except OSError:
            continue
        old = previous.get(relative, {}) if isinstance(previous.get(relative), dict) else {}
        metadata_same = old.get("size") == stat.st_size and old.get("mtimeNs") == stat.st_mtime_ns
        try:
            digest = old.get("sha256") if metadata_same and not verify_content else sha256_file(path)
        except OSError:
            continue
        manifest[relative] = {
            "size": stat.st_size,
            "mtimeNs": stat.st_mtime_ns,
            "sha256": digest,
            "kind": "asset" if path.suffix.lower() in ASSET_EXTENSIONS else "source",
        }
    return manifest


def manifest_diff(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    old_paths = set(previous)
    new_paths = set(current)
    added = sorted(new_paths - old_paths)
    removed = sorted(old_paths - new_paths)
    modified: list[str] = []
    metadata_only: list[str] = []
    for path in sorted(old_paths & new_paths):
        old = previous[path]
        new = current[path]
        if old.get("sha256") != new.get("sha256"):
            modified.append(path)
        elif old.get("size") != new.get("size") or old.get("mtimeNs") != new.get("mtimeNs"):
            metadata_only.append(path)
    return {"added": added, "modified": modified, "removed": removed, "metadataOnly": metadata_only}


def changed_paths(diff: dict[str, list[str]]) -> list[str]:
    return sorted(set(diff["added"] + diff["modified"] + diff["removed"]))


def load_project_ir(paths: dict[str, Path]) -> dict[str, Any] | None:
    value = read_json(paths["ir"])
    return value if isinstance(value, dict) else None


def graph_id(kind: str, *parts: str) -> str:
    key = "\x1f".join([kind, *parts])
    return f"{kind}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def build_ui_graph(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    """Build a stable, provider-neutral source UI graph from the scan inventory."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(kind: str, key: str, **data: Any) -> str:
        node_id = graph_id(kind, key)
        nodes[node_id] = {"id": node_id, "kind": kind, **data}
        return node_id

    def add_edge(source: str, target: str, kind: str, **data: Any) -> None:
        edges[(source, target, kind)] = {"source": source, "target": target, "kind": kind, **data}

    files: dict[str, str] = {}

    def file_node(path: str) -> str:
        if path not in files:
            files[path] = add_node("source", path, path=path)
        return files[path]

    screen_nodes: dict[str, str] = {}
    for screen in inventory.get("screens", []):
        path = str(screen.get("file") or "")
        key = f"{path}\x1f{screen.get('name')}\x1f{screen.get('kind')}"
        node_id = add_node("screen", key, name=screen.get("name"), screenKind=screen.get("kind"), file=path, evidence=screen.get("evidence", []))
        screen_nodes[key] = node_id
        if path:
            add_edge(file_node(path), node_id, "declares")

    route_nodes: dict[str, str] = {}
    for route in inventory.get("routes", []):
        path = str(route.get("file") or "")
        value = str(route.get("route") or "")
        key = f"{path}\x1f{value}"
        node_id = add_node("route", key, value=value, file=path, line=route.get("line"))
        route_nodes[value] = node_id
        if path:
            add_edge(file_node(path), node_id, "declares")

    for component in inventory.get("components", []):
        path = str(component.get("file") or "")
        symbol = str(component.get("symbol") or "")
        key = f"{path}\x1f{symbol}"
        node_id = add_node("component", key, symbol=symbol, file=path, platform=component.get("platform"), line=component.get("line"))
        if path:
            source_id = file_node(path)
            add_edge(source_id, node_id, "declares")
            for screen in inventory.get("screens", []):
                if screen.get("file") == path:
                    screen_key = f"{path}\x1f{screen.get('name')}\x1f{screen.get('kind')}"
                    if screen_key in screen_nodes:
                        add_edge(screen_nodes[screen_key], node_id, "uses-local-component")

    for token in inventory.get("tokenFiles", []):
        path = str(token.get("path") or "")
        node_id = add_node("token-file", path, path=path)
        if path:
            add_edge(file_node(path), node_id, "defines")

    for navigation in inventory.get("navigationTargets", []):
        path = str(navigation.get("file") or "")
        target = str(navigation.get("target") or "")
        key = f"{path}\x1f{target}\x1f{navigation.get('line')}"
        node_id = add_node("navigation-target", key, value=target, file=path, line=navigation.get("line"), navigationKind=navigation.get("kind"))
        if path:
            add_edge(file_node(path), node_id, "declares")
        route_id = route_nodes.get(target) or route_nodes.get(target.lstrip("#/"))
        if route_id:
            add_edge(node_id, route_id, "navigates-to", resolved=True)

    starter = starter_ir(inventory)
    return {
        "version": 1,
        "graphType": "ui-source-map",
        "repoRoot": str(root),
        "project": inventory.get("project", {}),
        "detectedPlatforms": inventory.get("detectedPlatforms", []),
        "summary": {"nodes": len(nodes), "edges": len(edges), "screens": len(inventory.get("screens", [])), "routes": len(inventory.get("routes", []))},
        "screenTree": starter.get("screenTree", []),
        "nodes": sorted(nodes.values(), key=lambda item: (str(item.get("kind")), str(item.get("id")))),
        "edges": sorted(edges.values(), key=lambda item: (str(item.get("source")), str(item.get("kind")), str(item.get("target")))),
    }


def impacted_screens(
    ir: dict[str, Any] | None,
    old_scan: dict[str, Any],
    new_scan: dict[str, Any],
    changed: list[str],
    invalidate_all: bool,
) -> list[str]:
    if not ir:
        return sorted({str(item.get("name")) for item in new_scan.get("screens", []) if item.get("file") in changed})
    all_screens = {str(item.get("id")) for item in ir.get("screens", []) if item.get("id")}
    if invalidate_all:
        return sorted(all_screens)
    changed_set = set(changed)
    roles: set[str] = set()
    for inventory in (old_scan, new_scan):
        for item in inventory.get("uiFiles", []):
            if item.get("path") in changed_set:
                roles.add(str(item.get("role")))
    if roles & {"theme", "navigation"}:
        return sorted(all_screens)
    impacted: set[str] = set()
    for screen in ir.get("screens", []):
        if screen.get("source", {}).get("file") in changed_set:
            impacted.add(str(screen.get("id")))
    node_screens = node_screen_map(ir)
    for node_id, node in ir.get("nodes", {}).items():
        source_file = node.get("source", {}).get("file")
        component_ref = str(node.get("componentRef") or "")
        serialized = json.dumps(node, ensure_ascii=False)
        if source_file in changed_set or any(path in component_ref or path in serialized for path in changed_set):
            impacted.update(node_screens.get(str(node_id), set()))
    if "component" in roles and not impacted:
        return sorted(all_screens)
    return sorted(impacted)


def compact_context(
    root: Path,
    inventory: dict[str, Any],
    report: dict[str, Any],
    ir: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    max_screens = max(1, int(config.get("maxContextScreens", 100)))
    max_components = max(1, int(config.get("maxContextComponents", 200)))
    impacted = set(report.get("impactedScreenIds", []))
    screens = inventory.get("screens", [])
    if impacted and ir:
        source_by_id = {
            str(screen.get("id")): str(screen.get("source", {}).get("file") or "")
            for screen in ir.get("screens", [])
        }
        impacted_files = {source_by_id[item] for item in impacted if source_by_id.get(item)}
        screens = [item for item in screens if item.get("file") in impacted_files] or screens
    priority_files = list(report.get("changedUiFiles", []))
    for item in screens:
        file = str(item.get("file") or "")
        if file and file not in priority_files:
            priority_files.append(file)
    return {
        "version": 1,
        "repoRoot": str(root),
        "cacheStatus": report.get("status"),
        "syncedAt": report.get("syncedAt"),
        "detectedPlatforms": inventory.get("detectedPlatforms", []),
        "summary": inventory.get("summary", {}),
        "changedUiFiles": report.get("changedUiFiles", []),
        "impactedScreenIds": report.get("impactedScreenIds", []),
        "prioritySourceFiles": priority_files[:300],
        "screens": screens[:max_screens],
        "routes": inventory.get("routes", [])[:200],
        "navigationTargets": inventory.get("navigationTargets", [])[:200],
        "tokenFiles": inventory.get("tokenFiles", [])[:100],
        "components": inventory.get("components", [])[:max_components],
        "warnings": inventory.get("warnings", []),
        UI_MODE_KEY: ui_mode_context(config, inventory.get("detectedPlatforms", [])),
        MOCK_DATA_KEY: mock_data_context(config),
        "instructions": "Read prioritySourceFiles only when cacheStatus is stale or the requested screen is not fully represented in ui-ir.json.",
    }


def inspect_cache(root: Path, verify_content: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], dict[str, Any]]:
    paths = state_paths(root)
    config = normalized_config(read_json(paths["config"], {}))
    cache = read_json(paths["cache"], {})
    if not isinstance(cache, dict):
        cache = {}
    previous_manifest = cache.get("manifest", {}) if isinstance(cache.get("manifest"), dict) else {}
    current_manifest = build_manifest(root, previous_manifest, verify_content)
    diff = manifest_diff(previous_manifest, current_manifest)
    reasons: list[str] = []
    if not paths["cache"].is_file() or not paths["scan"].is_file() or not paths["graph"].is_file():
        reasons.append("cache-missing")
    if cache.get("cacheVersion") != CACHE_VERSION:
        reasons.append("cache-version-changed")
    if cache.get("scannerVersion") != SCANNER_VERSION:
        reasons.append("scanner-version-changed")
    if cache.get("configHash") != config_hash(config):
        reasons.append("config-changed")
    if changed_paths(diff):
        reasons.append("ui-files-changed")
    status = "stale" if reasons else "clean"
    result = {
        "version": 1,
        "status": status,
        "repoRoot": str(root),
        "reasons": reasons,
        "changes": diff,
        "changedUiFiles": changed_paths(diff),
        "cacheFile": str(paths["cache"]),
        "configFile": str(paths["config"]),
        "scanFile": str(paths["scan"]),
        "irFile": str(paths["ir"]),
        "graphFile": str(paths["graph"]),
        UI_MODE_KEY: ui_mode_context(config),
        MOCK_DATA_KEY: mock_data_context(config),
    }
    return result, current_manifest, paths, config


def sync_project(root: Path, force: bool = False, verify_content: bool = False) -> dict[str, Any]:
    status, current_manifest, paths, config = inspect_cache(root, verify_content)
    cache = read_json(paths["cache"], {}) or {}
    old_scan = read_json(paths["scan"], {}) or {}
    invalidate_all = force or any(reason in status["reasons"] for reason in ("cache-missing", "cache-version-changed", "scanner-version-changed", "config-changed"))
    if status["status"] == "clean" and not force:
        inventory = old_scan
        if status["changes"]["metadataOnly"] and cache:
            cache["manifest"] = current_manifest
            write_json(paths["cache"], cache)
        report = {**status, "syncedAt": cache.get("syncedAt"), "impactedScreenIds": []}
    else:
        previous_records = cache.get("fileRecords", {}) if isinstance(cache.get("fileRecords"), dict) else {}
        if invalidate_all or not previous_records:
            file_records: dict[str, Any] = {}
            for relative in current_manifest:
                record = analyze_file(root, root / Path(relative))
                if record is not None:
                    file_records[relative] = record
        else:
            file_records = dict(previous_records)
            for relative in status["changes"]["removed"]:
                file_records.pop(relative, None)
            for relative in status["changes"]["added"] + status["changes"]["modified"]:
                record = analyze_file(root, root / Path(relative))
                if record is None:
                    file_records.pop(relative, None)
                else:
                    file_records[relative] = record
        inventory = assemble_scan(root, file_records.values())
        old_ir = load_project_ir(paths)
        new_ir = starter_ir(inventory)
        impacted = sorted(set(
            impacted_screens(old_ir, old_scan, inventory, status["changedUiFiles"], invalidate_all)
            + impacted_screens(new_ir, old_scan, inventory, status["changedUiFiles"], invalidate_all)
        ))
        synced_at = utc_now()
        paths["dir"].mkdir(parents=True, exist_ok=True)
        write_json(paths["scan"], inventory)
        write_json(paths["graph"], build_ui_graph(root, inventory))
        write_json(paths["ir"], new_ir)
        write_json(paths["cache"], {
            "cacheVersion": CACHE_VERSION,
            "scannerVersion": SCANNER_VERSION,
            "repoRoot": str(root),
            "configHash": config_hash(config),
            "syncedAt": synced_at,
            "manifest": current_manifest,
            "fileRecords": file_records,
        })
        report = {**status, "status": "synced", "syncedAt": synced_at, "impactedScreenIds": impacted}
    context = compact_context(root, inventory, report, load_project_ir(paths), config)
    context["uiGraphFile"] = str(paths["graph"])
    write_json(paths["context"], context)
    write_json(paths["sync"], report)
    return report


def initialize(root: Path, force: bool = False, project_cache: bool = False, ui_mode: bool = False, mock_data_mode: str = "none") -> dict[str, Any]:
    if project_cache:
        config_path = root / STATE_DIR_NAME / CONFIG_NAME
        config = normalized_config(read_json(config_path, {}))
        config["cacheMode"] = "project"
    else:
        initial_paths = state_paths(root)
        config_path = initial_paths["config"]
        config = normalized_config(read_json(config_path, {}))
    config[UI_MODE_KEY] = {"enabled": bool(ui_mode)}
    config[MOCK_DATA_KEY] = {"mode": mock_data_mode, "seed": "stable"}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(config_path, config)
    paths = state_paths(root)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    if project_cache and not paths["gitignore"].exists():
        paths["gitignore"].write_text(STATE_GITIGNORE, encoding="utf-8")
    result = sync_project(root, force=force)
    return {**result, UI_MODE_KEY: ui_mode_context(config, read_json(paths["scan"], {}).get("detectedPlatforms", [])), MOCK_DATA_KEY: mock_data_context(config)}


def configure_ui_mode(root: Path, enabled: bool | None = None) -> dict[str, Any]:
    paths = state_paths(root)
    config = normalized_config(read_json(paths["config"], {}))
    if enabled is not None:
        config[UI_MODE_KEY] = {"enabled": enabled}
        paths["config"].parent.mkdir(parents=True, exist_ok=True)
        write_json(paths["config"], config)
        sync_project(root)
        paths = state_paths(root)
    inventory = read_json(paths["scan"], {})
    detected = inventory.get("detectedPlatforms", []) if isinstance(inventory, dict) else []
    mode = ui_mode_context(config, detected)
    return {
        "version": 1,
        "status": "enabled" if mode["enabled"] else "disabled",
        "repoRoot": str(root),
        UI_MODE_KEY: mode,
        "configFile": str(paths["config"]),
        "contextFile": str(paths["context"]),
    }


def chrome_path() -> str | None:
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
    ]
    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ])
    return next((str(item) for item in candidates if item and Path(item).exists()), None)


def doctor(root: Path) -> dict[str, Any]:
    status, _, paths, config = inspect_cache(root)
    return {
        "version": 1,
        "repoRoot": str(root),
        "python": {"available": True, "version": sys.version.split()[0], "executable": sys.executable},
        "node": {"available": bool(shutil.which("node")), "path": shutil.which("node")},
        "chromium": {"available": bool(chrome_path()), "path": chrome_path()},
        "cache": status,
        "stateDir": str(paths["dir"]),
        "cliVersion": CLI_VERSION,
        UI_MODE_KEY: ui_mode_context(config),
    }


def write_screen_context(paths: dict[str, Path], screen_query: str) -> Path:
    ir = load_project_ir(paths)
    base = read_json(paths["context"], {})
    if not ir or not isinstance(base, dict):
        raise ValueError("UI context is unavailable; run init or sync first")
    normalized = screen_query.strip().lower()
    screen = next((
        item for item in ir.get("screens", [])
        if str(item.get("id", "")).lower() == normalized or str(item.get("name", "")).lower() == normalized
    ), None)
    if not screen:
        raise ValueError(f"Unknown screen: {screen_query}")
    nodes = ir.get("nodes", {})
    selected_nodes: dict[str, Any] = {}

    def visit(node_id: str) -> None:
        if node_id in selected_nodes or node_id not in nodes:
            return
        node = nodes[node_id]
        selected_nodes[node_id] = node
        for child in node.get("children", []):
            visit(str(child))

    visit(str(screen.get("root", "")))
    source_files = {
        str(item.get("source", {}).get("file"))
        for item in [screen, *selected_nodes.values()]
        if item.get("source", {}).get("file")
    }
    component_refs = sorted({
        str(item.get("componentRef"))
        for item in selected_nodes.values()
        if item.get("componentRef")
    })
    payload = {
        "version": 1,
        "repoRoot": base.get("repoRoot"),
        "cacheStatus": base.get("cacheStatus"),
        "screen": screen,
        "nodes": selected_nodes,
        "sourceFiles": sorted(source_files),
        "componentRefs": component_refs,
        "platforms": ir.get("platforms", []),
        "design": ir.get("design", {}),
        "tokens": ir.get("tokens", {}),
        "warnings": base.get("warnings", []),
        UI_MODE_KEY: base.get(UI_MODE_KEY, {"enabled": False, "default": "off"}),
        MOCK_DATA_KEY: base.get(MOCK_DATA_KEY, {"enabled": False, "mode": "none", "default": "off"}),
        "uiGraphFile": str(paths["graph"]),
    }
    slug = re.sub(r"[^a-z0-9]+", "-", str(screen.get("id", "screen")).lower()).strip("-") or "screen"
    output = paths["dir"] / f"ui-context-{slug}.json"
    write_json(output, payload)
    return output


def print_result(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        return
    changed = len(value.get("changedUiFiles", []))
    impacted = len(value.get("impactedScreenIds", []))
    mode = value.get(UI_MODE_KEY)
    mode_text = f" | ui-mode={'on' if mode.get('enabled') else 'off'}" if isinstance(mode, dict) else ""
    print(f"{value.get('status', 'ok')} | changed={changed} | impacted={impacted}{mode_text}")


def resolve_init_ui_mode(explicit: bool | None, as_json: bool) -> bool:
    if explicit is not None:
        return explicit
    if as_json or not sys.stdin.isatty():
        return False
    print(
        "Optional UI guidance mode applies project and platform conventions during ordinary UI implementation tasks.\n"
        "It helps agents reuse existing components, respect Android/Android TV, Apple, Windows, and Web patterns,\n"
        "and check accessibility and UI states without automatically starting a full review or redesign.\n"
        "The mode is disabled by default and can be changed later with `uidw ui-mode --enable|--disable`.",
        file=sys.stderr,
    )
    try:
        answer = input("Enable UI guidance mode for this project? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def resolve_init_mock_data(explicit: str | None, as_json: bool) -> str:
    if explicit is not None:
        return explicit
    if as_json or not sys.stdin.isatty():
        return "none"
    print(
        "Optional mock data makes data-driven screens useful without running the application.\n"
        "Representative mode creates one realistic populated fixture and only screen-specific critical states;\n"
        "it does not add the same loading/error/success set to every screen. The feature is disabled by default.",
        file=sys.stderr,
    )
    try:
        answer = input("Mock data mode [n]one/[r]epresentative/[e]xhaustive? [n]: ").strip().lower()
    except EOFError:
        return "none"
    return {"r": "representative", "representative": "representative", "e": "exhaustive", "exhaustive": "exhaustive"}.get(answer, "none")


def render_artifact(ir_path: Path, output: Path, allow_draft: bool, agent: str) -> dict[str, Any]:
    from render_preview import fidelity_audit, render_html, resolve_assets, validate

    ir = read_json(ir_path)
    if not isinstance(ir, dict):
        raise ValueError(f"Cannot read UI IR: {ir_path}")
    errors = validate(ir)
    if errors:
        raise ValueError("; ".join(errors))
    audit = fidelity_audit(ir)
    if audit["status"] == "blocked" and not allow_draft:
        raise ValueError("Preview blocked by fidelity audit: " + "; ".join(audit["reasons"]))
    ir["fidelityAudit"] = audit
    if audit["reasons"]:
        ir.setdefault("warnings", []).extend(audit["reasons"])
    destination = output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_html(resolve_assets(ir), destination.parent, agent), encoding="utf-8")
    return {"version": 1, "status": "rendered", "irFile": str(ir_path.resolve()), "previewFile": str(destination), "agent": agent, "fidelity": audit}


def validate_artifact(ir_path: Path, output_dir: Path) -> dict[str, Any]:
    from coverage_report import build_report
    from validate_platform_profiles import validate_profiles

    ir = read_json(ir_path)
    if not isinstance(ir, dict):
        raise ValueError(f"Cannot read UI IR: {ir_path}")
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    platform_report = validate_profiles(ir)
    coverage_report = build_report(ir)
    platform_path = destination / "platform-profile-report.json"
    coverage_path = destination / "ui-coverage.json"
    write_json(platform_path, platform_report)
    write_json(coverage_path, coverage_report)
    status = "pass" if platform_report.get("status") == "pass" and coverage_report.get("status") == "pass" else "fail"
    return {"version": 1, "status": status, "platformReport": str(platform_path), "coverageReport": str(coverage_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"uidw {CLI_VERSION}")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Target repository root")
    parser.add_argument("--json", action="store_true", help="Print compact JSON instead of a one-line summary")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Create project UI state and perform the initial scan")
    init_parser.add_argument("--force", action="store_true", help="Recreate config and scan even when the cache is clean")
    init_parser.add_argument("--project-cache", action="store_true", help="Store ignored derived state inside the repository instead of the OS cache")
    init_mode = init_parser.add_mutually_exclusive_group()
    init_mode.add_argument("--ui-mode", dest="ui_mode", action="store_true", default=None, help="Enable platform guidance for ordinary UI tasks without prompting")
    init_mode.add_argument("--no-ui-mode", dest="ui_mode", action="store_false", default=None, help="Keep platform guidance disabled without prompting")
    init_parser.add_argument("--mock-data", choices=("none", "representative", "exhaustive"), default=None, help="Generate only relevant deterministic mock scenarios; default is none")
    status_parser = subparsers.add_parser("status", help="Check whether the cached UI index is current")
    status_parser.add_argument("--verify-content", action="store_true", help="Hash every candidate file instead of trusting unchanged metadata")
    sync_parser = subparsers.add_parser("sync", help="Refresh the UI index only when relevant files changed")
    sync_parser.add_argument("--force", action="store_true", help="Force a full UI rescan")
    sync_parser.add_argument("--verify-content", action="store_true", help="Hash every candidate file before deciding")
    context_parser = subparsers.add_parser("context", help="Refresh lazily and print the compact model-context path")
    context_parser.add_argument("--no-sync", action="store_true", help="Do not refresh a stale cache")
    context_parser.add_argument("--screen", help="Write a bounded context containing only one translated screen and its source references")
    map_parser = subparsers.add_parser("map", help="Refresh lazily and return or export the stable UI graph")
    map_parser.add_argument("--output", type=Path, help="Copy ui-graph.json to this explicit path")
    render_parser = subparsers.add_parser("render", help="Render a complete UI IR as standalone HTML")
    render_parser.add_argument("ir", type=Path, help="Path to ui-ir.json")
    render_parser.add_argument("--output", type=Path, required=True, help="Output HTML path")
    render_parser.add_argument("--allow-draft", action="store_true", help="Render an incomplete IR for internal diagnostics")
    render_parser.add_argument("--agent", choices=("generic", "codex"), default="generic", help="Optional agent handoff adapter")
    validate_parser = subparsers.add_parser("validate", help="Run deterministic platform and coverage gates")
    validate_parser.add_argument("ir", type=Path, help="Path to ui-ir.json")
    validate_parser.add_argument("--output-dir", type=Path, required=True, help="Directory for validation reports")
    mode_parser = subparsers.add_parser("ui-mode", help="Show or change platform guidance for ordinary UI tasks")
    mode_group = mode_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--enable", action="store_true", help="Enable UI guidance without rescanning unchanged UI source")
    mode_group.add_argument("--disable", action="store_true", help="Disable UI guidance without rescanning unchanged UI source")
    subparsers.add_parser("doctor", help="Check local runtime and cache capabilities")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo.resolve()
    if not root.is_dir():
        print(f"Repository directory does not exist: {root}", file=sys.stderr)
        return 2
    if args.command == "init":
        result = initialize(root, args.force, args.project_cache, resolve_init_ui_mode(args.ui_mode, args.json), resolve_init_mock_data(args.mock_data, args.json))
    elif args.command == "status":
        result, _, _, _ = inspect_cache(root, args.verify_content)
    elif args.command == "sync":
        result = sync_project(root, args.force, args.verify_content)
    elif args.command == "context":
        status, _, paths, config = inspect_cache(root)
        if status["status"] == "stale" and not args.no_sync and config.get("autoSync", True):
            result = sync_project(root)
        else:
            result = status
        context_path = paths["context"]
        if args.screen:
            try:
                context_path = write_screen_context(paths, args.screen)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 3
        result = {**result, "contextFile": str(context_path)}
    elif args.command == "map":
        status, _, paths, config = inspect_cache(root)
        result = sync_project(root) if status["status"] == "stale" and config.get("autoSync", True) else status
        graph_path = paths["graph"]
        if args.output:
            destination = args.output.resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(graph_path, destination)
            graph_path = destination
        result = {**result, "graphFile": str(graph_path)}
    elif args.command == "render":
        try:
            result = render_artifact(args.ir, args.output, args.allow_draft, args.agent)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 3
    elif args.command == "validate":
        try:
            result = validate_artifact(args.ir, args.output_dir)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 3
    elif args.command == "ui-mode":
        result = configure_ui_mode(root, True if args.enable else False if args.disable else None)
    else:
        result = doctor(root)
    print_result(result, args.json)
    return 4 if args.command == "validate" and result.get("status") != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
