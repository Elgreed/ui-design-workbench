#!/usr/bin/env python3
"""Read-only Android native-render provider discovery.

Discovery never invokes Gradle, starts an emulator, or edits the target repo.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterator


IGNORED_DIRS = {".git", ".gradle", ".idea", ".ui-design-workbench", "build", "dist", "node_modules", "out", "vendor"}
TEXT_LIMIT = 2 * 1024 * 1024
FILE_LIMIT = 30000


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _files(root: Path) -> Iterator[Path]:
    seen = 0
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in IGNORED_DIRS and not name.startswith(".")]
        for name in files:
            seen += 1
            if seen > FILE_LIMIT:
                return
            yield Path(directory) / name


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > TEXT_LIMIT:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _fingerprint(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{_relative(path, root)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _settings_modules(text: str) -> set[str]:
    modules: set[str] = set()
    for match in re.finditer(r"(?ms)^\s*include\s*\((.*?)\)", text):
        modules.update(re.findall(r"[\"'](:[^\"']+)[\"']", match.group(1)))
    for match in re.finditer(r"(?m)^\s*include\s+([^\n]+)", text):
        modules.update(re.findall(r"[\"'](:[^\"']+)[\"']", match.group(1)))
    return modules


def _provider(provider_id: str, configured: bool, reason: str, supports: list[str]) -> dict[str, Any]:
    return {
        "id": provider_id,
        "platform": "android",
        "status": "configured" if configured else "not-configured",
        "availableFidelityTier": "native-preview",
        "supports": supports,
        "reason": reason,
        "execution": "explicit-only",
    }


def discover_android(root: Path) -> dict[str, Any]:
    root = root.resolve()
    all_files = list(_files(root))
    settings = [path for path in all_files if path.name in {"settings.gradle", "settings.gradle.kts"}]
    build_files = [path for path in all_files if path.name in {"build.gradle", "build.gradle.kts", "libs.versions.toml", "gradle.properties"}]
    manifests = [path for path in all_files if path.name == "AndroidManifest.xml"]
    kotlin = [path for path in all_files if path.suffix.lower() in {".kt", ".kts"} and path.name not in {"build.gradle.kts", "settings.gradle.kts"}]
    layouts = [
        path for path in all_files
        if path.suffix.lower() == ".xml" and any(part.startswith("layout") for part in path.parts) and "res" in path.parts
    ]
    resources = [path for path in all_files if "res" in path.parts and "src" in path.parts]
    settings_text = {path: _read(path) for path in settings}
    build_text = {path: _read(path) for path in build_files}
    combined_build = "\n".join(build_text.values())
    modules = sorted({module for text in settings_text.values() for module in _settings_modules(text)})
    android_markers = (
        "com.android.application",
        "com.android.library",
        "com.android.test",
        "com.android.dynamic-feature",
        "android {",
    )
    detected = bool(manifests or any(marker in combined_build for marker in android_markers))
    wrapper = next((path for path in (root / "gradlew.bat", root / "gradlew") if path.is_file()), None)

    preview_entries: list[dict[str, Any]] = []
    compose_function_count = 0
    screenshot_test_count = 0
    for path in kotlin:
        text = _read(path)
        if not text:
            continue
        compose_function_count += len(re.findall(r"@Composable\b", text))
        screenshot_test_count += len(re.findall(r"(?:Paparazzi|Roborazzi|PreviewTest|captureRoboImage|snapshot\s*\()", text))
        for match in re.finditer(r"@(?:[\w.]*Preview)\b(?:\s*\([^)]*\))?[\s\S]{0,800}?\bfun\s+(\w+)\s*\(", text):
            preview_entries.append({"symbol": match.group(1), "file": _relative(path, root)})

    official = "com.android.compose.screenshot" in combined_build or "android.experimental.enableScreenshotTest" in combined_build
    paparazzi = "app.cash.paparazzi" in combined_build or "paparazzi-gradle-plugin" in combined_build
    roborazzi = "io.github.takahirom.roborazzi" in combined_build or re.search(r"\broborazzi\b", combined_build, re.I) is not None
    providers = [
        _provider("android-compose-screenshot", official, "Official Compose screenshot plugin marker found." if official else "Compose screenshot plugin is not configured.", ["compose"]),
        _provider("paparazzi", paparazzi, "Paparazzi marker found; Layoutlib capture can run without an emulator." if paparazzi else "Paparazzi is not configured.", ["compose", "views"]),
        _provider("roborazzi", roborazzi, "Roborazzi marker found." if roborazzi else "Roborazzi is not configured.", ["compose", "views"]),
    ]
    sdk_present = bool(os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME"))
    emulator_ready = bool(detected and wrapper and sdk_present and (shutil.which("emulator") or shutil.which("emulator.exe")))
    providers.append({
        "id": "android-emulator",
        "platform": "android",
        "status": "configured" if emulator_ready else "available" if detected else "not-applicable",
        "availableFidelityTier": "device-verified",
        "supports": ["compose", "views", "runtime-state"],
        "reason": "Gradle wrapper, Android SDK, and emulator executable are available." if emulator_ready else "Requires an explicit emulator run with a configured SDK and Gradle wrapper.",
        "execution": "explicit-only",
    })
    configured = [provider["id"] for provider in providers if provider["status"] == "configured"]
    inputs = settings + build_files + manifests + resources + kotlin
    return {
        "platform": "android",
        "status": "detected" if detected else "not-applicable",
        "sourceFingerprint": _fingerprint(root, inputs),
        "project": {
            "gradleWrapper": _relative(wrapper, root) if wrapper else None,
            "settingsFiles": [_relative(path, root) for path in settings],
            "modules": modules,
            "manifestCount": len(manifests),
            "composeFunctionCount": compose_function_count,
            "previewEntryCount": len(preview_entries),
            "layoutResourceCount": len(layouts),
            "screenshotTestMarkerCount": screenshot_test_count,
        },
        "entryPoints": preview_entries[:200],
        "providers": providers,
        "recommendedProvider": configured[0] if configured else None,
        "currentFidelityTier": "structural",
        "nativeExecutionStarted": False,
        "limitations": [
            "Discovery does not execute Gradle or render a screen.",
            "A configured provider is capability evidence, not visual fidelity evidence.",
        ],
    }
