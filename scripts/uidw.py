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
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import Any

from quality_common import node_screen_map
from fidelity_core import fidelity_report, seal_baseline
from fidelity_adapters import adapter_capabilities
from platform_component_catalog import catalog_summary, validate_component_catalog
from scoped_context import (
    apply_patch_file,
    build_scoped_context,
    patch_template,
    read_json as read_scoped_json,
    validate_patch as validate_ir_patch,
    write_json as write_scoped_json,
)
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


CACHE_VERSION = 10
CLI_VERSION = "0.6.9"
CONFIG_VERSION = 5
STATE_DIR_NAME = ".ui-design-workbench"
CONFIG_NAME = "config.json"
UI_MODE_KEY = "uiMode"
MOCK_DATA_KEY = "mockData"
SETUP_KEY = "setup"
DETAIL_KEY = "detailLevel"
PREVIEW_KEY = "preview"
REVIEW_KEY = "review"
MOCK_DATA_BY_DETAIL = {
    "low": "minimal",
    "medium": "representative",
    "high": "exhaustive",
}
CACHE_NAME = "cache-state.json"
SCAN_NAME = "ui-scan.json"
IR_NAME = "ui-ir.json"
GRAPH_NAME = "ui-graph.json"
CONTEXT_NAME = "ui-context.json"
SYNC_REPORT_NAME = "sync-report.json"
DESIGN_MODEL_NAME = "design-model.json"
REVIEW_STATE_NAME = "review-state.json"
NATIVE_RENDER_STATE_NAME = "native-render-state.json"
STATE_LOCK_NAME = ".state.lock"
STATE_GITIGNORE = "*\n!.gitignore\n!config.json\n"
SKILL_NAME = "ui-design-workbench"
SKILL_MARKER_NAME = ".uidw-skill.json"
SUPPORTED_SKILL_AGENTS = ("codex", "claude", "cursor", "gemini", "copilot", "opencode", "agents")
SKILL_SCRIPT_FILES = (
    "android_resource_resolver.py",
    "android_xml_support.py",
    "apple_resource_resolver.py",
    "coverage_report.py",
    "fidelity_adapter_api.py",
    "fidelity_adapters.py",
    "source_syntax.py",
    "compose_syntax.py",
    "compose_resources.py",
    "compose_instances.py",
    "fidelity_core.py",
    "fidelity_platform_adapters.py",
    "generate_interaction_matrix.py",
    "ir_contracts.py",
    "layout_model.py",
    "merge_review_state.py",
    "native_render_android.py",
    "native_render_apple.py",
    "native_render_contracts.py",
    "native_render_registry.py",
    "quality_common.py",
    "render_preview.py",
    "scan_ui.py",
    "scoped_context.py",
    "smoke_preview.js",
    "uidw.py",
    "uidw_mcp.py",
    "validate_platform_profiles.py",
    "visual_regression.py",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def skill_source_dir() -> Path:
    """Locate the complete skill payload in a checkout or installed wheel."""
    module = Path(__file__).resolve()
    candidates = (
        module.parent.parent,
        Path(sys.prefix) / "share" / "ui-design-workbench",
        module.parent / "share" / "ui-design-workbench",
    )
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file() and (candidate / "references").is_dir():
            return candidate
    checked = ", ".join(str(path) for path in candidates)
    raise RuntimeError(f"Packaged Agent Skill is unavailable. Checked: {checked}")


def agent_skill_paths(agent: str, home: Path | None = None) -> dict[str, Path]:
    base = (home or Path.home()).resolve()
    paths = {
        "agents": base / ".agents" / "skills" / SKILL_NAME,
        "codex": base / ".codex" / "skills" / SKILL_NAME,
        "claude": base / ".claude" / "skills" / SKILL_NAME,
        "cursor": base / ".cursor" / "skills" / SKILL_NAME,
        "gemini": base / ".gemini" / "skills" / SKILL_NAME,
        "copilot": base / ".copilot" / "skills" / SKILL_NAME,
        "opencode": base / ".config" / "opencode" / "skills" / SKILL_NAME,
    }
    if agent == "all":
        return paths
    if agent not in paths:
        raise ValueError(f"Unknown agent: {agent}. Available: {', '.join((*SUPPORTED_SKILL_AGENTS, 'all'))}")
    return {agent: paths[agent]}


def copy_skill_payload(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "SKILL.md", destination / "SKILL.md")
    for folder, patterns in (("references", ("*.md", "*.json")), ("schemas", ("*.json",))):
        source_dir = source / folder
        target_dir = destination / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for path in source_dir.glob(pattern):
                if path.is_file():
                    shutil.copy2(path, target_dir / path.name)
    scripts_source = source / "scripts"
    scripts_target = destination / "scripts"
    scripts_target.mkdir(parents=True, exist_ok=True)
    for name in SKILL_SCRIPT_FILES:
        path = scripts_source / name
        if not path.is_file():
            raise RuntimeError(f"Packaged Agent Skill is missing scripts/{name}")
        shutil.copy2(path, scripts_target / name)


def install_skill(agent: str, target: Path | None = None, source: Path | None = None) -> dict[str, Any]:
    """Install or refresh UIDW-managed Agent Skill copies without a Git checkout."""
    payload_source = (source or skill_source_dir()).resolve()
    if target is not None:
        if agent == "all":
            raise ValueError("--target cannot be combined with agent 'all'")
        targets = {agent: target.expanduser().resolve()}
    else:
        targets = agent_skill_paths(agent)
    for destination in targets.values():
        if not destination.exists():
            continue
        with contextlib.suppress(OSError):
            if destination.resolve() == payload_source:
                continue
        marker = read_json(destination / SKILL_MARKER_NAME, {})
        if not isinstance(marker, dict) or marker.get("type") != "ui-design-workbench-skill":
            raise ValueError(f"Skill target already exists and is not UIDW-managed: {destination}")
    installations = []
    for name, destination in targets.items():
        if destination.exists():
            with contextlib.suppress(OSError):
                if destination.resolve() == payload_source:
                    installations.append({"agent": name, "status": "linked", "path": str(destination)})
                    continue
            copy_skill_payload(payload_source, destination)
            status = "updated"
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging_root = Path(tempfile.mkdtemp(prefix=".uidw-skill-", dir=destination.parent))
            staged = staging_root / SKILL_NAME
            try:
                copy_skill_payload(payload_source, staged)
                os.replace(staged, destination)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
            status = "installed"
        write_json(destination / SKILL_MARKER_NAME, {
            "type": "ui-design-workbench-skill",
            "version": 1,
            "cliVersion": CLI_VERSION,
            "agent": name,
        })
        installations.append({"agent": name, "status": status, "path": str(destination)})
    return {"version": 1, "status": "ok", "skillInstallations": installations, "cliVersion": CLI_VERSION}


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


def _lock_owner_pid(path: Path) -> int | None:
    try:
        match = re.search(r"^pid=(\d+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        return int(match.group(1)) if match else None
    except (OSError, ValueError):
        return None


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


@contextlib.contextmanager
def state_lock(path: Path, timeout_seconds: float = 10.0):
    """Serialize cache writers without requiring a daemon or third-party lock package."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    token = f"{os.getpid()}-{time.time_ns()}"
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()}\ntoken={token}\ncreated={utc_now()}\n".encode("utf-8"))
        except FileExistsError:
            try:
                stale_by_age = time.time() - path.stat().st_mtime > 120
            except OSError:
                stale_by_age = False
            owner_pid = _lock_owner_pid(path)
            abandoned = owner_pid is not None and not _process_is_running(owner_pid)
            if abandoned or owner_pid is None and stale_by_age:
                try:
                    path.unlink()
                except OSError:
                    pass
                else:
                    continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"UI cache is locked by another process: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            current = path.read_text(encoding="utf-8")
            if f"token={token}" in current:
                path.unlink()
        except OSError:
            pass


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
        "native": directory / NATIVE_RENDER_STATE_NAME,
        "lock": directory / STATE_LOCK_NAME,
        "gitignore": directory / ".gitignore",
    }


def default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        SETUP_KEY: {"completed": False, "answered": []},
        DETAIL_KEY: None,
        "autoSync": True,
        "cacheMode": "user",
        "compactContext": True,
        "maxContextScreens": 100,
        "maxContextComponents": 200,
        "handoffProvider": "generic",
        UI_MODE_KEY: {"enabled": False},
        MOCK_DATA_KEY: {"mode": "minimal", "seed": "stable", "explicit": False},
        PREVIEW_KEY: {"themeLayout": "auto", "defaultView": "overview", "language": "auto"},
        REVIEW_KEY: {"depth": "auto", "validation": "auto"},
    }


def config_hash(config: dict[str, Any]) -> str:
    scan_config = {key: value for key, value in config.items() if key not in {SETUP_KEY, DETAIL_KEY, UI_MODE_KEY, MOCK_DATA_KEY, PREVIEW_KEY, REVIEW_KEY}}
    payload = json.dumps(scan_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_config(value: Any) -> dict[str, Any]:
    config = default_config()
    if isinstance(value, dict):
        config.update(value)
    mode = config.get(UI_MODE_KEY)
    config[UI_MODE_KEY] = {"enabled": bool(mode.get("enabled", False))} if isinstance(mode, dict) else {"enabled": False}
    detail = config.get(DETAIL_KEY)
    config[DETAIL_KEY] = detail if detail in {"low", "medium", "high"} else None
    configured = config[DETAIL_KEY] in {"low", "medium", "high"}
    config[SETUP_KEY] = {"completed": configured, "answered": ["detail"] if configured else []}
    config[MOCK_DATA_KEY] = {
        "mode": MOCK_DATA_BY_DETAIL.get(config[DETAIL_KEY], "minimal"),
        "seed": "stable",
        "explicit": False,
    }
    preview = config.get(PREVIEW_KEY) if isinstance(config.get(PREVIEW_KEY), dict) else {}
    theme_layout = preview.get("themeLayout", "auto")
    default_view = preview.get("defaultView", "overview")
    language = preview.get("language", "auto")
    config[PREVIEW_KEY] = {
        "themeLayout": theme_layout if theme_layout in {"auto", "themes", "states", "matrix"} else "auto",
        "defaultView": default_view if default_view in {"overview", "single", "prototype", "states"} else "overview",
        "language": language if language in {"auto", "ru", "en"} else "auto",
    }
    review = config.get(REVIEW_KEY) if isinstance(config.get(REVIEW_KEY), dict) else {}
    depth = review.get("depth", "auto")
    validation = review.get("validation", "auto")
    config[REVIEW_KEY] = {
        "depth": depth if depth in {"auto", "standard", "deep"} else "auto",
        "validation": validation if validation in {"auto", "quick", "full"} else "auto",
    }
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


DETAIL_PROFILES: dict[str, dict[str, Any]] = {
    "low": {
        "label": "Low",
        "description": "Screens, basic layout, and minimal mock data.",
    },
    "medium": {
        "label": "Medium",
        "description": "Navigation, interactions, relevant states, and representative mock data.",
    },
    "high": {
        "label": "High",
        "description": "Everything in Medium, plus expanded mock data, detected themes, and exhaustive reconstruction/HTML checks.",
    },
}

SETTING_CATALOG: dict[str, dict[str, Any]] = {
    "detail": {
        "values": ["low", "medium", "high"],
        "description": "Low: basic layout and minimal data. Medium: interactions, states, and representative data. High: expanded data, themes, and exhaustive reconstruction/HTML checks. No level starts UI/UX review.",
    },
    "ui-mode": {"values": ["on", "off"], "description": "Apply platform-aware UI guidance to ordinary UI tasks without an explicit workbench request."},
    "theme-layout": {"values": ["auto", "themes", "states", "matrix"], "description": "Default organization for multi-theme and multi-state canvas variants."},
    "default-view": {"values": ["overview", "single", "prototype", "states"], "description": "Initial workbench view."},
    "language": {"values": ["auto", "ru", "en"], "description": "Workbench interface language."},
    "review-depth": {"values": ["auto", "standard", "deep"], "description": "Default expert review breadth; auto follows the detail profile."},
    "validation": {"values": ["auto", "quick", "full"], "description": "Default deterministic validation level; auto uses full for high detail."},
    "auto-sync": {"values": ["on", "off"], "description": "Refresh the UI index only when relevant source fingerprints change."},
    "cache-mode": {"values": ["user", "project"], "description": "Store derived state in the OS cache or an ignored project directory."},
}


def effective_review_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get(REVIEW_KEY, {})
    high = config.get(DETAIL_KEY) == "high"
    depth = raw.get("depth", "auto")
    validation = raw.get("validation", "auto")
    return {
        "depth": "deep" if depth == "auto" and high else "standard" if depth == "auto" else depth,
        "validation": "full" if validation == "auto" and high else "quick" if validation == "auto" else validation,
    }


def effective_preview_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get(PREVIEW_KEY, {})
    theme_layout = raw.get("themeLayout", "auto")
    return {
        "themeLayout": ("matrix" if config.get(DETAIL_KEY) == "high" else "states") if theme_layout == "auto" else theme_layout,
        "defaultView": raw.get("defaultView", "overview"),
        "language": raw.get("language", "auto"),
    }


def configuration_context(config: dict[str, Any]) -> dict[str, Any]:
    completed = config.get(DETAIL_KEY) in DETAIL_PROFILES
    questions = [] if completed else [
        {
            "key": "detail",
            "question": "Выберите детализацию: Low — базовая разметка и минимум данных; Medium — взаимодействия, состояния и репрезентативные данные; High — расширенные данные, темы и полная проверка реконструкции/HTML. UI/UX-ревью ни один уровень не запускает.",
        },
    ]
    detail = config.get(DETAIL_KEY)
    return {
        "status": "configured" if completed else "needs-setup",
        "setupRequired": not completed,
        "detailLevel": detail,
        "detailProfile": DETAIL_PROFILES.get(detail),
        UI_MODE_KEY: config.get(UI_MODE_KEY),
        MOCK_DATA_KEY: mock_data_context(config),
        PREVIEW_KEY: {**config.get(PREVIEW_KEY, {}), "effective": effective_preview_config(config)},
        REVIEW_KEY: {**config.get(REVIEW_KEY, {}), "effective": effective_review_config(config)},
        "autoSync": bool(config.get("autoSync", True)),
        "cacheMode": config.get("cacheMode", "user"),
        "questionsForUser": questions,
        "changeCommand": "uidw --repo <repo> config set <setting> <value>",
    }


def parse_on_off(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "yes", "1", "enable", "enabled"}:
        return True
    if normalized in {"off", "false", "no", "0", "disable", "disabled"}:
        return False
    raise ValueError(f"Expected on/off, got: {value}")


def set_config_value(config: dict[str, Any], key: str, value: str) -> None:
    key = key.strip().lower()
    if key not in SETTING_CATALOG:
        raise ValueError(f"Unknown setting: {key}. Run `uidw help config`.")
    allowed = SETTING_CATALOG[key]["values"]
    if allowed != ["<text>"] and value not in allowed:
        raise ValueError(f"Invalid {key}: {value}. Expected: {', '.join(allowed)}")
    if key == "detail":
        config[DETAIL_KEY] = value
        config[MOCK_DATA_KEY] = {
            "mode": MOCK_DATA_BY_DETAIL[value],
            "seed": "stable",
            "explicit": False,
        }
    elif key == "ui-mode":
        config[UI_MODE_KEY] = {"enabled": parse_on_off(value)}
    elif key in {"theme-layout", "default-view", "language"}:
        field = {"theme-layout": "themeLayout", "default-view": "defaultView", "language": "language"}[key]
        config[PREVIEW_KEY] = {**config.get(PREVIEW_KEY, {}), field: value}
    elif key in {"review-depth", "validation"}:
        field = "depth" if key == "review-depth" else "validation"
        config[REVIEW_KEY] = {**config.get(REVIEW_KEY, {}), field: value}
    elif key == "auto-sync":
        config["autoSync"] = parse_on_off(value)
    elif key == "cache-mode":
        config["cacheMode"] = value
    configured = config.get(DETAIL_KEY) in DETAIL_PROFILES
    config[SETUP_KEY] = {"completed": configured, "answered": ["detail"] if configured else []}


def configure_project(root: Path, action: str, key: str | None = None, value: str | None = None) -> dict[str, Any]:
    paths = state_paths(root)
    config = load_config(paths["config"])
    if action == "reset":
        config = default_config()
    elif action == "set":
        if not key or value is None:
            raise ValueError("Usage: uidw config set <setting> <value>")
        set_config_value(config, key, value)
    elif action not in {"show", "setup"}:
        raise ValueError(f"Unknown config action: {action}")
    if action in {"set", "reset"}:
        destination = root / STATE_DIR_NAME / CONFIG_NAME if config.get("cacheMode") == "project" else paths["config"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, normalized_config(config))
        ensure_initialized(root, synchronize=True)
        paths = state_paths(root)
        config = load_config(paths["config"])
    return {
        "version": 1,
        "status": configuration_context(config)["status"],
        "repoRoot": str(root),
        "configuration": configuration_context(config),
        "catalog": SETTING_CATALOG,
        "configFile": str(paths["config"]),
        "contextFile": str(paths["context"]),
    }


def help_topic(topic: str | None = None) -> dict[str, Any]:
    selected = topic or "overview"
    topics = {
        "overview": "Для сборки макета используйте `uidw workbench`: он проверяет только точность переноса и работу HTML. `uidw review` запускайте отдельно только по явному запросу на UI/UX-аудит. Ручной `init` не нужен: первый запуск автоматически создаст UI-кеш, последующие переиспользуют его. Для диагностики установки используйте `uidw doctor`.",
        "config": "Первичная настройка спрашивает только детализацию: Low — базовая разметка и минимум данных; Medium — взаимодействия, состояния и репрезентативные данные; High — расширенные данные, темы и полная проверка реконструкции/HTML. Ни один уровень не включает UI/UX-аудит. Команды: `uidw config setup`, `uidw config show`, `uidw config set detail <low|medium|high>`.",
        "themes": "В workbench попадают только темы, подтверждённые исходниками. Варианты группируются по темам, состояниям или раздельной матрице.",
        "review": "`uidw review` — единственная команда, которая явно запускает UI/UX-аудит и его три шага: Проверка → Проблемы → Исправление. `uidw review prepare` создаёт только задание для внешнего AI-ревью, а `uidw review import <result.json>` импортирует его результат.",
        "workbench": "`uidw workbench --output-dir <dir>` собирает HTML и проверяет только точность переноса, варианты, ссылки переходов и механику workbench. Он не оценивает UI/UX и не создаёт проблемы.",
        "apply": "`uidw apply` работает только после выбора проблем, подготовки и подтверждения нового макета. `uidw apply --direct` — отдельный явный путь без предварительного макета.",
        "advanced": "Расширенные команды: context, map, render, validate, workbench, diff, scenarios, findings, proposal, pack, unpack, visual-test и fidelity. `uidw fidelity capabilities` показывает установленные платформенные адаптеры и их ограничения. Используйте `<команда> --help` для точных параметров.",
    }
    if selected not in topics:
        raise ValueError(f"Неизвестный раздел справки: {selected}. Доступно: {', '.join(topics)}")
    return {"version": 1, "status": "ok", "topic": selected, "text": topics[selected], "topics": sorted(topics), "settings": SETTING_CATALOG if selected == "config" else None}


def about() -> dict[str, Any]:
    return {
        "version": 1,
        "status": "ok",
        "name": "UI Design Workbench",
        "cliVersion": CLI_VERSION,
        "description": "Provider-neutral CLI for reconstructing, reviewing, redesigning, and validating repository UI as standalone interactive HTML without running the application.",
        "runtime": "No server, emulator, or application runtime required.",
    }


def mock_data_context(config: dict[str, Any]) -> dict[str, Any]:
    detail = config.get(DETAIL_KEY)
    mode = MOCK_DATA_BY_DETAIL.get(detail, "minimal")
    instructions = {
        "minimal": (
            "Create the smallest deterministic, non-sensitive data set that makes every visible data-bound view readable. "
            "Use one value per scalar field and two compact synthetic items per list, table, grid, or collection. "
            "Do not generate alternate scenarios at this level."
        ),
        "representative": (
            "Create deterministic, non-sensitive, platform-appropriate representative data for the main user flow. "
            "Populate collections with several varied synthetic items and add only task-critical alternate states supported "
            "by source branches. Do not stamp the same loading/error/success set onto every screen."
        ),
        "exhaustive": (
            "Create deterministic, non-sensitive, platform-appropriate expanded data that exercises density, scrolling, "
            "long values, and source-evidenced boundary states. Keep variants screen-specific; never invent a universal "
            "loading/error/success trio."
        ),
    }
    result: dict[str, Any] = {
        "enabled": True,
        "mode": mode,
        "source": "detailLevel",
        "seed": "stable",
        "instruction": instructions[mode] + " Represent collections with repeated synthetic item nodes; one summary text line is not a populated collection.",
    }
    return result


def fidelity_command(ir: dict[str, Any], action: str, identifier: str | None = None, output: Path | None = None, output_format: str = "json") -> dict[str, Any]:
    if action == "capabilities":
        adapters = adapter_capabilities()
        catalog_errors = validate_component_catalog()
        return {
            "version": 1,
            "status": "pass" if not catalog_errors else "fail",
            "adapterCount": len(adapters),
            "adapters": adapters,
            "componentCatalog": catalog_summary(),
            "componentCatalogErrors": catalog_errors,
        }
    if action == "report":
        report = fidelity_report(ir)
        if output:
            output = output.resolve()
            if output_format == "markdown":
                coverage = report["propertyProvenance"]
                lines = [
                    "# Fidelity report", "", f"Status: **{report['status']}**", "",
                    f"Property provenance: {coverage['covered']}/{coverage['total']} ({coverage['percent']}%)", "",
                    "## Strict errors", "",
                ]
                lines.extend(f"- {item}" for item in report["strictErrors"] or ["None"])
                write_text_atomic(output, "\n".join(lines) + "\n")
            else:
                write_json(output, report)
            report["reportFile"] = str(output)
        return report
    if not identifier:
        raise ValueError("fidelity explain requires a node or evidence id")
    nodes = ir.get("nodes", {})
    if identifier in nodes:
        node = nodes[identifier]
        return {"version": 1, "status": "pass", "nodeId": identifier, "source": node.get("source", {}), "confidence": node.get("confidence"), "properties": node.get("provenance", {})}
    for node_id, node in nodes.items():
        for path, evidence in node.get("provenance", {}).items() if isinstance(node.get("provenance"), dict) else ():
            if isinstance(evidence, dict) and evidence.get("id") == identifier:
                return {"version": 1, "status": "pass", "evidenceId": identifier, "nodeId": node_id, "property": path, "evidence": evidence}
    raise ValueError(f"Unknown node or evidence id: {identifier}")


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


def ui_reference_paths(scan: dict[str, Any] | None, ir: dict[str, Any] | None) -> set[str]:
    """Collect source and asset paths that currently participate in the rendered UI graph."""
    result: set[str] = set()
    scan = scan if isinstance(scan, dict) else {}
    ir = ir if isinstance(ir, dict) else {}
    for item in scan.get("uiFiles", []):
        if isinstance(item, dict) and item.get("path"):
            result.add(str(item["path"]))
    for item in (*scan.get("screens", []), *scan.get("routes", []), *scan.get("navigationTargets", []), *scan.get("components", [])):
        if not isinstance(item, dict):
            continue
        source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
        path = item.get("file") or source.get("file")
        if path:
            result.add(str(path))
    result.update(str(path) for path in scan.get("tokenFiles", []) if path)
    for screen in ir.get("screens", []):
        if isinstance(screen, dict) and screen.get("source", {}).get("file"):
            result.add(str(screen["source"]["file"]))
    for node in ir.get("nodes", {}).values():
        if not isinstance(node, dict):
            continue
        if node.get("source", {}).get("file"):
            result.add(str(node["source"]["file"]))
        asset = node.get("asset")
        if isinstance(asset, str):
            result.add(asset)
        elif isinstance(asset, dict):
            for key in ("path", "file", "src"):
                if asset.get(key):
                    result.add(str(asset[key]))
    return result


def classify_ui_changes(
    root: Path,
    diff: dict[str, list[str]],
    previous_records: dict[str, Any],
    scan: dict[str, Any] | None,
    ir: dict[str, Any] | None,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Separate repository source changes from changes that can affect the current UI target."""
    references = ui_reference_paths(scan, ir)
    updates: dict[str, Any] = {}

    def relevant(path: str, current: dict[str, Any] | None, previous: dict[str, Any] | None) -> bool:
        records = [record for record in (current, previous) if isinstance(record, dict)]
        return path in references or any(isinstance(record.get("uiFile"), dict) for record in records)

    classified = {key: [] for key in ("added", "modified", "removed", "metadataOnly")}
    for key in ("added", "modified"):
        for relative in diff[key]:
            record = analyze_file(root, root / Path(relative))
            if record is not None:
                updates[relative] = record
            previous = previous_records.get(relative) if isinstance(previous_records.get(relative), dict) else None
            if relevant(relative, record, previous):
                classified[key].append(relative)
    for relative in diff["removed"]:
        previous = previous_records.get(relative) if isinstance(previous_records.get(relative), dict) else None
        if relevant(relative, None, previous):
            classified["removed"].append(relative)
    for relative in diff["metadataOnly"]:
        previous = previous_records.get(relative) if isinstance(previous_records.get(relative), dict) else None
        if relevant(relative, previous, previous):
            classified["metadataOnly"].append(relative)
    return classified, updates


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
        path = str(token.get("path") or "") if isinstance(token, dict) else str(token or "")
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
        return {"version": 1, "screens": {}, "nodes": {}, "scenarioFixtures": {}, "themes": {}, "tokens": {}}
    return {
        "version": 1,
        "screens": {
            str(item["id"]): copy.deepcopy(item)
            for item in ir.get("screens", [])
            if isinstance(item, dict) and item.get("id")
        },
        "nodes": copy.deepcopy(ir.get("nodes", {})) if isinstance(ir.get("nodes"), dict) else {},
        "scenarioFixtures": copy.deepcopy(ir.get("scenarioFixtures", {})) if isinstance(ir.get("scenarioFixtures"), dict) else {},
        "themes": copy.deepcopy(ir.get("themes", {})) if isinstance(ir.get("themes"), dict) else {},
        "tokens": copy.deepcopy(ir.get("tokens", {})) if isinstance(ir.get("tokens"), dict) else {},
        "savedAt": utc_now(),
    }


def extract_review_state(ir: dict[str, Any] | None) -> dict[str, Any]:
    review = copy.deepcopy(ir.get("review", {})) if isinstance(ir, dict) and isinstance(ir.get("review"), dict) else {}
    return {"version": 1, "review": review, "savedAt": utc_now()}


_MISSING_TOKEN = object()


def deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def prune_missing_token_refs(value: Any, tokens: dict[str, Any]) -> Any:
    """Drop authored values whose token path no longer exists after cache migration."""

    if isinstance(value, str) and value.startswith("$"):
        resolved: Any = tokens
        for part in value[1:].split("."):
            if not isinstance(resolved, dict) or part not in resolved:
                return _MISSING_TOKEN
            resolved = resolved[part]
        return value
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned = prune_missing_token_refs(item, tokens)
            if cleaned is not _MISSING_TOKEN:
                result[key] = cleaned
        return result
    if isinstance(value, list):
        items = [prune_missing_token_refs(item, tokens) for item in value]
        return [item for item in items if item is not _MISSING_TOKEN]
    return copy.deepcopy(value)


def prune_orphan_provenance(node: dict[str, Any]) -> dict[str, Any]:
    """Remove evidence entries for authored properties pruned during cache migration."""
    provenance = node.get("provenance")
    if not isinstance(provenance, dict):
        return node

    def path_exists(path: str) -> bool:
        current: Any = node
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True

    node["provenance"] = {path: evidence for path, evidence in provenance.items() if path_exists(str(path))}
    return node


def merge_authored_state(
    generated: dict[str, Any],
    design_model: dict[str, Any],
    review_state: dict[str, Any],
    impacted_screen_ids: list[str],
) -> dict[str, Any]:
    """Overlay durable authored detail while marking changed source bindings as stale."""
    result = copy.deepcopy(generated)
    impacted = set(impacted_screen_ids)
    generated_tokens = result.get("tokens", {}) if isinstance(result.get("tokens"), dict) else {}
    authored_tokens = design_model.get("tokens", {}) if isinstance(design_model.get("tokens"), dict) else {}
    merged_tokens = deep_merge_dict(generated_tokens, authored_tokens)
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
        cleaned_authored = prune_missing_token_refs(authored, merged_tokens)
        if not isinstance(cleaned_authored, dict):
            continue
        prune_orphan_provenance(cleaned_authored)
        existing = result.setdefault("nodes", {}).get(node_id, {})
        merged = copy.deepcopy(existing)
        for key, value in cleaned_authored.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = copy.deepcopy(value)
        if owners.intersection(impacted):
            merged["sourceState"] = "stale"
        else:
            merged.pop("sourceState", None)
        prune_orphan_provenance(merged)
        result["nodes"][node_id] = merged

    fixtures = design_model.get("scenarioFixtures", {})
    if isinstance(fixtures, dict) and fixtures:
        result["scenarioFixtures"] = copy.deepcopy(fixtures)

    if merged_tokens:
        result["tokens"] = merged_tokens

    generated_themes = result.get("themes", {}) if isinstance(result.get("themes"), dict) else {}
    authored_themes = design_model.get("themes", {}) if isinstance(design_model.get("themes"), dict) else {}
    generated_items = generated_themes.get("items", []) if isinstance(generated_themes.get("items"), list) else []
    authored_items = {
        str(item.get("id")): item
        for item in authored_themes.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    merged_theme_items: list[dict[str, Any]] = []
    for generated_theme in generated_items:
        if not isinstance(generated_theme, dict) or not generated_theme.get("id"):
            continue
        theme_id = str(generated_theme["id"])
        merged_theme = copy.deepcopy(generated_theme)
        authored_theme = authored_items.get(theme_id)
        if isinstance(authored_theme, dict):
            generated_refs = copy.deepcopy(merged_theme.get("sourceRefs", []))
            merged_theme.update(copy.deepcopy(authored_theme))
            if generated_refs:
                merged_theme["sourceRefs"] = generated_refs
        merged_theme_items.append(merged_theme)
    if merged_theme_items:
        requested_default = authored_themes.get("defaultThemeId")
        known_theme_ids = {str(item.get("id")) for item in merged_theme_items}
        generated_themes["items"] = merged_theme_items
        generated_themes["defaultThemeId"] = requested_default if requested_default in known_theme_ids else generated_themes.get("defaultThemeId", "light")
        result["themes"] = generated_themes

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
    seal_baseline(result)
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
        "repoRoot": "<project-root>",
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
        "themes": inventory.get("themes", []),
        "components": inventory.get("components", [])[:max_components],
        "warnings": inventory.get("warnings", []),
        "configuration": configuration_context(config),
        UI_MODE_KEY: ui_mode_context(config, inventory.get("detectedPlatforms", [])),
        MOCK_DATA_KEY: mock_data_context(config),
        "instructions": "Read prioritySourceFiles only when cacheStatus is stale or the requested screen is not fully represented in ui-ir.json.",
    }


def inspect_cache(root: Path, verify_content: bool = False, include_internal: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], dict[str, Any]]:
    paths = state_paths(root)
    config = load_config(paths["config"])
    cache = read_json(paths["cache"], {})
    if not isinstance(cache, dict):
        cache = {}
    previous_manifest = cache.get("manifest", {}) if isinstance(cache.get("manifest"), dict) else {}
    current_manifest = build_manifest(root, previous_manifest, verify_content)
    source_diff = manifest_diff(previous_manifest, current_manifest)
    previous_records = cache.get("fileRecords", {}) if isinstance(cache.get("fileRecords"), dict) else {}
    old_scan = read_json(paths["scan"], {}) if paths["scan"].is_file() else {}
    old_ir = load_project_ir(paths)
    diff, record_updates = classify_ui_changes(root, source_diff, previous_records, old_scan, old_ir)
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
        "sourceChanges": source_diff,
        "changedUiFiles": changed_paths(diff),
        "cacheFile": str(paths["cache"]),
        "configFile": str(paths["config"]),
        "scanFile": str(paths["scan"]),
        "irFile": str(paths["ir"]),
        "graphFile": str(paths["graph"]),
        "configuration": configuration_context(config),
        UI_MODE_KEY: ui_mode_context(config),
        MOCK_DATA_KEY: mock_data_context(config),
    }
    if include_internal:
        result["_recordUpdates"] = record_updates
    return result, current_manifest, paths, config


def sync_project(root: Path, force: bool = False, verify_content: bool = False) -> dict[str, Any]:
    initial_paths = state_paths(root)
    with state_lock(initial_paths["lock"]):
        status, current_manifest, paths, config = inspect_cache(root, verify_content, include_internal=True)
        record_updates = status.pop("_recordUpdates", {})
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
            if any(status.get("sourceChanges", {}).values()) and cache:
                cache["manifest"] = current_manifest
                file_records = dict(cache.get("fileRecords", {})) if isinstance(cache.get("fileRecords"), dict) else {}
                for relative in status["sourceChanges"]["removed"]:
                    file_records.pop(relative, None)
                file_records.update(record_updates)
                cache["fileRecords"] = file_records
                write_json(paths["cache"], cache)
            report = {**status, "syncedAt": cache.get("syncedAt"), "impactedScreenIds": []}
        else:
            previous_records = cache.get("fileRecords", {}) if isinstance(cache.get("fileRecords"), dict) else {}
            if invalidate_all or not previous_records:
                file_records: dict[str, Any] = {}
                for relative in current_manifest:
                    record = record_updates.get(relative)
                    if record is None:
                        record = analyze_file(root, root / Path(relative))
                    if record is not None:
                        file_records[relative] = record
            else:
                file_records = dict(previous_records)
                for relative in status["changes"]["removed"]:
                    file_records.pop(relative, None)
                for relative in status["changes"]["added"] + status["changes"]["modified"]:
                    record = record_updates.get(relative)
                    if record is None:
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


def ensure_initialized(
    root: Path,
    force: bool = False,
    verify_content: bool = False,
    synchronize: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Path], dict[str, Any]]:
    """Create or reuse the project UI cache through one observable bootstrap path."""

    paths = state_paths(root)
    required_keys = ("cache", "scan", "graph", "ir")
    cache_ready_before = all(paths[key].is_file() for key in required_keys)
    config_created = not paths["config"].is_file()
    if config_created:
        paths["config"].parent.mkdir(parents=True, exist_ok=True)
        write_json(paths["config"], normalized_config(default_config()))
        paths = state_paths(root)

    config = load_config(paths["config"])
    should_sync = force or synchronize is True or (synchronize is None and bool(config.get("autoSync", True)))
    if should_sync:
        result = sync_project(root, force=force, verify_content=verify_content)
    else:
        result, _, paths, config = inspect_cache(root, verify_content)
    paths = state_paths(root)
    config = load_config(paths["config"])
    cache_ready_after = all(paths[key].is_file() for key in required_keys)

    if not cache_ready_before and cache_ready_after:
        bootstrap_status = "created"
        message = "Инициализация: кеш проекта создан."
    elif should_sync and result.get("status") == "synced":
        bootstrap_status = "updated"
        message = "Инициализация: существующий UI-кеш обновлён."
    elif cache_ready_after and result.get("status") == "clean":
        bootstrap_status = "reused"
        message = "Инициализация: используется существующий UI-кеш."
    else:
        bootstrap_status = "stale"
        message = "Инициализация: UI-кеш требует обновления, но автоматическая синхронизация отключена."

    initialization = {
        "status": bootstrap_status,
        "firstRun": not cache_ready_before,
        "configCreated": config_created,
        "cacheCreated": bootstrap_status == "created",
        "cacheReused": bootstrap_status == "reused",
        "synchronizationChecked": should_sync,
        "synchronized": result.get("status") == "synced",
        "sourceAnalysisRun": result.get("status") == "synced",
        "cacheDir": str(paths["dir"]),
        "message": message,
    }
    inventory = read_json(paths["scan"], {})
    detected_platforms = inventory.get("detectedPlatforms", []) if isinstance(inventory, dict) else []
    result = {
        **result,
        "initialization": initialization,
        "configuration": configuration_context(config),
        UI_MODE_KEY: ui_mode_context(config, detected_platforms),
        MOCK_DATA_KEY: mock_data_context(config),
    }
    context = read_json(paths["context"], {})
    if isinstance(context, dict) and context:
        context["initialization"] = initialization
        write_json(paths["context"], context)
    return result, paths, config


def initialize(
    root: Path,
    force: bool = False,
    project_cache: bool = False,
    ui_mode: bool = False,
    detail_level: str | None = None,
    setup_completed: bool = False,
) -> dict[str, Any]:
    if project_cache:
        config_path = root / STATE_DIR_NAME / CONFIG_NAME
        config = load_config(config_path)
        config["cacheMode"] = "project"
    else:
        initial_paths = state_paths(root)
        config_path = initial_paths["config"]
        config = load_config(config_path)
    config[UI_MODE_KEY] = {"enabled": bool(ui_mode)}
    config[DETAIL_KEY] = detail_level if detail_level in DETAIL_PROFILES else None
    config[MOCK_DATA_KEY] = {
        "mode": MOCK_DATA_BY_DETAIL.get(config[DETAIL_KEY], "minimal"),
        "seed": "stable",
        "explicit": False,
    }
    config[SETUP_KEY] = {
        "completed": bool(setup_completed and config[DETAIL_KEY]),
        "answered": ["detail"] if setup_completed else [],
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(config_path, config)
    paths = state_paths(root)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    if project_cache and not paths["gitignore"].exists():
        paths["gitignore"].write_text(STATE_GITIGNORE, encoding="utf-8")
    result, paths, config = ensure_initialized(root, force=force, synchronize=True)
    return {
        **result,
        "configuration": configuration_context(config),
        UI_MODE_KEY: ui_mode_context(config, read_json(paths["scan"], {}).get("detectedPlatforms", [])),
        MOCK_DATA_KEY: mock_data_context(config),
    }


def configure_ui_mode(root: Path, enabled: bool | None = None) -> dict[str, Any]:
    paths = state_paths(root)
    config = load_config(paths["config"])
    if enabled is not None:
        config[UI_MODE_KEY] = {"enabled": enabled}
        paths["config"].parent.mkdir(parents=True, exist_ok=True)
        write_json(paths["config"], normalized_config(config))
        ensure_initialized(root, synchronize=True)
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
        "mcp": {
            "available": importlib.util.find_spec("mcp") is not None,
            "transport": "stdio",
            "command": f'uidw-mcp --repo "{root}"',
            "requiredForCli": False,
        },
        "cache": status,
        "stateDir": str(paths["dir"]),
        "stateFiles": {"sourceIndex": str(paths["scan"]), "designModel": str(paths["design"]), "reviewState": str(paths["review"])},
        "cliVersion": CLI_VERSION,
        "configVersion": CONFIG_VERSION,
        "configuration": configuration_context(config),
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
    scoped = build_scoped_context(
        ir,
        screen_ids=[str(screen.get("id"))],
        token_budget=1_000_000,
        ui_ir_file=str(paths["ir"]),
        provenance_mode="summary",
        strict_budget=False,
    )
    selected_nodes = scoped.get("nodes", {})
    component_refs = sorted({
        str(item.get("componentRef"))
        for item in selected_nodes.values()
        if item.get("componentRef")
    })
    payload = {
        "version": 1,
        "repoRoot": "<project-root>",
        "cacheStatus": base.get("cacheStatus"),
        "screen": screen,
        "nodes": selected_nodes,
        "sourceFiles": scoped.get("sourceFiles", []),
        "componentRefs": component_refs,
        "platforms": ir.get("platforms", []),
        "design": ir.get("design", {}),
        "tokens": scoped.get("tokens", {}),
        "themes": scoped.get("themes", {}),
        "evidence": scoped.get("evidence", {}),
        "scopeHash": scoped.get("scopeHash"),
        "warnings": base.get("warnings", []),
        "configuration": base.get("configuration", configuration_context(load_config(paths["config"]))),
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

    initial_size = size()
    if result.get("screen") and initial_size > limit:
        screen = result.get("screen", {}) if isinstance(result.get("screen"), dict) else {}
        response = {
            "version": 1,
            "status": "over-budget",
            "screen": {key: screen.get(key) for key in ("id", "name", "platform") if screen.get(key) is not None},
            "scopeHash": result.get("scopeHash"),
            "sourceFileCount": len(result.get("sourceFiles", [])),
            "evidence": result.get("evidence", {}),
            "next": "Use uidw scope with a narrower selection or a larger explicit budget; no partial node tree was returned.",
            "contextBudget": {
                "requestedTokens": max(256, token_budget),
                "estimatedTokens": max(1, (initial_size + 3) // 4),
                "withinBudget": False,
                "structuralTruncation": False,
                "truncated": False,
            },
        }
        response["contextBudget"]["returnedTokens"] = max(1, (len(json.dumps(response, ensure_ascii=False, separators=(",", ":"))) + 3) // 4)
        return response

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
        "truncated": size() > limit or size() < initial_size,
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


def finding_verified(item: dict[str, Any]) -> bool:
    verification = item.get("verification", {}) if isinstance(item.get("verification"), dict) else {}
    return (
        verification.get("result") == "pass"
        or verification.get("status") == "verified"
        or bool(item.get("verifiedAt"))
    )


def finding_proposals(ir: dict[str, Any], finding_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for version in ir.get("review", {}).get("versions", []):
        if not isinstance(version, dict) or version.get("kind") != "proposal":
            continue
        covered = set(version.get("resolvedFindingIds", [])) | set(version.get("findingIds", []))
        if finding_id in covered:
            proposals.append(version)
    return proposals


def finding_lifecycle_state(ir: dict[str, Any], item: dict[str, Any], decision: str = "pending") -> str:
    """Return the same evidence-based lifecycle state used by the workbench UI."""
    if finding_verified(item):
        return "verified"
    implementation = item.get("implementation", {}) if isinstance(item.get("implementation"), dict) else {}
    if item.get("appliedAt") or implementation.get("status") in {"applied", "implemented"}:
        return "applied"
    proposals = finding_proposals(ir, str(item.get("id") or ""))
    if proposals:
        review_decision = str(ir.get("review", {}).get("versionDecision") or "")
        if review_decision == "accepted" or any(str(version.get("status")) in {"accepted", "approved"} for version in proposals):
            return "approved"
        return "addressed"
    if decision == "accepted":
        return "selected"
    if decision in {"rejected", "deferred"}:
        return decision
    return "pending"


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
        state = finding_lifecycle_state(ir, item, decision)
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
            "legacyStatus": item.get("status") if item.get("status") == "resolved" else None,
            "title": item.get("title", "Untitled finding"),
            "sourceState": item.get("sourceState", "current"),
        })
    return {"version": 1, "status": "ok", "total": len(findings), "shown": len(rows), "screen": screen, "findings": rows}


def update_finding_decisions(ir: dict[str, Any], identifiers: list[str], decision: str) -> dict[str, Any]:
    if decision == "resolved":
        raise ValueError("A finding can be verified only by importing a passing targeted verification result")
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
        if decision == "pending":
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
    direct: bool = False,
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
        raise ValueError("No findings selected. Open step 2 in `uidw review` and select the issues to continue")
    source_change_allowed = kind == "implementation"
    if source_change_allowed and not direct:
        uncovered = [item["id"] for item in selected if not finding_proposals(ir, str(item["id"])) and not finding_verified(item)]
        approved = str(ir.get("review", {}).get("versionDecision") or "") == "accepted"
        approved = approved or all(
            finding_verified(item)
            or any(str(version.get("status")) in {"accepted", "approved"} for version in finding_proposals(ir, str(item["id"])))
            for item in selected
        )
        if uncovered:
            raise ValueError("A new mockup is required before applying these findings: " + ", ".join(uncovered))
        if not approved:
            raise ValueError("Approve the new mockup in step 3 before applying it, or use `uidw apply --direct` for the explicit no-preview path")
    source_targets = source_targets_for_findings(root, selected)
    if source_change_allowed and not source_targets:
        raise ValueError("Selected findings have no verified source targets inside the repository")
    screen_ids = sorted({str(item.get("screenId")) for item in selected if item.get("screenId")})
    if not selected and scope == "current":
        screen_ids = [str(item.get("id")) for item in ir.get("screens", [])[:1] if item.get("id")]
    context_file = output.resolve().parent / "ui-agent-context.json"
    patch_file = output.resolve().parent / "ui-ir.patch.json"
    scoped = build_scoped_context(
        ir,
        screen_ids=screen_ids,
        finding_ids=selected_ids,
        token_budget=5000 if selected_ids else 4000,
        ui_ir_file=str(ir_path.resolve()),
    )
    if scoped.get("status") == "over-budget":
        return {
            "version": 1,
            "status": "blocked",
            "kind": kind,
            "reason": "context-over-budget",
            "contextBudget": scoped.get("contextBudget", {}),
            "scopeHash": scoped.get("scopeHash"),
            "next": scoped.get("next"),
        }
    write_scoped_json(context_file, scoped)
    write_scoped_json(patch_file, patch_template(ir, str(ir_path.resolve()), str(context_file)))
    allowed_writes = source_targets if source_change_allowed else ["ui-ir.patch.json", "ui-ir.proposed.json", "ui-preview.html", "*.report.json"]
    config = load_config(state_paths(root)["config"])
    preview_config = effective_preview_config(config)
    review_config = effective_review_config(config)
    job = {
        "type": "ui-design-workbench-agent-job",
        "version": 3,
        "provider": provider,
        "kind": kind,
        "project": ir.get("project", {}).get("name", root.name),
        "projectRoot": str(root.resolve()),
        "artifactDir": str(ir_path.resolve().parent),
        "uiIrFile": str(ir_path.resolve()),
        "contextFile": str(context_file),
        "patchFile": str(patch_file),
        "contextBudget": scoped.get("contextBudget", {}),
        "scope": scope,
        "screenIds": screen_ids,
        "acceptedFindingIds": selected_ids,
        "sourceTargets": source_targets,
        "allowedWrites": allowed_writes,
        "sourceChangeAllowed": source_change_allowed,
        "directSourceAuthorization": bool(source_change_allowed and direct),
        "configuration": {
            "detailLevel": config.get(DETAIL_KEY),
            "validation": review_config.get("validation"),
            "defaultView": preview_config.get("defaultView"),
            "uiModeEnabled": bool(config.get(UI_MODE_KEY, {}).get("enabled")),
        },
        "requiredChatReport": ["number", "findingId", "screen", "problem", "implementedFix", "changedFiles", "verification", "remainingReason"],
        "requestedAction": {
            "expert": "Read only contextFile. Review its catalog in small screen scopes, then write findings and sparse proposal versions as operations in patchFile. Never load the complete UI IR into the prompt.",
            "proposal": "Read only contextFile. Create sparse proposal operations in patchFile for the selected findings without changing project source.",
            "implementation": "Implement the selected findings in the verified project source targets, run incremental uidw sync and targeted verification, and do not repeat the full AI review.",
        }[kind],
        "createdAt": utc_now(),
    }
    write_json(output.resolve(), job)
    return {
        "version": 1,
        "status": "prepared",
        "kind": kind,
        "jobFile": str(output.resolve()),
        "contextFile": str(context_file),
        "patchFile": str(patch_file),
        "contextTokens": scoped.get("contextBudget", {}).get("estimatedTokens"),
        "findingIds": selected_ids,
        "sourceTargets": source_targets,
    }


def import_review_result(ir_path: Path, result_path: Path, output: Path) -> dict[str, Any]:
    from merge_review_state import merge, validate_feedback

    ir = read_json(ir_path)
    payload = read_json(result_path)
    if not isinstance(ir, dict) or not isinstance(payload, dict):
        raise ValueError("IR or review result is not valid JSON")
    result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    incoming_ir = payload.get("uiIr") or result.get("uiIr")
    if isinstance(incoming_ir, dict):
        if incoming_ir.get("project", {}).get("name") != ir.get("project", {}).get("name"):
            raise ValueError("Review result belongs to another project")
        request_revision = payload.get("requestRevision") or result.get("requestRevision")
        review = ir.get("review", {}) if isinstance(ir.get("review"), dict) else {}
        incoming_review = incoming_ir.get("review", {}) if isinstance(incoming_ir.get("review"), dict) else {}
        if request_revision and review.get("revision") and request_revision != review.get("revision"):
            raise ValueError("Review result belongs to another revision")
        if incoming_review.get("baselineHash") and incoming_review.get("baselineHash") != review.get("baselineHash"):
            raise ValueError("Review result baselineHash does not match the immutable baseline")
        if incoming_review.get("baselineVersion") and incoming_review.get("baselineVersion") != review.get("baselineVersion"):
            raise ValueError("Review result baselineVersion does not match the immutable baseline")
        if incoming_ir.get("screens") is not None and incoming_ir.get("screens") != ir.get("screens"):
            raise ValueError("Review result cannot replace immutable baseline screens")
        merged = copy.deepcopy(ir)
        merged_nodes = merged.setdefault("nodes", {})
        incoming_nodes = incoming_ir.get("nodes", {})
        if not isinstance(incoming_nodes, dict):
            raise ValueError("Review result nodes must be an object")
        for node_id, node in incoming_nodes.items():
            if node_id in merged_nodes and merged_nodes[node_id] != node:
                raise ValueError(f"Review result cannot replace immutable baseline node: {node_id}")
            if node_id not in merged_nodes:
                merged_nodes[node_id] = copy.deepcopy(node)

        merged_review = merged.setdefault("review", {})
        incoming_versions = payload.get("versions") or result.get("versions") or incoming_review.get("versions", [])
        versions_by_id = {
            item.get("id"): copy.deepcopy(item)
            for item in merged_review.get("versions", [])
            if isinstance(item, dict) and item.get("id")
        }
        baseline_version = merged_review.get("baselineVersion")
        imported_version_ids: list[str] = []
        for version in incoming_versions if isinstance(incoming_versions, list) else []:
            if not isinstance(version, dict) or not version.get("id"):
                continue
            version_id = str(version["id"])
            if version_id == baseline_version and version_id in versions_by_id and versions_by_id[version_id] != version:
                raise ValueError("Review result cannot replace the immutable baseline version")
            if version_id != baseline_version:
                versions_by_id[version_id] = copy.deepcopy(version)
                imported_version_ids.append(version_id)
        merged_review["versions"] = list(versions_by_id.values())

        incoming_audit = incoming_review.get("audit", {}) if isinstance(incoming_review.get("audit"), dict) else {}
        incoming_findings = payload.get("findings") or result.get("findings") or incoming_audit.get("findings", [])
        merged_audit = merged_review.setdefault("audit", {})
        findings_by_id = {
            item.get("id"): copy.deepcopy(item)
            for item in merged_audit.get("findings", [])
            if isinstance(item, dict) and item.get("id")
        }
        for finding in incoming_findings if isinstance(incoming_findings, list) else []:
            if isinstance(finding, dict) and finding.get("id"):
                findings_by_id[finding["id"]] = copy.deepcopy(finding)
        merged_audit["findings"] = list(findings_by_id.values())
        if imported_version_ids:
            merged_review["activeVersion"] = imported_version_ids[-1]
        history = merged_review.setdefault("importHistory", [])
        if not isinstance(history, list):
            history = merged_review["importHistory"] = []
        history.append({
            "source": str(result_path.resolve()),
            "requestRevision": request_revision,
            "versions": imported_version_ids,
            "importedAt": utc_now(),
        })
    else:
        errors = validate_feedback(ir, payload)
        if errors:
            raise ValueError("; ".join(errors))
        merged = merge(copy.deepcopy(ir), payload)
    write_json(output.resolve(), merged)
    return {"version": 1, "status": "imported", "irFile": str(output.resolve()), "source": str(result_path.resolve())}


def diff_project(root: Path, synchronize: bool = False) -> dict[str, Any]:
    if synchronize:
        ensure_initialized(root, synchronize=True)
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
    initialization = value.get("initialization")
    if isinstance(initialization, dict) and initialization.get("message"):
        print(initialization["message"])
    if value.get("name") == "UI Design Workbench":
        print(f"{value['name']} {value.get('cliVersion', '')}")
        print(value.get("description", ""))
        print(value.get("runtime", ""))
        return
    if value.get("topic") and value.get("text"):
        print(f"Справка: {value['topic']}\n{value['text']}")
        if isinstance(value.get("settings"), dict):
            for key, item in value["settings"].items():
                print(f"{key}: {'|'.join(item['values'])} — {item['description']}")
        return
    if isinstance(value.get("configuration"), dict) and isinstance(value.get("catalog"), dict):
        configuration = value["configuration"]
        print(f"Настройка: {value.get('status', 'ok')} · детализация {configuration.get('detailLevel') or 'не выбрана'} · UI-подсказки {'включены' if configuration.get(UI_MODE_KEY, {}).get('enabled') else 'выключены'} · тестовые данные {configuration.get(MOCK_DATA_KEY, {}).get('mode', 'minimal')}")
        print(f"Файл настроек: {value.get('configFile', '')}")
        if configuration.get("setupRequired"):
            print("Следующий шаг: `uidw config setup`")
        return
    if isinstance(value.get("skillInstallations"), list):
        print("Agent Skill готов:")
        for item in value["skillInstallations"]:
            print(f"- {item.get('agent')}: {item.get('status')} · {item.get('path')}")
        print("Перезапустите агент или откройте новую сессию.")
        return
    if value.get("type") == "ui-design-workbench-native-render-state":
        summary = value.get("summary", {})
        platforms = ", ".join(summary.get("detectedPlatforms", [])) or "не обнаружены"
        configured = ", ".join(summary.get("configuredProviders", [])) or "нет"
        print(f"Нативный рендер: {value.get('currentFidelityTier', 'structural')} · платформы: {platforms}")
        print(f"Настроенные провайдеры: {configured}")
        print(f"Нативные снимки: {summary.get('nativeCaptureCount', 0)} · устаревшие: {summary.get('staleCaptureCount', 0)}")
        print(f"Важно: нативный запуск {'выполнялся' if value.get('nativeExecutionStarted') else 'не выполнялся'}.")
        if value.get("next"):
            print(f"Следующий шаг: {value['next']}")
        return
    if "propertyProvenance" in value and "schemaVersion" in value:
        coverage = value.get("propertyProvenance", {})
        labels = {"pass": "пройдено", "fail": "ошибка", "not-applicable": "не применимо"}
        print(f"Fidelity: {labels.get(value.get('status'), value.get('status', 'неизвестно'))}")
        if value.get("applicabilityReason"):
            print(f"Причина: {value['applicabilityReason']}")
        print(f"Происхождение свойств: {coverage.get('covered', 0)}/{coverage.get('total', 0)} ({coverage.get('percent', 0)}%)")
        baseline = value.get("baseline", {})
        print(f"Неизменность исходного макета: {'подтверждена' if baseline.get('valid') else 'не подтверждена'}")
        for error in value.get("strictErrors", []):
            print(f"! {error}")
        if value.get("reportFile"):
            print(f"Отчёт: {value['reportFile']}")
        return
    if isinstance(value.get("findings"), list):
        labels = {"pending": "найдена", "selected": "выбрана", "addressed": "учтена в макете", "approved": "макет подтверждён", "applied": "применена", "verified": "проверена", "rejected": "не исправлять", "deferred": "позже"}
        print(f"Проблемы: показано {value.get('shown', len(value['findings']))} из {value.get('total', len(value['findings']))}")
        for item in value["findings"]:
            state = labels.get(str(item.get("status")), str(item.get("status", "")))
            print(f"#{item['number']:<3} {str(item.get('severity', '')):<7} {state:<18} {item.get('screenId', '—')} | {item.get('title', '')}")
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
    if isinstance(value.get("render"), dict) and isinstance(value.get("check"), dict):
        print(f"Ревью готово · проверка {value['check'].get('status', 'unknown')}")
        print(f"HTML: {value.get('previewFile', '')}")
        print(f"Ссылка: {value.get('url', '')}")
        if value.get("configurationNotice"):
            print(value["configurationNotice"])
        print("Следующий шаг: откройте «Ревью» и начните с шага «Проверка».")
        return
    if isinstance(value.get(UI_MODE_KEY), dict) and not value.get("changedUiFiles"):
        print(f"UI-подсказки: {'включены' if value[UI_MODE_KEY].get('enabled') else 'выключены'}")
        if value.get("contextFile"):
            print(f"Контекст: {value['contextFile']}")
        return
    if isinstance(value.get(MOCK_DATA_KEY), dict) and not value.get("changedUiFiles"):
        print(f"Тестовые данные: {value[MOCK_DATA_KEY].get('mode', 'none')}")
        if value.get("contextFile"):
            print(f"Контекст: {value['contextFile']}")
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
    if "changedUiFiles" in value or "impactedScreenIds" in value:
        print(f"{value.get('status', 'ok')} | UI-файлов изменено: {changed} | экранов затронуто: {impacted}{mode_text}{mock_text}")
    else:
        print(str(value.get("status", "ok")))
    for key in ("contextFile", "graphFile", "previewFile", "reportFile", "jobFile", "irFile", "bundleFile", "outputDir", "diffImage", "url"):
        if value.get(key):
            print(f"{key}: {value[key]}")
    if value.get("findingIds"):
        print("findings: " + ", ".join(value["findingIds"]))
    if value.get("sourceTargets"):
        print("source targets: " + ", ".join(value["sourceTargets"]))


def resolve_init_detail(explicit: str | None, as_json: bool) -> str | None:
    if explicit in DETAIL_PROFILES:
        return explicit
    if as_json or not sys.stdin.isatty():
        return None
    print(
        "Low: basic layout and minimal mock data.\n"
        "Medium: interactions, states, and representative mock data.\n"
        "High: expanded mock data, themes, and exhaustive reconstruction/HTML checks; no automatic UI/UX review.",
        file=sys.stderr,
    )
    try:
        answer = input("Preview detail [l]ow/[m]edium/[h]igh: ").strip().lower()
    except EOFError:
        return None
    return {"l": "low", "low": "low", "m": "medium", "medium": "medium", "h": "high", "high": "high"}.get(answer)


def initialization_preferences(root: Path, args: argparse.Namespace) -> tuple[bool, str | None, bool]:
    paths = state_paths(root)
    existing = load_config(paths["config"])
    already_configured = not configuration_context(existing)["setupRequired"]
    if args.detail is not None:
        detail = args.detail
    elif already_configured:
        detail = existing.get(DETAIL_KEY)
    else:
        detail = resolve_init_detail(None, args.json)
    if args.ui_mode is not None:
        ui_mode = bool(args.ui_mode)
    elif already_configured:
        ui_mode = bool(existing.get(UI_MODE_KEY, {}).get("enabled", False))
    else:
        ui_mode = False
    completed = detail in DETAIL_PROFILES
    return ui_mode, detail, completed


def configure_setup(
    root: Path,
    detail: str | None,
    as_json: bool,
) -> dict[str, Any]:
    paths = state_paths(root)
    config = load_config(paths["config"])
    interactive = not as_json and sys.stdin.isatty()
    if detail is None and interactive:
        detail = resolve_init_detail(None, False)
    if detail in DETAIL_PROFILES:
        config[DETAIL_KEY] = detail
        config[MOCK_DATA_KEY] = {
            "mode": MOCK_DATA_BY_DETAIL[detail],
            "seed": "stable",
            "explicit": False,
        }
    configured = config.get(DETAIL_KEY) in DETAIL_PROFILES
    config[SETUP_KEY] = {
        "answered": ["detail"] if configured else [],
        "completed": configured,
    }
    paths["config"].parent.mkdir(parents=True, exist_ok=True)
    write_json(paths["config"], normalized_config(config))
    if paths["scan"].is_file():
        ensure_initialized(root, synchronize=True)
    config = load_config(state_paths(root)["config"])
    return {
        "version": 1,
        "status": configuration_context(config)["status"],
        "repoRoot": str(root),
        "configuration": configuration_context(config),
        "catalog": SETTING_CATALOG,
        "configFile": str(state_paths(root)["config"]),
    }


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


def validate_artifact(ir_path: Path, output_dir: Path, purpose: str = "projection") -> dict[str, Any]:
    from coverage_report import build_report
    from validate_platform_profiles import validate_profiles

    ir = read_json(ir_path)
    if not isinstance(ir, dict):
        raise ValueError(f"Cannot read UI IR: {ir_path}")
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    platform_report = validate_profiles(ir)
    coverage_report = build_report(ir, purpose)
    strict_fidelity = fidelity_report(ir)
    platform_path = destination / "platform-profile-report.json"
    coverage_path = destination / "ui-coverage.json"
    fidelity_path = destination / "fidelity-report.json"
    write_json(platform_path, platform_report)
    write_json(coverage_path, coverage_report)
    write_json(fidelity_path, strict_fidelity)
    fidelity_ok = strict_fidelity.get("status") in {"pass", "not-applicable"}
    status = "pass" if platform_report.get("status") == "pass" and coverage_report.get("status") == "pass" and fidelity_ok else "fail"
    return {"version": 1, "status": status, "platformReport": str(platform_path), "coverageReport": str(coverage_path), "fidelityReport": str(fidelity_path)}


def preview_uri(path: Path, view: str | None = None, screen: str | None = None, lang: str | None = None, theme: str | None = None, axis: str | None = None) -> str:
    from urllib.parse import urlencode

    query = {key: value for key, value in {"view": view, "screen": screen, "lang": lang, "theme": theme, "axis": axis}.items() if value}
    return path.resolve().as_uri() + ("?" + urlencode(query) if query else "")


def open_preview(path: Path, launch: bool = False, view: str | None = None, screen: str | None = None, lang: str | None = None, theme: str | None = None, axis: str | None = None) -> dict[str, Any]:
    if not path.resolve().is_file():
        raise ValueError(f"Preview does not exist: {path.resolve()}")
    uri = preview_uri(path, view, screen, lang, theme, axis)
    launched = bool(webbrowser.open(uri)) if launch else False
    return {"version": 1, "status": "opened" if launched else "ready", "previewFile": str(path.resolve()), "url": uri, "launched": launched}


def run_headless_smoke(preview: Path, output_dir: Path, purpose: str = "projection") -> dict[str, Any]:
    if purpose not in {"projection", "review"}:
        raise ValueError(f"Unknown smoke purpose: {purpose}")
    node = shutil.which("node")
    chrome = chrome_path()
    if not node or not chrome:
        return {"version": 1, "status": "unavailable", "reason": "Node.js and Chromium/Edge are required for full smoke"}
    script = Path(__file__).resolve().parent / "smoke_preview.js"
    report = output_dir / "ui-diagnostics.json"
    command = [node, str(script), str(preview.resolve()), "--output", str(report), "--mode", purpose]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return {"version": 1, "status": "fail", "reason": "Headless smoke timed out after 60 seconds"}
    data = read_json(report, {}) if report.is_file() else {}
    status = "pass" if completed.returncode == 0 and data.get("status") in {"pass", "complete"} else "fail"
    return {
        "version": 1,
        "status": status,
        "purpose": purpose,
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
    purpose: str = "projection",
) -> dict[str, Any]:
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    validation = validate_artifact(ir_path, destination, purpose)
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
        checks["headlessSmoke"] = run_headless_smoke(preview_path, destination, purpose)
    status = "pass" if all(item.get("status") in {"pass", "ok"} for item in checks.values()) else "fail"
    report = {"version": 1, "status": status, "level": level, "purpose": purpose, "irFile": str(ir_path.resolve()), "previewFile": str(preview_path) if preview_path.is_file() else None, "checks": checks}
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
    theme: str | None = None,
    axis: str | None = None,
    purpose: str = "projection",
) -> dict[str, Any]:
    paths = state_paths(root)
    initialization = None
    if ir_path is None:
        ensured, paths, _ = ensure_initialized(root)
        initialization = ensured.get("initialization")
        ir_path = paths["ir"]
        allow_draft = True
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    preview = destination / "ui-preview.html"
    rendered = render_artifact(ir_path, preview, allow_draft, agent)
    checked = check_artifact(ir_path, destination / "validation", level, "json", preview, purpose)
    opened = open_preview(preview, launch, view, screen, lang, theme, axis)
    status = "pass" if checked["status"] == "pass" else "blocked"
    result = {"version": 1, "status": status, "purpose": purpose, "render": rendered, "check": checked, "previewFile": str(preview), "url": opened["url"], "launched": opened["launched"]}
    if initialization:
        result["initialization"] = initialization
    return result


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
    payloads: dict[str, bytes] = {}
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("Bundle contains duplicate paths")
        for info in infos:
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError(f"Unsafe bundle path: {info.filename}") from exc
        file_infos = {info.filename: info for info in infos if not info.is_dir()}
        if "uidw-bundle.json" not in file_infos:
            raise ValueError("Bundle manifest uidw-bundle.json is missing")
        try:
            manifest = json.loads(archive.read(file_infos["uidw-bundle.json"]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Bundle manifest is not valid JSON") from exc
        if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("type") != "ui-design-workbench-bundle":
            raise ValueError("Bundle manifest type or version is unsupported")
        declared = manifest.get("files")
        if not isinstance(declared, list):
            raise ValueError("Bundle manifest files must be an array")
        declared_paths: set[str] = set()
        for item in declared:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
                raise ValueError("Bundle manifest contains an invalid file entry")
            relative = item["path"]
            target = (destination / relative).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError(f"Unsafe bundle manifest path: {relative}") from exc
            if relative == "uidw-bundle.json" or relative in declared_paths:
                raise ValueError(f"Bundle manifest contains a duplicate or reserved path: {relative}")
            declared_paths.add(relative)
        archive_paths = set(file_infos) - {"uidw-bundle.json"}
        if archive_paths != declared_paths:
            missing = sorted(declared_paths - archive_paths)
            unexpected = sorted(archive_paths - declared_paths)
            raise ValueError(f"Bundle members do not match manifest; missing={missing}, unexpected={unexpected}")
        for item in declared:
            relative = item["path"]
            payload = archive.read(file_infos[relative])
            digest = hashlib.sha256(payload).hexdigest()
            if digest != item.get("sha256") or len(payload) != item.get("bytes"):
                raise ValueError(f"Bundle integrity check failed: {relative}")
            payloads[relative] = payload
        payloads["uidw-bundle.json"] = archive.read(file_infos["uidw-bundle.json"])

    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Bundle output directory must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for relative, payload in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, target)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
    return {"version": 1, "status": "unpacked", "outputDir": str(destination), "files": sorted(payloads)}


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
    parser = argparse.ArgumentParser(
        prog="uidw",
        description="Проверка и улучшение интерфейса без запуска приложения.",
        epilog="Основной путь: uidw review. Расширенные команды: uidw help advanced.",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="Показать эту справку")
    parser.add_argument("--version", action="version", version=f"uidw {CLI_VERSION}", help="Показать версию")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Корень проекта")
    parser.add_argument("--json", action="store_true", help="Вывести JSON для автоматизации")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="КОМАНДА")
    advanced_help = argparse.SUPPRESS
    init_parser = subparsers.add_parser("init", help="Необязательно: настроить или принудительно пересоздать UI-кеш")
    init_parser.add_argument("--force", action="store_true", help="Recreate config and scan even when the cache is clean")
    init_parser.add_argument("--project-cache", action="store_true", help="Store ignored derived state inside the repository instead of the OS cache")
    init_mode = init_parser.add_mutually_exclusive_group()
    init_mode.add_argument("--ui-mode", dest="ui_mode", action="store_true", default=None, help="Enable platform guidance for ordinary UI tasks without prompting")
    init_mode.add_argument("--no-ui-mode", dest="ui_mode", action="store_false", default=None, help="Keep platform guidance disabled without prompting")
    init_parser.add_argument("--detail", choices=("low", "medium", "high"), default=None, help="Low: minimal data; Medium: representative data; High: expanded data, themes, and reconstruction/HTML checks; no automatic UI/UX review")
    status_parser = subparsers.add_parser("status", help="Показать, актуален ли UI-кеш")
    status_parser.add_argument("--verify-content", action="store_true", help="Hash every candidate file instead of trusting unchanged metadata")
    native_parser = subparsers.add_parser("native", help="Показать готовность точного Android/iOS-рендера")
    native_parser.add_argument("action", choices=("status",), nargs="?", default="status")
    native_parser.add_argument("--platform", choices=("all", "android", "apple"), default="all")
    sync_parser = subparsers.add_parser("sync", help=advanced_help)
    sync_parser.add_argument("--force", action="store_true", help="Force a full UI rescan")
    sync_parser.add_argument("--verify-content", action="store_true", help="Hash every candidate file before deciding")
    context_parser = subparsers.add_parser("context", help=advanced_help)
    context_parser.add_argument("--no-sync", action="store_true", help="Do not refresh a stale cache")
    context_parser.add_argument("--screen", help="Write a bounded context containing only one translated screen and its source references")
    context_parser.add_argument("--budget", type=int, help="Approximate maximum token budget for the exported context")
    context_parser.add_argument("--changed-only", action="store_true", help="Include only files and entities affected by the latest UI change")
    context_parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Context artifact format")
    scope_parser = subparsers.add_parser("scope", help=advanced_help)
    scope_parser.add_argument("--ir", type=Path, help="UI IR; defaults to the cached project IR")
    scope_parser.add_argument("--screen", action="append", default=[], help="Screen id or name; repeat for a small multi-screen scope")
    scope_parser.add_argument("--finding", action="append", default=[], help="Stable finding id or displayed number; repeat as needed")
    scope_parser.add_argument("--budget", type=int, default=4000, help="Context token budget; structure is never cut to fit")
    scope_parser.add_argument("--provenance", choices=("summary", "full"), default="summary", help="Return compact property names or full source evidence")
    scope_parser.add_argument("--if-none-match", help="Return a compact not-modified response when the scope hash matches")
    scope_parser.add_argument("--output", type=Path, help="Output path; defaults beside the IR")
    patch_parser = subparsers.add_parser("patch", help=advanced_help)
    patch_parser.add_argument("action", choices=("template", "validate", "apply"))
    patch_parser.add_argument("patch", type=Path, nargs="?", help="Path to ui-ir.patch.json for validate/apply")
    patch_parser.add_argument("--ir", type=Path, help="UI IR; defaults to the cached project IR")
    patch_parser.add_argument("--context", type=Path, help="Scoped context path recorded by a new template")
    patch_parser.add_argument("--output", type=Path, help="Template or patched IR output path")
    mcp_parser = subparsers.add_parser("mcp", help=advanced_help)
    mcp_parser.add_argument("--name", default="UI Design Workbench", help="Local MCP server name")
    map_parser = subparsers.add_parser("map", help=advanced_help)
    map_parser.add_argument("--output", type=Path, help="Copy ui-graph.json to this explicit path")
    render_parser = subparsers.add_parser("render", help=advanced_help)
    render_parser.add_argument("ir", type=Path, help="Path to ui-ir.json")
    render_parser.add_argument("--output", type=Path, required=True, help="Output HTML path")
    render_parser.add_argument("--allow-draft", action="store_true", help="Render an incomplete IR for internal diagnostics")
    render_parser.add_argument("--agent", choices=("generic", "codex"), default="generic", help="Optional agent handoff adapter")
    validate_parser = subparsers.add_parser("validate", help=advanced_help)
    validate_parser.add_argument("ir", type=Path, help="Path to ui-ir.json")
    validate_parser.add_argument("--output-dir", type=Path, required=True, help="Directory for validation reports")
    check_parser = subparsers.add_parser("check", help="Проверить точность переноса и HTML без UI/UX-аудита")
    check_parser.add_argument("--ir", type=Path, help="UI IR; defaults to the cached project IR")
    check_parser.add_argument("--output-dir", type=Path, help="Report directory; defaults to the project cache")
    check_parser.add_argument("--level", choices=("quick", "full"), default=None)
    check_parser.add_argument("--format", choices=("json", "sarif", "junit"), default="json")
    check_parser.add_argument("--preview", type=Path, help="Existing preview for the full smoke gate")
    workbench_parser = subparsers.add_parser("workbench", help=advanced_help)
    workbench_parser.add_argument("--ir", type=Path, help="Review IR; defaults to the cached project IR")
    workbench_parser.add_argument("--output-dir", type=Path, help="Artifact directory; defaults to the project cache")
    workbench_parser.add_argument("--level", choices=("quick", "full"), default=None)
    workbench_parser.add_argument("--allow-draft", action="store_true")
    workbench_parser.add_argument("--agent", choices=("generic", "codex"), default="generic")
    workbench_parser.add_argument("--open", action="store_true", dest="launch")
    workbench_parser.add_argument("--view", choices=("overview", "prototype", "single", "states", "compare"))
    workbench_parser.add_argument("--screen")
    workbench_parser.add_argument("--lang", choices=("ru", "en"))
    workbench_parser.add_argument("--theme", help="Initial detected theme id")
    workbench_parser.add_argument("--axis", choices=("themes", "states", "matrix"), help="Initial variants-canvas organization")
    open_parser = subparsers.add_parser("open", help="Открыть последнее ревью")
    open_parser.add_argument("preview", type=Path, nargs="?", help="Preview HTML; defaults to the cached workbench")
    open_parser.add_argument("--launch", action="store_true")
    open_parser.add_argument("--view", choices=("overview", "prototype", "single", "states", "compare"))
    open_parser.add_argument("--screen")
    open_parser.add_argument("--lang", choices=("ru", "en"))
    open_parser.add_argument("--theme", help="Initial detected theme id")
    open_parser.add_argument("--axis", choices=("themes", "states", "matrix"))
    diff_parser = subparsers.add_parser("diff", help=advanced_help)
    diff_parser.add_argument("--sync", action="store_true", help="Synchronize before returning the semantic diff")
    mode_parser = subparsers.add_parser("ui-mode", help=advanced_help)
    mode_group = mode_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--enable", action="store_true", help="Enable UI guidance without rescanning unchanged UI source")
    mode_group.add_argument("--disable", action="store_true", help="Disable UI guidance without rescanning unchanged UI source")
    config_parser = subparsers.add_parser("config", help=advanced_help)
    config_parser.add_argument("action", choices=("show", "set", "setup", "reset"), nargs="?", default="show")
    config_parser.add_argument("key", nargs="?", help="Setting name for `config set`")
    config_parser.add_argument("value", nargs="?", help="Setting value for `config set`")
    config_parser.add_argument("--detail", choices=("low", "medium", "high"))
    help_parser = subparsers.add_parser("help", help="Показать справку по задаче")
    help_parser.add_argument("topic", nargs="?", choices=("overview", "config", "themes", "review", "workbench", "apply", "advanced"))
    subparsers.add_parser("about", help=advanced_help)
    scenarios_parser = subparsers.add_parser("scenarios", help=advanced_help)
    scenarios_parser.add_argument("action", choices=("list", "validate"), nargs="?", default="list")
    scenarios_parser.add_argument("--ir", type=Path)
    scenarios_parser.add_argument("--screen")
    findings_parser = subparsers.add_parser("findings", help=advanced_help)
    findings_parser.add_argument("action", choices=("list", "accept", "reject", "defer", "reset"), nargs="?", default="list")
    findings_parser.add_argument("identifiers", nargs="*", help="Stable finding IDs or displayed global numbers")
    findings_parser.add_argument("--ir", type=Path)
    findings_parser.add_argument("--feedback", type=Path, help="Optional exported browser feedback containing runtime findings")
    findings_parser.add_argument("--screen")
    findings_parser.add_argument("--status", choices=("pending", "selected", "addressed", "approved", "applied", "verified", "rejected", "deferred"))
    review_parser = subparsers.add_parser("review", help="Запустить понятное трёхшаговое ревью")
    review_parser.add_argument("action", choices=("start", "prepare", "import"), nargs="?", default="start", help="start открывает workbench; prepare/import нужны для внешнего AI")
    review_parser.add_argument("result", type=Path, nargs="?", help="Result JSON for review import")
    review_parser.add_argument("--ir", type=Path)
    review_parser.add_argument("--output", type=Path)
    review_parser.add_argument("--output-dir", type=Path, help="Каталог HTML и отчётов")
    review_parser.add_argument("--provider", default="generic")
    review_parser.add_argument("--scope", choices=("all", "current"), default="all")
    review_parser.add_argument("--level", choices=("quick", "full"), help="Глубина автоматических проверок")
    review_parser.add_argument("--no-open", dest="launch", action="store_false", default=True, help="Не открывать HTML автоматически")
    review_parser.add_argument("--view", choices=("overview", "prototype", "single", "states", "compare"))
    review_parser.add_argument("--screen")
    review_parser.add_argument("--lang", choices=("ru", "en"), default="ru")
    proposal_parser = subparsers.add_parser("proposal", help=advanced_help)
    proposal_parser.add_argument("action", choices=("prepare",), nargs="?", default="prepare")
    proposal_parser.add_argument("identifiers", nargs="*")
    proposal_parser.add_argument("--ir", type=Path)
    proposal_parser.add_argument("--output", type=Path)
    proposal_parser.add_argument("--provider", default="generic")
    apply_parser = subparsers.add_parser("apply", help="Применить подтверждённый новый макет к проекту")
    apply_parser.add_argument("action", choices=("prepare",), nargs="?", default="prepare")
    apply_parser.add_argument("identifiers", nargs="*")
    apply_parser.add_argument("--ir", type=Path)
    apply_parser.add_argument("--output", type=Path)
    apply_parser.add_argument("--provider", default="generic")
    apply_parser.add_argument("--direct", action="store_true", help="Явно разрешить исправление без предварительного нового макета")
    pack_parser = subparsers.add_parser("pack", help=advanced_help)
    pack_parser.add_argument("--ir", type=Path)
    pack_parser.add_argument("--output", type=Path, required=True)
    unpack_parser = subparsers.add_parser("unpack", help=advanced_help)
    unpack_parser.add_argument("bundle", type=Path)
    unpack_parser.add_argument("--output-dir", type=Path, required=True)
    visual_parser = subparsers.add_parser("visual-test", help=advanced_help)
    visual_parser.add_argument("--baseline", type=Path, required=True)
    visual_parser.add_argument("--candidate", type=Path, required=True)
    visual_parser.add_argument("--output-dir", type=Path, required=True)
    visual_parser.add_argument("--baseline-geometry", type=Path)
    visual_parser.add_argument("--candidate-geometry", type=Path)
    fidelity_parser = subparsers.add_parser("fidelity", help=advanced_help)
    fidelity_parser.add_argument("action", choices=("report", "explain", "capabilities"), nargs="?", default="report")
    fidelity_parser.add_argument("identifier", nargs="?", help="Node id or stable evidence id for explain")
    fidelity_parser.add_argument("--ir", type=Path, help="UI IR; defaults to the cached project IR")
    fidelity_parser.add_argument("--output", type=Path, help="Optional report file")
    fidelity_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    install_skill_parser = subparsers.add_parser("install-skill", help="Установить Agent Skill без клонирования репозитория")
    install_skill_parser.add_argument("agent", choices=(*SUPPORTED_SKILL_AGENTS, "all"), nargs="?", default="codex", help="Агент или all")
    install_skill_parser.add_argument("--target", type=Path, help="Явный каталог назначения для одного агента")
    subparsers.add_parser("doctor", help="Проверить установку и зависимости")
    hidden_commands = {
        "sync", "context", "scope", "patch", "mcp", "map", "render", "validate", "workbench", "diff", "ui-mode",
        "config", "about", "scenarios", "findings", "proposal", "pack", "unpack", "visual-test", "fidelity",
    }
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest not in hidden_commands
    ]
    parser._positionals.title = "Команды"
    parser._optionals.title = "Параметры"
    for command_parser in subparsers.choices.values():
        command_parser._positionals.title = "Аргументы"
        command_parser._optionals.title = "Параметры"
        for action in command_parser._actions:
            if action.dest == "help":
                action.help = "Показать эту справку"
    argv = sys.argv[1:]
    if "--json" in argv:
        argv = [item for item in argv if item != "--json"]
        argv.insert(0, "--json")
    return parser.parse_args(argv)


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
            ui_mode, detail, setup_completed = initialization_preferences(root, args)
            result = initialize(root, args.force, args.project_cache, ui_mode, detail, setup_completed)
        elif args.command == "status":
            result, _, _, _ = inspect_cache(root, args.verify_content)
        elif args.command == "native":
            from native_render_registry import native_render_status

            result = native_render_status(root, paths["native"], args.platform)
        elif args.command == "sync":
            result, paths, _ = ensure_initialized(root, args.force, args.verify_content, synchronize=True)
        elif args.command == "context":
            result, paths, _ = ensure_initialized(root, synchronize=False if args.no_sync else None)
            context_path = write_context_variant(paths, args.screen, args.budget, args.changed_only, args.format)
            result = {**result, "contextFile": str(context_path)}
        elif args.command == "scope":
            if args.ir is None:
                _, paths, _ = ensure_initialized(root)
            ir_path, ir = load_ir_argument(paths, args.ir)
            output = (args.output or ir_path.with_name("ui-agent-context.json")).resolve()
            payload = build_scoped_context(
                ir,
                screen_ids=args.screen,
                finding_ids=args.finding,
                token_budget=args.budget,
                ui_ir_file=str(ir_path),
                provenance_mode=args.provenance,
                if_none_match=args.if_none_match,
            )
            if payload.get("status") != "not-modified":
                write_scoped_json(output, payload)
            result = {
                "version": 1,
                "status": payload.get("status", "ready"),
                "contextFile": str(output),
                "scope": payload.get("scope", {}),
                "scopeHash": payload.get("scopeHash"),
                "contextBudget": payload.get("contextBudget", {}),
            }
        elif args.command == "patch":
            ir_path, ir = load_ir_argument(paths, args.ir)
            if args.action == "template":
                output = (args.output or ir_path.with_name("ui-ir.patch.json")).resolve()
                write_scoped_json(output, patch_template(ir, str(ir_path), str(args.context.resolve()) if args.context else None))
                result = {"version": 1, "status": "prepared", "patchFile": str(output), "uiIrFile": str(ir_path)}
            else:
                if not args.patch:
                    raise ValueError(f"patch {args.action} requires a ui-ir.patch.json path")
                patch_payload = read_scoped_json(args.patch.resolve())
                errors = validate_ir_patch(ir, patch_payload)
                if errors:
                    raise ValueError("; ".join(errors))
                if args.action == "validate":
                    result = {"version": 1, "status": "pass", "patchFile": str(args.patch.resolve()), "operations": len(patch_payload.get("operations", []))}
                else:
                    output = (args.output or ir_path.with_name("ui-ir.patched.json")).resolve()
                    result = apply_patch_file(ir_path, args.patch, output)
        elif args.command == "mcp":
            from uidw_mcp import run_server

            run_server(root, args.name)
            return 0
        elif args.command == "map":
            result, paths, _ = ensure_initialized(root)
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
            configured_level = effective_review_config(load_config(paths["config"]))["validation"]
            result = check_artifact(ir_path, output_dir, args.level or configured_level, args.format, args.preview)
        elif args.command == "workbench":
            config = load_config(paths["config"])
            preview_config = effective_preview_config(config)
            review_config = effective_review_config(config)
            output_dir = args.output_dir or paths["dir"] / "workbench"
            configured_lang = preview_config.get("language")
            configured_axis = preview_config.get("themeLayout")
            result = build_workbench(root, args.ir, output_dir, args.level or review_config.get("validation", "quick"), args.allow_draft, args.agent, args.launch, args.view or preview_config.get("defaultView"), args.screen, args.lang or (configured_lang if configured_lang in {"ru", "en"} else None), args.theme, args.axis or (configured_axis if configured_axis in {"themes", "states", "matrix"} else None))
        elif args.command == "open":
            preview_config = effective_preview_config(load_config(paths["config"]))
            preview = args.preview or paths["dir"] / "workbench" / "ui-preview.html"
            configured_lang = preview_config.get("language")
            configured_axis = preview_config.get("themeLayout")
            result = open_preview(preview, args.launch, args.view or preview_config.get("defaultView"), args.screen, args.lang or (configured_lang if configured_lang in {"ru", "en"} else None), args.theme, args.axis or (configured_axis if configured_axis in {"themes", "states", "matrix"} else None))
        elif args.command == "diff":
            result = diff_project(root, args.sync)
        elif args.command == "ui-mode":
            result = configure_ui_mode(root, True if args.enable else False if args.disable else None)
        elif args.command == "config":
            result = configure_setup(root, args.detail, args.json) if args.action == "setup" else configure_project(root, args.action, args.key, args.value)
        elif args.command == "help":
            result = help_topic(args.topic)
        elif args.command == "about":
            result = about()
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
                decision = {"accept": "accepted", "reject": "rejected", "defer": "deferred", "reset": "pending"}[args.action]
                result = update_finding_decisions(ir, args.identifiers, decision)
                write_json(ir_path, ir)
        elif args.command == "review":
            if args.action == "start":
                config = load_config(paths["config"])
                setup = configuration_context(config)
                preview_config = effective_preview_config(config)
                review_config = effective_review_config(config)
                output_dir = args.output_dir or paths["dir"] / "workbench"
                result = build_workbench(
                    root,
                    args.ir,
                    output_dir,
                    args.level or review_config.get("validation", "quick"),
                    False,
                    args.provider,
                    args.launch,
                    args.view or preview_config.get("defaultView"),
                    args.screen,
                    args.lang,
                    None,
                    preview_config.get("themeLayout") if preview_config.get("themeLayout") in {"themes", "states", "matrix"} else None,
                    "review",
                )
                result["workflow"] = "review"
                if setup.get("setupRequired"):
                    result["configurationNotice"] = "Постоянная детализация не выбрана. Задайте Low, Medium или High командой `uidw config setup`."
            else:
                ir_path, ir = load_ir_argument(paths, args.ir)
            if args.action == "prepare":
                output = args.output or ir_path.parent / "ui-agent-job.json"
                result = prepare_agent_job(root, ir_path, ir, "expert", output, args.provider, scope=args.scope)
            elif args.action == "import":
                if not args.result:
                    raise ValueError("Review import requires a result JSON path")
                output = args.output or ir_path.with_name("ui-ir.imported.json")
                result = import_review_result(ir_path, args.result, output)
        elif args.command in {"proposal", "apply"}:
            ir_path, ir = load_ir_argument(paths, args.ir)
            kind = "proposal" if args.command == "proposal" else "implementation"
            output = args.output or ir_path.parent / f"ui-agent-job-{kind}.json"
            result = prepare_agent_job(root, ir_path, ir, kind, output, args.provider, args.identifiers, direct=bool(getattr(args, "direct", False)))
        elif args.command == "pack":
            ir_path, _ = load_ir_argument(paths, args.ir)
            result = pack_artifact(ir_path, args.output)
        elif args.command == "unpack":
            result = unpack_artifact(args.bundle, args.output_dir)
        elif args.command == "visual-test":
            result = visual_test(args.baseline, args.candidate, args.output_dir, args.baseline_geometry, args.candidate_geometry)
        elif args.command == "fidelity":
            ir = {} if args.action == "capabilities" else load_ir_argument(paths, args.ir)[1]
            result = fidelity_command(ir, args.action, args.identifier, args.output, args.format)
        elif args.command == "install-skill":
            result = install_skill(args.agent, args.target)
        else:
            result = doctor(root)
    except (ValueError, RuntimeError, TimeoutError, OSError, zipfile.BadZipFile) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        if getattr(args, "command", None):
            print(f"Подсказка: `uidw {args.command} --help`; общий маршрут — `uidw help overview`", file=sys.stderr)
        return 3
    print_result(result, args.json)
    gate_failed = result.get("status") not in {"pass", "not-applicable"}
    return 4 if args.command in {"validate", "check", "visual-test", "fidelity"} and gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
