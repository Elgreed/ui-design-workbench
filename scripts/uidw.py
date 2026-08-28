#!/usr/bin/env python3
"""Provider-neutral UI Design Workbench command line interface.

The cache is lazy and deterministic: source contents are read only on the
initial scan or after a candidate UI file fingerprint changes. No watcher,
server, application runtime, emulator, or development server is started.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
import zipfile
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


CACHE_VERSION = 3
CLI_VERSION = "0.2.0"
CONFIG_VERSION = 2
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
DESIGN_MODEL_NAME = "design-model.json"
REVIEW_STATE_NAME = "review-state.json"
STATE_LOCK_NAME = ".state.lock"
STATE_GITIGNORE = "*\n!.gitignore\n!config.json\n"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


@contextlib.contextmanager
def state_lock(path: Path, timeout_seconds: float = 10.0):
    """Serialize cache writers without requiring a daemon or third-party lock package."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()}\ncreated={utc_now()}\n".encode("utf-8"))
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > 120
            except OSError:
                stale = False
            if stale:
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"UI cache is locked by another process: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()


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
        "design": directory / DESIGN_MODEL_NAME,
        "review": directory / REVIEW_STATE_NAME,
        "lock": directory / STATE_LOCK_NAME,
        "gitignore": directory / ".gitignore",
    }


def default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
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
    mock_seed = str(mock_data.get("seed", "stable")) if isinstance(mock_data, dict) else "stable"
    if mock_mode not in {"none", "representative", "exhaustive"}:
        mock_mode = "none"
    config[MOCK_DATA_KEY] = {"mode": mock_mode, "seed": mock_seed or "stable"}
    config["version"] = CONFIG_VERSION
    return config


def load_config(path: Path, migrate: bool = True) -> dict[str, Any]:
    raw = read_json(path, {})
    config = normalized_config(raw)
    old_version = int(raw.get("version", 1)) if isinstance(raw, dict) else 1
    if migrate and path.is_file() and old_version < CONFIG_VERSION:
        backup = path.with_name(f"config.v{old_version}.backup.json")
        if not backup.exists() and isinstance(raw, dict):
            write_json(backup, raw)
        write_json(path, config)
    return config


def mock_data_context(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get(MOCK_DATA_KEY, {}).get("mode", "none"))
    enabled = mode != "none"
    result: dict[str, Any] = {"enabled": enabled, "mode": mode, "default": "off", "seed": str(config.get(MOCK_DATA_KEY, {}).get("seed", "stable"))}
    if enabled:
        result["instruction"] = (
            "Create deterministic, non-sensitive, platform-appropriate screen scenarios only when supported by "
            "the screen task or source branches. Use reusable scenarioFixtures plus sparse screen.scenarios; do "
            "not stamp the same loading/error/success set onto every screen. Representative mode keeps one "
            "populated fixture and only critical alternate states; exhaustive mode also covers evidenced boundary states. "
            "Represent source-evidenced lists, tables, and grids with repeated synthetic item nodes; one summary text "
            "line does not count as a populated collection."
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


def semantic_diff(old_scan: dict[str, Any], new_scan: dict[str, Any]) -> dict[str, list[str]]:
    def keys(scan: dict[str, Any], section: str, fields: tuple[str, ...]) -> set[str]:
        return {
            "#".join(str(item.get(field) or "") for field in fields)
            for item in scan.get(section, [])
            if isinstance(item, dict)
        }

    result: dict[str, list[str]] = {}
    for label, section, fields in (
        ("screens", "screens", ("file", "name")),
        ("routes", "routes", ("file", "route")),
        ("components", "components", ("file", "symbol")),
    ):
        before, after = keys(old_scan, section, fields), keys(new_scan, section, fields)
        result[f"added{label.title()}"] = sorted(after - before)
        result[f"removed{label.title()}"] = sorted(before - after)
    return result


def extract_design_model(ir: dict[str, Any] | None) -> dict[str, Any]:
    """Keep authored screen/node/scenario detail separate from the generated source index."""
    if not isinstance(ir, dict):
        return {"version": 1, "screens": {}, "nodes": {}, "scenarioFixtures": {}}
    return {
        "version": 1,
        "screens": {
            str(item["id"]): copy.deepcopy(item)
            for item in ir.get("screens", [])
            if isinstance(item, dict) and item.get("id")
        },
        "nodes": copy.deepcopy(ir.get("nodes", {})) if isinstance(ir.get("nodes"), dict) else {},
        "scenarioFixtures": copy.deepcopy(ir.get("scenarioFixtures", {})) if isinstance(ir.get("scenarioFixtures"), dict) else {},
        "savedAt": utc_now(),
    }


def extract_review_state(ir: dict[str, Any] | None) -> dict[str, Any]:
    review = copy.deepcopy(ir.get("review", {})) if isinstance(ir, dict) and isinstance(ir.get("review"), dict) else {}
    return {"version": 1, "review": review, "savedAt": utc_now()}


def merge_authored_state(
    generated: dict[str, Any],
    design_model: dict[str, Any],
    review_state: dict[str, Any],
    impacted_screen_ids: list[str],
) -> dict[str, Any]:
    """Overlay durable authored detail while marking changed source bindings as stale."""
    result = copy.deepcopy(generated)
    impacted = set(impacted_screen_ids)
    generated_screens = {str(item.get("id")): item for item in result.get("screens", []) if item.get("id")}
    preserved_screens = design_model.get("screens", {}) if isinstance(design_model.get("screens"), dict) else {}
    for screen_id, authored in preserved_screens.items():
        current = generated_screens.get(str(screen_id))
        if current is None or not isinstance(authored, dict):
            continue
        source = copy.deepcopy(current.get("source", {}))
        current.update(copy.deepcopy(authored))
        if source:
            current["source"] = source
        if screen_id in impacted:
            current["sourceState"] = "stale"
        else:
            current.pop("sourceState", None)
    result["screens"] = list(generated_screens.values())

    current_screen_ids = set(generated_screens)
    old_nodes = design_model.get("nodes", {}) if isinstance(design_model.get("nodes"), dict) else {}
    old_screen_map = node_screen_map({"screens": list(preserved_screens.values()), "nodes": old_nodes})
    for node_id, authored in old_nodes.items():
        owners = old_screen_map.get(str(node_id), set())
        if owners and not owners.intersection(current_screen_ids):
            continue
        existing = result.setdefault("nodes", {}).get(node_id, {})
        merged = copy.deepcopy(existing)
        merged.update(copy.deepcopy(authored))
        if owners.intersection(impacted):
            merged["sourceState"] = "stale"
        else:
            merged.pop("sourceState", None)
        result["nodes"][node_id] = merged

    fixtures = design_model.get("scenarioFixtures", {})
    if isinstance(fixtures, dict) and fixtures:
        result["scenarioFixtures"] = copy.deepcopy(fixtures)

    old_review = review_state.get("review", {}) if isinstance(review_state.get("review"), dict) else {}
    if old_review:
        base_review = result.setdefault("review", {})
        preserved = copy.deepcopy(old_review)
        known_screens = set(current_screen_ids)
        audit = preserved.get("audit", {}) if isinstance(preserved.get("audit"), dict) else {}
        findings = []
        for finding in audit.get("findings", []):
            if not isinstance(finding, dict) or finding.get("screenId") not in known_screens:
                continue
            item = copy.deepcopy(finding)
            if item.get("screenId") in impacted:
                item["sourceState"] = "stale"
            findings.append(item)
        if findings or "findings" in audit:
            audit["findings"] = findings
            preserved["audit"] = audit
        generated_baseline = next((item for item in base_review.get("versions", []) if item.get("kind") == "baseline"), None)
        proposals = [item for item in preserved.get("versions", []) if item.get("kind") != "baseline"]
        preserved["versions"] = ([generated_baseline] if generated_baseline else []) + proposals
        base_review.update(preserved)
        if generated_baseline:
            base_review["baselineVersion"] = generated_baseline.get("id", "baseline")
    return result


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
    config = load_config(paths["config"])
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
    initial_paths = state_paths(root)
    with state_lock(initial_paths["lock"]):
        status, current_manifest, paths, config = inspect_cache(root, verify_content)
        cache = read_json(paths["cache"], {}) or {}
        old_scan = read_json(paths["scan"], {}) or {}
        old_ir = load_project_ir(paths)
        design_model = read_json(paths["design"], None)
        review_state = read_json(paths["review"], None)
        if isinstance(old_ir, dict):
            design_model = extract_design_model(old_ir)
            review_state = extract_review_state(old_ir)
        elif not isinstance(design_model, dict):
            design_model = extract_design_model(None)
        if not isinstance(review_state, dict):
            review_state = extract_review_state(None)
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
            generated_ir = starter_ir(inventory)
            impacted = sorted(set(
                impacted_screens(old_ir, old_scan, inventory, status["changedUiFiles"], invalidate_all)
                + impacted_screens(generated_ir, old_scan, inventory, status["changedUiFiles"], invalidate_all)
            ))
            new_ir = merge_authored_state(generated_ir, design_model, review_state, impacted)
            synced_at = utc_now()
            paths["dir"].mkdir(parents=True, exist_ok=True)
            write_json(paths["scan"], inventory)
            write_json(paths["graph"], build_ui_graph(root, inventory))
            write_json(paths["ir"], new_ir)
            write_json(paths["design"], extract_design_model(new_ir))
            write_json(paths["review"], extract_review_state(new_ir))
            write_json(paths["cache"], {
                "cacheVersion": CACHE_VERSION,
                "scannerVersion": SCANNER_VERSION,
                "repoRoot": str(root),
                "configHash": config_hash(config),
                "syncedAt": synced_at,
                "manifest": current_manifest,
                "fileRecords": file_records,
            })
            report = {
                **status,
                "status": "synced",
                "syncedAt": synced_at,
                "impactedScreenIds": impacted,
                "semanticChanges": semantic_diff(old_scan, inventory),
            }
        current_ir = load_project_ir(paths)
        if current_ir and not paths["design"].is_file():
            write_json(paths["design"], extract_design_model(current_ir))
        if current_ir and not paths["review"].is_file():
            write_json(paths["review"], extract_review_state(current_ir))
        context = compact_context(root, inventory, report, current_ir, config)
        context["uiGraphFile"] = str(paths["graph"])
        context["designModelFile"] = str(paths["design"])
        context["reviewStateFile"] = str(paths["review"])
        write_json(paths["context"], context)
        write_json(paths["sync"], report)
        return report


def initialize(root: Path, force: bool = False, project_cache: bool = False, ui_mode: bool = False, mock_data_mode: str = "none") -> dict[str, Any]:
    if project_cache:
        config_path = root / STATE_DIR_NAME / CONFIG_NAME
        config = load_config(config_path)
        config["cacheMode"] = "project"
    else:
        initial_paths = state_paths(root)
        config_path = initial_paths["config"]
        config = load_config(config_path)
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
    config = load_config(paths["config"])
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


def configure_mock_data(root: Path, mode: str | None = None, seed: str | None = None) -> dict[str, Any]:
    paths = state_paths(root)
    config = load_config(paths["config"])
    current = config.get(MOCK_DATA_KEY, {"mode": "none", "seed": "stable"})
    if mode is not None or seed is not None:
        config[MOCK_DATA_KEY] = {
            "mode": mode if mode is not None else current.get("mode", "none"),
            "seed": seed if seed is not None else current.get("seed", "stable"),
        }
        paths["config"].parent.mkdir(parents=True, exist_ok=True)
        write_json(paths["config"], normalized_config(config))
        sync_project(root)
        paths = state_paths(root)
        config = load_config(paths["config"])
    value = mock_data_context(config)
    return {
        "version": 1,
        "status": "enabled" if value["enabled"] else "disabled",
        "repoRoot": str(root),
        MOCK_DATA_KEY: value,
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
        "stateFiles": {"sourceIndex": str(paths["scan"]), "designModel": str(paths["design"]), "reviewState": str(paths["review"])},
        "cliVersion": CLI_VERSION,
        "configVersion": CONFIG_VERSION,
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


def trim_context_to_budget(payload: dict[str, Any], token_budget: int) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    limit = max(256, token_budget) * 4

    def size() -> int:
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    for key in ("components", "navigationTargets", "routes", "tokenFiles", "screens", "prioritySourceFiles", "nodes"):
        value = result.get(key)
        while size() > limit and isinstance(value, list) and len(value) > 1:
            del value[(len(value) + 1) // 2:]
        if size() <= limit:
            break
        if isinstance(value, dict):
            keys = list(value)
            while size() > limit and len(keys) > 1:
                for item in keys[(len(keys) + 1) // 2:]:
                    value.pop(item, None)
                keys = list(value)
        if size() <= limit:
            break
    result["contextBudget"] = {
        "requestedTokens": token_budget,
        "estimatedTokens": max(1, size() // 4),
        "truncated": size() > limit or size() < len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
    }
    return result


def context_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# UI Design Workbench context",
        "",
        f"- Repository: `{payload.get('repoRoot', '')}`",
        f"- Cache: `{payload.get('cacheStatus', 'unknown')}`",
        f"- Platforms: {', '.join(payload.get('detectedPlatforms', payload.get('platforms', []))) or 'unknown'}",
        f"- Changed UI files: {len(payload.get('changedUiFiles', []))}",
        f"- Impacted screens: {len(payload.get('impactedScreenIds', []))}",
        "",
        "## Priority source files",
        "",
    ]
    lines.extend(f"- `{item}`" for item in payload.get("prioritySourceFiles", payload.get("sourceFiles", [])))
    screens = payload.get("screens", [])
    if payload.get("screen"):
        screens = [payload["screen"]]
    lines.extend(["", "## Screens", ""])
    lines.extend(f"- `{item.get('id', item.get('name', 'screen'))}` — {item.get('name', item.get('file', ''))}" for item in screens if isinstance(item, dict))
    budget = payload.get("contextBudget")
    if budget:
        lines.extend(["", f"Estimated tokens: {budget.get('estimatedTokens')} / {budget.get('requestedTokens')}."])
    return "\n".join(lines).rstrip() + "\n"


def write_context_variant(
    paths: dict[str, Path],
    screen: str | None = None,
    token_budget: int | None = None,
    changed_only: bool = False,
    output_format: str = "json",
) -> Path:
    source = write_screen_context(paths, screen) if screen else paths["context"]
    payload = read_json(source, {})
    if not isinstance(payload, dict):
        raise ValueError("UI context is unavailable; run init or sync first")
    if changed_only:
        changed = set(payload.get("changedUiFiles", []))
        payload["prioritySourceFiles"] = [item for item in payload.get("prioritySourceFiles", []) if item in changed]
        for key in ("screens", "routes", "navigationTargets", "components"):
            if isinstance(payload.get(key), list):
                payload[key] = [item for item in payload[key] if item.get("file") in changed]
        payload["contextScope"] = "changed-only"
    if token_budget:
        payload = trim_context_to_budget(payload, token_budget)
    if not token_budget and not changed_only and output_format == "json":
        return source
    suffix = ".md" if output_format == "markdown" else ".json"
    label = re.sub(r"[^a-z0-9]+", "-", (screen or "project").lower()).strip("-") or "project"
    output = paths["dir"] / f"ui-context-{label}-bounded{suffix}"
    if output_format == "markdown":
        write_text_atomic(output, context_markdown(payload))
    else:
        write_json(output, payload)
    return output


def load_ir_argument(paths: dict[str, Path], ir_path: Path | None) -> tuple[Path, dict[str, Any]]:
    path = ir_path.resolve() if ir_path else paths["ir"]
    ir = read_json(path)
    if not isinstance(ir, dict):
        raise ValueError(f"Cannot read UI IR: {path}")
    return path, ir


def scenario_report(ir: dict[str, Any], screen_query: str | None = None) -> dict[str, Any]:
    fixtures = ir.get("scenarioFixtures", {}) if isinstance(ir.get("scenarioFixtures"), dict) else {}
    nodes = ir.get("nodes", {}) if isinstance(ir.get("nodes"), dict) else {}
    issues: list[dict[str, str]] = []
    screens: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    query = screen_query.lower() if screen_query else None
    for screen in ir.get("screens", []):
        if query and query not in {str(screen.get("id", "")).lower(), str(screen.get("name", "")).lower()}:
            continue
        declared = []
        reachable: set[str] = set()
        queue = [str(screen.get("root") or "")]
        while queue:
            node_id = queue.pop(0)
            if not node_id or node_id in reachable or node_id not in nodes:
                continue
            reachable.add(node_id)
            queue.extend(str(child) for child in nodes[node_id].get("children", []))
        collections = {
            node_id: node
            for node_id in reachable
            if (node := nodes.get(node_id, {})).get("type") in {"list", "collection", "grid", "table"}
            and (node.get("dataDriven") is True or isinstance(node.get("collection"), dict))
        }
        for scenario in screen.get("scenarios", []):
            scenario_id = str(scenario.get("id") or "")
            key = (str(screen.get("id")), scenario_id)
            if not scenario_id:
                issues.append({"screenId": str(screen.get("id")), "code": "missing-id", "message": "Scenario has no id"})
            elif key in seen:
                issues.append({"screenId": str(screen.get("id")), "code": "duplicate-id", "message": f"Duplicate scenario id: {scenario_id}"})
            seen.add(key)
            fixture_ref = scenario.get("fixtureRef")
            if fixture_ref and fixture_ref not in fixtures:
                issues.append({"screenId": str(screen.get("id")), "code": "missing-fixture", "message": f"Missing fixture: {fixture_ref}"})
            fixture = fixtures.get(fixture_ref, {}) if fixture_ref else {}
            fixture_overrides = fixture.get("nodeOverrides", {}) if isinstance(fixture, dict) and isinstance(fixture.get("nodeOverrides"), dict) else {}
            scenario_overrides = scenario.get("nodeOverrides", {}) if isinstance(scenario.get("nodeOverrides"), dict) else {}
            overrides = {**fixture_overrides, **scenario_overrides}
            collection_counts: dict[str, int] = {}
            for collection_id, collection in collections.items():
                effective_children = overrides.get(collection_id, {}).get("children", collection.get("children", []))
                item_ids = [
                    str(child) for child in effective_children or []
                    if not nodes.get(str(child), {}).get("emptyState")
                ]
                collection_counts[collection_id] = len(item_ids)
                minimum = int(collection.get("collection", {}).get("minMockItems", 2))
                if scenario_id == "mock-data" and len(item_ids) < minimum:
                    issues.append({
                        "screenId": str(screen.get("id")),
                        "code": "mock-collection-empty",
                        "message": f"Mock scenario must populate {collection_id} with at least {minimum} items; found {len(item_ids)}",
                    })
                for child in effective_children or []:
                    if str(child) not in nodes:
                        issues.append({"screenId": str(screen.get("id")), "code": "missing-collection-item", "message": f"Collection {collection_id} references missing item node: {child}"})
            declared.append({"id": scenario_id, "label": scenario.get("label", scenario_id), "fixtureRef": fixture_ref, "collectionCounts": collection_counts})
        default_id = screen.get("defaultScenarioId")
        if default_id and default_id not in {item["id"] for item in declared}:
            issues.append({"screenId": str(screen.get("id")), "code": "missing-default", "message": f"Default scenario is not declared: {default_id}"})
        screens.append({"id": screen.get("id"), "name": screen.get("name"), "defaultScenarioId": screen.get("defaultScenarioId"), "collections": sorted(collections), "scenarios": declared})
    if query and not screens:
        issues.append({"screenId": screen_query or "", "code": "unknown-screen", "message": "Screen was not found"})
    return {"version": 1, "status": "pass" if not issues else "fail", "screens": screens, "fixtures": sorted(fixtures), "issues": issues}


FINDING_RANK = {"blocker": 4, "high": 3, "medium": 2, "low": 1}


def ordered_findings(ir: dict[str, Any], feedback: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for item in ir.get("review", {}).get("audit", {}).get("findings", []):
        if isinstance(item, dict) and item.get("id"):
            values[str(item["id"])] = copy.deepcopy(item)
    if isinstance(feedback, dict):
        for item in feedback.get("runtimeFindings", []):
            if isinstance(item, dict) and item.get("id"):
                values[str(item["id"])] = copy.deepcopy(item)
    source_order = {item_id: index for index, item_id in enumerate(values)}
    return sorted(values.values(), key=lambda item: (-FINDING_RANK.get(str(item.get("severity")), 0), source_order[str(item["id"])]))


def finding_report(
    ir: dict[str, Any],
    feedback: dict[str, Any] | None = None,
    screen: str | None = None,
    status_filter: str | None = None,
) -> dict[str, Any]:
    findings = ordered_findings(ir, feedback)
    decisions = copy.deepcopy(ir.get("review", {}).get("audit", {}).get("findingDecisions", {}))
    if isinstance(feedback, dict) and isinstance(feedback.get("findingDecisions"), dict):
        decisions.update(feedback["findingDecisions"])
    rows = []
    for number, item in enumerate(findings, 1):
        decision = decisions.get(item["id"], "pending")
        state = "resolved" if item.get("status") == "resolved" else decision
        if screen and str(item.get("screenId", "")).lower() != screen.lower():
            continue
        if status_filter and state != status_filter:
            continue
        rows.append({
            "number": number,
            "id": item["id"],
            "screenId": item.get("screenId"),
            "severity": item.get("severity", "medium"),
            "status": state,
            "title": item.get("title", "Untitled finding"),
            "sourceState": item.get("sourceState", "current"),
        })
    return {"version": 1, "status": "ok", "total": len(findings), "shown": len(rows), "screen": screen, "findings": rows}


def update_finding_decisions(ir: dict[str, Any], identifiers: list[str], decision: str) -> dict[str, Any]:
    findings = ordered_findings(ir)
    by_id = {str(item["id"]): item for item in findings}
    by_number = {str(index): item for index, item in enumerate(findings, 1)}
    resolved: list[str] = []
    unknown: list[str] = []
    decisions = ir.setdefault("review", {}).setdefault("audit", {}).setdefault("findingDecisions", {})
    for identifier in identifiers:
        item = by_id.get(identifier) or by_number.get(identifier)
        if not item:
            unknown.append(identifier)
            continue
        finding_id = str(item["id"])
        if decision == "resolved":
            item["status"] = "resolved"
            decisions.pop(finding_id, None)
            for original in ir["review"]["audit"].get("findings", []):
                if original.get("id") == finding_id:
                    original["status"] = "resolved"
        elif decision == "pending":
            decisions.pop(finding_id, None)
        else:
            decisions[finding_id] = decision
        resolved.append(finding_id)
    return {"version": 1, "status": "updated" if resolved else "unchanged", "decision": decision, "findingIds": resolved, "unknown": unknown}


def source_targets_for_findings(root: Path, findings: list[dict[str, Any]]) -> list[str]:
    targets: set[str] = set()
    for item in findings:
        explicit = item.get("sourceTarget") or item.get("sourceTargets") or []
        if isinstance(explicit, (str, dict)):
            explicit = [explicit]
        candidates: list[str] = []
        for value in explicit:
            candidates.append(str(value.get("file") if isinstance(value, dict) else value))
        source = item.get("source")
        if isinstance(source, dict) and source.get("file"):
            candidates.append(str(source["file"]))
        for evidence in item.get("evidence", []):
            if evidence.get("type") == "source" and evidence.get("ref"):
                candidates.append(str(evidence["ref"]).split("#", 1)[0])
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
            try:
                relative = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if resolved.is_file():
                targets.add(relative)
    return sorted(targets)


def prepare_agent_job(
    root: Path,
    ir_path: Path,
    ir: dict[str, Any],
    kind: str,
    output: Path,
    provider: str = "generic",
    identifiers: list[str] | None = None,
    scope: str = "all",
) -> dict[str, Any]:
    findings = ordered_findings(ir)
    by_id = {str(item["id"]): item for item in findings}
    by_number = {str(index): item for index, item in enumerate(findings, 1)}
    decisions = ir.get("review", {}).get("audit", {}).get("findingDecisions", {})
    selected_ids: list[str] = []
    for identifier in identifiers or []:
        item = by_id.get(identifier) or by_number.get(identifier)
        if item and item["id"] not in selected_ids:
            selected_ids.append(str(item["id"]))
    if not selected_ids and kind in {"proposal", "implementation"}:
        selected_ids = [str(item["id"]) for item in findings if decisions.get(item["id"]) == "accepted"]
    selected = [by_id[item] for item in selected_ids if item in by_id]
    if kind in {"proposal", "implementation"} and not selected:
        raise ValueError("No findings selected or accepted")
    source_change_allowed = kind == "implementation"
    source_targets = source_targets_for_findings(root, selected)
    if source_change_allowed and not source_targets:
        raise ValueError("Selected findings have no verified source targets inside the repository")
    allowed_writes = source_targets if source_change_allowed else ["ui-ir.json", "ui-preview.html", "*.report.json"]
    job = {
        "type": "ui-design-workbench-agent-job",
        "version": 2,
        "provider": provider,
        "kind": kind,
        "project": ir.get("project", {}).get("name", root.name),
        "projectRoot": str(root.resolve()),
        "artifactDir": str(ir_path.resolve().parent),
        "uiIrFile": str(ir_path.resolve()),
        "scope": scope,
        "screenIds": sorted({str(item.get("screenId")) for item in selected if item.get("screenId")}) if selected else [str(item.get("id")) for item in ir.get("screens", [])],
        "acceptedFindingIds": selected_ids,
        "sourceTargets": source_targets,
        "allowedWrites": allowed_writes,
        "sourceChangeAllowed": source_change_allowed,
        "requiredChatReport": ["number", "findingId", "screen", "problem", "implementedFix", "changedFiles", "verification", "remainingReason"],
        "requestedAction": {
            "expert": "Review the requested UI scope and return evidence-based findings without changing project source.",
            "proposal": "Create sparse proposal versions only for the selected findings without changing project source.",
            "implementation": "Implement the selected findings in the verified project source targets, run incremental uidw sync and targeted verification, and do not repeat the full AI review.",
        }[kind],
        "createdAt": utc_now(),
    }
    write_json(output.resolve(), job)
    return {"version": 1, "status": "prepared", "kind": kind, "jobFile": str(output.resolve()), "findingIds": selected_ids, "sourceTargets": source_targets}


def import_review_result(ir_path: Path, result_path: Path, output: Path) -> dict[str, Any]:
    from merge_review_state import merge, validate_feedback

    ir = read_json(ir_path)
    payload = read_json(result_path)
    if not isinstance(ir, dict) or not isinstance(payload, dict):
        raise ValueError("IR or review result is not valid JSON")
    incoming_ir = payload.get("uiIr") or payload.get("result", {}).get("uiIr")
    if isinstance(incoming_ir, dict):
        if incoming_ir.get("project", {}).get("name") != ir.get("project", {}).get("name"):
            raise ValueError("Review result belongs to another project")
        merged = incoming_ir
    else:
        errors = validate_feedback(ir, payload)
        if errors:
            raise ValueError("; ".join(errors))
        merged = merge(copy.deepcopy(ir), payload)
    write_json(output.resolve(), merged)
    return {"version": 1, "status": "imported", "irFile": str(output.resolve()), "source": str(result_path.resolve())}


def diff_project(root: Path, synchronize: bool = False) -> dict[str, Any]:
    if synchronize:
        sync_project(root)
    status, _, paths, _ = inspect_cache(root)
    last = read_json(paths["sync"], {}) if paths["sync"].is_file() else {}
    if status.get("status") == "clean" and isinstance(last, dict):
        return {"version": 1, "status": "clean", "repoRoot": str(root), "lastSync": last}
    old_scan = read_json(paths["scan"], {}) or {}
    ir = load_project_ir(paths)
    impacted = impacted_screens(ir, old_scan, old_scan, status.get("changedUiFiles", []), False)
    return {**status, "version": 1, "impactedScreenIds": impacted, "lastSync": last}


def print_result(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        return
    if isinstance(value.get("findings"), list):
        print(f"{value.get('status', 'ok')} | shown={value.get('shown', len(value['findings']))} | total={value.get('total', len(value['findings']))}")
        for item in value["findings"]:
            print(f"#{item['number']:<3} {str(item.get('severity', '')):<7} {str(item.get('status', '')):<9} {item.get('screenId', '—')} | {item.get('title', '')}")
        return
    if isinstance(value.get("screens"), list) and "fixtures" in value:
        print(f"{value.get('status', 'ok')} | screens={len(value['screens'])} | fixtures={len(value.get('fixtures', []))} | issues={len(value.get('issues', []))}")
        for screen in value["screens"]:
            print(f"{screen.get('id', 'screen')}: {len(screen.get('scenarios', []))} scenarios")
        for issue in value.get("issues", []):
            print(f"! {issue.get('screenId', 'project')} [{issue.get('code', 'issue')}] {issue.get('message', '')}")
        return
    if isinstance(value.get("checks"), dict):
        print(f"{value.get('status', 'ok')} | level={value.get('level', 'quick')}")
        for name, check in value["checks"].items():
            print(f"{name}: {check.get('status', 'unknown')}")
        if value.get("reportFile"):
            print(f"reportFile: {value['reportFile']}")
        return
    if isinstance(value.get("lastSync"), dict):
        last = value["lastSync"]
        print(f"{value.get('status', 'ok')} | changed={len(last.get('changedUiFiles', value.get('changedUiFiles', [])))} | impacted={len(last.get('impactedScreenIds', value.get('impactedScreenIds', [])))}")
        for key, items in last.get("semanticChanges", {}).items():
            if items:
                print(f"{key}: {', '.join(items)}")
        return
    changed = len(value.get("changedUiFiles", []))
    impacted = len(value.get("impactedScreenIds", []))
    mode = value.get(UI_MODE_KEY)
    mode_text = f" | ui-mode={'on' if mode.get('enabled') else 'off'}" if isinstance(mode, dict) else ""
    mock_data = value.get(MOCK_DATA_KEY)
    mock_text = f" | mock-data={mock_data.get('mode')}" if isinstance(mock_data, dict) else ""
    print(f"{value.get('status', 'ok')} | changed={changed} | impacted={impacted}{mode_text}{mock_text}")
    for key in ("contextFile", "graphFile", "previewFile", "reportFile", "jobFile", "irFile", "bundleFile", "outputDir", "diffImage", "url"):
        if value.get(key):
            print(f"{key}: {value[key]}")
    if value.get("findingIds"):
        print("findings: " + ", ".join(value["findingIds"]))
    if value.get("sourceTargets"):
        print("source targets: " + ", ".join(value["sourceTargets"]))


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


def preview_uri(path: Path, view: str | None = None, screen: str | None = None, lang: str | None = None) -> str:
    from urllib.parse import urlencode

    query = {key: value for key, value in {"view": view, "screen": screen, "lang": lang}.items() if value}
    return path.resolve().as_uri() + ("?" + urlencode(query) if query else "")


def open_preview(path: Path, launch: bool = False, view: str | None = None, screen: str | None = None, lang: str | None = None) -> dict[str, Any]:
    if not path.resolve().is_file():
        raise ValueError(f"Preview does not exist: {path.resolve()}")
    uri = preview_uri(path, view, screen, lang)
    launched = bool(webbrowser.open(uri)) if launch else False
    return {"version": 1, "status": "opened" if launched else "ready", "previewFile": str(path.resolve()), "url": uri, "launched": launched}


def run_headless_smoke(preview: Path, output_dir: Path) -> dict[str, Any]:
    node = shutil.which("node")
    chrome = chrome_path()
    if not node or not chrome:
        return {"version": 1, "status": "unavailable", "reason": "Node.js and Chromium/Edge are required for full smoke"}
    script = Path(__file__).resolve().parent / "smoke_preview.js"
    report = output_dir / "ui-diagnostics.json"
    command = [node, str(script), str(preview.resolve()), "--output", str(report)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return {"version": 1, "status": "fail", "reason": "Headless smoke timed out after 60 seconds"}
    data = read_json(report, {}) if report.is_file() else {}
    status = "pass" if completed.returncode == 0 and data.get("status") in {"pass", "complete"} else "fail"
    return {
        "version": 1,
        "status": status,
        "report": str(report),
        "exitCode": completed.returncode,
        "stderr": (completed.stderr or "").strip()[-2000:],
    }


def write_ci_report(report: dict[str, Any], output_dir: Path, output_format: str) -> Path | None:
    if output_format == "json":
        path = output_dir / "uidw-check.json"
        write_json(path, report)
        return path
    failures = []
    for name, result in report.get("checks", {}).items():
        if result.get("status") not in {"pass", "ok"}:
            failures.append((name, str(result.get("reason") or result.get("status"))))
    if output_format == "sarif":
        path = output_dir / "uidw-check.sarif"
        payload = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "UI Design Workbench", "version": CLI_VERSION}},
                "results": [{"ruleId": f"uidw/{name}", "level": "error", "message": {"text": message}} for name, message in failures],
            }],
        }
        write_json(path, payload)
        return path
    if output_format == "junit":
        path = output_dir / "uidw-check.xml"
        cases = []
        for name, result in report.get("checks", {}).items():
            failure = "" if result.get("status") in {"pass", "ok"} else f'<failure message="{html.escape(str(result.get("reason") or result.get("status")), quote=True)}" />'
            cases.append(f'<testcase classname="uidw" name="{html.escape(name, quote=True)}">{failure}</testcase>')
        xml = f'<?xml version="1.0" encoding="UTF-8"?><testsuite name="uidw" tests="{len(cases)}" failures="{len(failures)}">{"".join(cases)}</testsuite>\n'
        write_text_atomic(path, xml)
        return path
    return None


def check_artifact(
    ir_path: Path,
    output_dir: Path,
    level: str = "quick",
    output_format: str = "json",
    preview: Path | None = None,
) -> dict[str, Any]:
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    validation = validate_artifact(ir_path, destination)
    ir = read_json(ir_path, {})
    from render_preview import validate as validate_ir
    structural_errors = validate_ir(ir)
    scenarios = scenario_report(ir)
    structure = {"version": 1, "status": "pass" if not structural_errors else "fail", "errors": structural_errors}
    checks: dict[str, Any] = {"irStructure": structure, "platformAndCoverage": validation, "scenarios": scenarios}
    preview_path = preview.resolve() if preview else destination / "ui-preview.html"
    if level == "full":
        if not preview_path.is_file():
            render_artifact(ir_path, preview_path, True, "generic")
        checks["headlessSmoke"] = run_headless_smoke(preview_path, destination)
    status = "pass" if all(item.get("status") in {"pass", "ok"} for item in checks.values()) else "fail"
    report = {"version": 1, "status": status, "level": level, "irFile": str(ir_path.resolve()), "previewFile": str(preview_path) if preview_path.is_file() else None, "checks": checks}
    ci_path = write_ci_report(report, destination, output_format)
    if ci_path:
        report["reportFile"] = str(ci_path)
        if output_format == "json":
            write_json(ci_path, report)
    return report


def build_workbench(
    root: Path,
    ir_path: Path | None,
    output_dir: Path,
    level: str,
    allow_draft: bool,
    agent: str,
    launch: bool,
    view: str | None,
    screen: str | None,
    lang: str | None,
) -> dict[str, Any]:
    paths = state_paths(root)
    if ir_path is None:
        status, _, _, config = inspect_cache(root)
        if status["status"] == "stale" and config.get("autoSync", True):
            sync_project(root)
        ir_path = paths["ir"]
        allow_draft = True
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    preview = destination / "ui-preview.html"
    rendered = render_artifact(ir_path, preview, allow_draft, agent)
    checked = check_artifact(ir_path, destination / "validation", level, "json", preview)
    opened = open_preview(preview, launch, view, screen, lang)
    status = "pass" if checked["status"] == "pass" else "warning"
    return {"version": 1, "status": status, "render": rendered, "check": checked, "previewFile": str(preview), "url": opened["url"], "launched": opened["launched"]}


def pack_artifact(ir_path: Path, output: Path) -> dict[str, Any]:
    ir_path = ir_path.resolve()
    if not ir_path.is_file():
        raise ValueError(f"Cannot read UI IR: {ir_path}")
    base = ir_path.parent
    ir = read_json(ir_path, {})
    candidates = [ir_path]
    for pattern in ("ui-preview.html", "*.report.json", "ui-coverage.json", "ui-diagnostics*.json", "ui-agent-job*.json"):
        candidates.extend(path for path in base.glob(pattern) if path.is_file())
    files = []
    for path in sorted(set(candidates), key=lambda item: item.name.lower()):
        if path.name.startswith("ui-agent-job"):
            job = read_json(path, {})
            if isinstance(job, dict) and job.get("sourceChangeAllowed") is True:
                continue
        files.append(path)
    project_root = str(ir.get("project", {}).get("root") or "") if isinstance(ir, dict) else ""
    replacements = {
        str(base.resolve()): "<artifact-dir>",
        base.resolve().as_posix(): "<artifact-dir>",
    }
    if project_root:
        replacements[project_root] = "<project-root>"
        replacements[project_root.replace("\\", "/")] = "<project-root>"

    def sanitized_bytes(path: Path) -> bytes:
        raw = path.read_bytes()
        if path.suffix.lower() not in {".json", ".html", ".md", ".txt"}:
            return raw
        text = raw.decode("utf-8")
        for original, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
            if original:
                text = text.replace(original, replacement)
        return text.encode("utf-8")

    payloads = {path: sanitized_bytes(path) for path in files}
    manifest_files = []
    for path in files:
        relative = path.relative_to(base).as_posix()
        payload = payloads[path]
        manifest_files.append({"path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
    manifest = {
        "version": 1,
        "type": "ui-design-workbench-bundle",
        "createdAt": utc_now(),
        "project": ir.get("project", {}).get("name", base.name),
        "sourceIncluded": False,
        "files": manifest_files,
    }
    destination = output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("uidw-bundle.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for path in files:
                archive.writestr(path.relative_to(base).as_posix(), payloads[path])
        os.replace(temporary, destination)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    return {"version": 1, "status": "packed", "bundleFile": str(destination), "files": len(files)}


def unpack_artifact(bundle: Path, output_dir: Path) -> dict[str, Any]:
    source = bundle.resolve()
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(source, "r") as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError(f"Unsafe bundle path: {info.filename}") from exc
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text = archive.read(info)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            try:
                temporary.write_bytes(write_text)
                os.replace(temporary, target)
            finally:
                with contextlib.suppress(OSError):
                    temporary.unlink()
            extracted.append(info.filename)
    manifest = read_json(destination / "uidw-bundle.json", {})
    for item in manifest.get("files", []) if isinstance(manifest, dict) else []:
        path = destination / item.get("path", "")
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise ValueError(f"Bundle integrity check failed: {item.get('path')}")
    return {"version": 1, "status": "unpacked", "outputDir": str(destination), "files": extracted}


def visual_test(
    baseline: Path,
    candidate: Path,
    output_dir: Path,
    baseline_geometry: Path | None = None,
    candidate_geometry: Path | None = None,
) -> dict[str, Any]:
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    report = destination / "visual-regression.json"
    diff_image = destination / "visual-diff.png"
    script = Path(__file__).resolve().parent / "visual_regression.py"
    command = [sys.executable, str(script), "--baseline", str(baseline.resolve()), "--candidate", str(candidate.resolve()), "--output", str(report), "--diff-image", str(diff_image), "--strict"]
    if baseline_geometry and candidate_geometry:
        command.extend(["--baseline-geometry", str(baseline_geometry.resolve()), "--candidate-geometry", str(candidate_geometry.resolve())])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return {"version": 1, "status": "fail", "reportFile": str(report), "diffImage": None, "details": {}, "stderr": "Visual regression timed out after 60 seconds"}
    result = read_json(report, {}) if report.is_file() else {}
    return {"version": 1, "status": "pass" if completed.returncode == 0 else "fail", "reportFile": str(report), "diffImage": str(diff_image) if diff_image.is_file() else None, "details": result, "stderr": (completed.stderr or "").strip()[-2000:]}


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
    context_parser.add_argument("--budget", type=int, help="Approximate maximum token budget for the exported context")
    context_parser.add_argument("--changed-only", action="store_true", help="Include only files and entities affected by the latest UI change")
    context_parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Context artifact format")
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
    check_parser = subparsers.add_parser("check", help="Run the combined deterministic quality gate")
    check_parser.add_argument("--ir", type=Path, help="UI IR; defaults to the cached project IR")
    check_parser.add_argument("--output-dir", type=Path, help="Report directory; defaults to the project cache")
    check_parser.add_argument("--level", choices=("quick", "full"), default="quick")
    check_parser.add_argument("--format", choices=("json", "sarif", "junit"), default="json")
    check_parser.add_argument("--preview", type=Path, help="Existing preview for the full smoke gate")
    workbench_parser = subparsers.add_parser("workbench", help="Synchronize, render, check, and optionally open a workbench")
    workbench_parser.add_argument("--ir", type=Path, help="Review IR; defaults to the cached project IR")
    workbench_parser.add_argument("--output-dir", type=Path, help="Artifact directory; defaults to the project cache")
    workbench_parser.add_argument("--level", choices=("quick", "full"), default="quick")
    workbench_parser.add_argument("--allow-draft", action="store_true")
    workbench_parser.add_argument("--agent", choices=("generic", "codex"), default="generic")
    workbench_parser.add_argument("--open", action="store_true", dest="launch")
    workbench_parser.add_argument("--view", choices=("overview", "prototype", "single", "states", "compare"))
    workbench_parser.add_argument("--screen")
    workbench_parser.add_argument("--lang", choices=("ru", "en"))
    open_parser = subparsers.add_parser("open", help="Print a canonical local preview URL and optionally launch it")
    open_parser.add_argument("preview", type=Path, nargs="?", help="Preview HTML; defaults to the cached workbench")
    open_parser.add_argument("--launch", action="store_true")
    open_parser.add_argument("--view", choices=("overview", "prototype", "single", "states", "compare"))
    open_parser.add_argument("--screen")
    open_parser.add_argument("--lang", choices=("ru", "en"))
    diff_parser = subparsers.add_parser("diff", help="Show changed UI files, impacted screens, and the last semantic change")
    diff_parser.add_argument("--sync", action="store_true", help="Synchronize before returning the semantic diff")
    mode_parser = subparsers.add_parser("ui-mode", help="Show or change platform guidance for ordinary UI tasks")
    mode_group = mode_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--enable", action="store_true", help="Enable UI guidance without rescanning unchanged UI source")
    mode_group.add_argument("--disable", action="store_true", help="Disable UI guidance without rescanning unchanged UI source")
    mock_parser = subparsers.add_parser("mock-data", help="Show or change deterministic mock-data policy")
    mock_parser.add_argument("--set", dest="mock_mode", choices=("none", "representative", "exhaustive"))
    mock_parser.add_argument("--seed", help="Stable synthetic-data seed")
    scenarios_parser = subparsers.add_parser("scenarios", help="List and validate declared screen scenarios")
    scenarios_parser.add_argument("action", choices=("list", "validate"), nargs="?", default="list")
    scenarios_parser.add_argument("--ir", type=Path)
    scenarios_parser.add_argument("--screen")
    findings_parser = subparsers.add_parser("findings", help="List or classify review findings by stable id/number")
    findings_parser.add_argument("action", choices=("list", "accept", "reject", "defer", "reset", "resolve"), nargs="?", default="list")
    findings_parser.add_argument("identifiers", nargs="*", help="Stable finding IDs or displayed global numbers")
    findings_parser.add_argument("--ir", type=Path)
    findings_parser.add_argument("--feedback", type=Path, help="Optional exported browser feedback containing runtime findings")
    findings_parser.add_argument("--screen")
    findings_parser.add_argument("--status", choices=("pending", "accepted", "rejected", "deferred", "resolved"))
    review_parser = subparsers.add_parser("review", help="Prepare a provider-neutral review job or import its result")
    review_parser.add_argument("action", choices=("prepare", "import"))
    review_parser.add_argument("result", type=Path, nargs="?", help="Result JSON for review import")
    review_parser.add_argument("--ir", type=Path)
    review_parser.add_argument("--output", type=Path)
    review_parser.add_argument("--provider", default="generic")
    review_parser.add_argument("--scope", choices=("all", "current"), default="all")
    proposal_parser = subparsers.add_parser("proposal", help="Prepare a source-read-only proposal job")
    proposal_parser.add_argument("action", choices=("prepare",), nargs="?", default="prepare")
    proposal_parser.add_argument("identifiers", nargs="*")
    proposal_parser.add_argument("--ir", type=Path)
    proposal_parser.add_argument("--output", type=Path)
    proposal_parser.add_argument("--provider", default="generic")
    apply_parser = subparsers.add_parser("apply", help="Prepare an explicit bounded project-source implementation job")
    apply_parser.add_argument("action", choices=("prepare",), nargs="?", default="prepare")
    apply_parser.add_argument("identifiers", nargs="*")
    apply_parser.add_argument("--ir", type=Path)
    apply_parser.add_argument("--output", type=Path)
    apply_parser.add_argument("--provider", default="generic")
    pack_parser = subparsers.add_parser("pack", help="Create a portable source-free workbench bundle")
    pack_parser.add_argument("--ir", type=Path)
    pack_parser.add_argument("--output", type=Path, required=True)
    unpack_parser = subparsers.add_parser("unpack", help="Safely extract and verify a portable workbench bundle")
    unpack_parser.add_argument("bundle", type=Path)
    unpack_parser.add_argument("--output-dir", type=Path, required=True)
    visual_parser = subparsers.add_parser("visual-test", help="Compare an approved screenshot/geometry baseline with a candidate")
    visual_parser.add_argument("--baseline", type=Path, required=True)
    visual_parser.add_argument("--candidate", type=Path, required=True)
    visual_parser.add_argument("--output-dir", type=Path, required=True)
    visual_parser.add_argument("--baseline-geometry", type=Path)
    visual_parser.add_argument("--candidate-geometry", type=Path)
    subparsers.add_parser("doctor", help="Check local runtime and cache capabilities")
    return parser.parse_args()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(OSError):
                stream.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.repo.resolve()
    if not root.is_dir():
        print(f"Repository directory does not exist: {root}", file=sys.stderr)
        return 2
    paths = state_paths(root)
    try:
        if args.command == "init":
            result = initialize(root, args.force, args.project_cache, resolve_init_ui_mode(args.ui_mode, args.json), resolve_init_mock_data(args.mock_data, args.json))
        elif args.command == "status":
            result, _, _, _ = inspect_cache(root, args.verify_content)
        elif args.command == "sync":
            result = sync_project(root, args.force, args.verify_content)
        elif args.command == "context":
            status, _, paths, config = inspect_cache(root)
            result = sync_project(root) if status["status"] == "stale" and not args.no_sync and config.get("autoSync", True) else status
            context_path = write_context_variant(paths, args.screen, args.budget, args.changed_only, args.format)
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
            result = render_artifact(args.ir, args.output, args.allow_draft, args.agent)
        elif args.command == "validate":
            result = validate_artifact(args.ir, args.output_dir)
        elif args.command == "check":
            ir_path, _ = load_ir_argument(paths, args.ir)
            output_dir = args.output_dir or paths["dir"] / "validation"
            result = check_artifact(ir_path, output_dir, args.level, args.format, args.preview)
        elif args.command == "workbench":
            output_dir = args.output_dir or paths["dir"] / "workbench"
            result = build_workbench(root, args.ir, output_dir, args.level, args.allow_draft, args.agent, args.launch, args.view, args.screen, args.lang)
        elif args.command == "open":
            preview = args.preview or paths["dir"] / "workbench" / "ui-preview.html"
            result = open_preview(preview, args.launch, args.view, args.screen, args.lang)
        elif args.command == "diff":
            result = diff_project(root, args.sync)
        elif args.command == "ui-mode":
            result = configure_ui_mode(root, True if args.enable else False if args.disable else None)
        elif args.command == "mock-data":
            result = configure_mock_data(root, args.mock_mode, args.seed)
        elif args.command == "scenarios":
            _, ir = load_ir_argument(paths, args.ir)
            result = scenario_report(ir, args.screen)
        elif args.command == "findings":
            ir_path, ir = load_ir_argument(paths, args.ir)
            feedback = read_json(args.feedback.resolve(), {}) if args.feedback else None
            if args.action == "list":
                result = finding_report(ir, feedback, args.screen, args.status)
            else:
                if not args.identifiers:
                    raise ValueError("Specify at least one finding id or number")
                decision = {"accept": "accepted", "reject": "rejected", "defer": "deferred", "reset": "pending", "resolve": "resolved"}[args.action]
                result = update_finding_decisions(ir, args.identifiers, decision)
                write_json(ir_path, ir)
        elif args.command == "review":
            ir_path, ir = load_ir_argument(paths, args.ir)
            if args.action == "prepare":
                output = args.output or ir_path.parent / "ui-agent-job.json"
                result = prepare_agent_job(root, ir_path, ir, "expert", output, args.provider, scope=args.scope)
            else:
                if not args.result:
                    raise ValueError("Review import requires a result JSON path")
                output = args.output or ir_path.with_name("ui-ir.imported.json")
                result = import_review_result(ir_path, args.result, output)
        elif args.command in {"proposal", "apply"}:
            ir_path, ir = load_ir_argument(paths, args.ir)
            kind = "proposal" if args.command == "proposal" else "implementation"
            output = args.output or ir_path.parent / f"ui-agent-job-{kind}.json"
            result = prepare_agent_job(root, ir_path, ir, kind, output, args.provider, args.identifiers)
        elif args.command == "pack":
            ir_path, _ = load_ir_argument(paths, args.ir)
            result = pack_artifact(ir_path, args.output)
        elif args.command == "unpack":
            result = unpack_artifact(args.bundle, args.output_dir)
        elif args.command == "visual-test":
            result = visual_test(args.baseline, args.candidate, args.output_dir, args.baseline_geometry, args.candidate_geometry)
        else:
            result = doctor(root)
    except (ValueError, TimeoutError, OSError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print_result(result, args.json)
    return 4 if args.command in {"validate", "check", "visual-test"} and result.get("status") != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
