#!/usr/bin/env python3
"""Read-only Apple native-render provider discovery."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator


IGNORED_DIRS = {".git", ".build", ".idea", ".ui-design-workbench", "build", "DerivedData", "node_modules", "Pods", "vendor"}
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


def _bundles(root: Path) -> tuple[list[Path], list[Path]]:
    projects: list[Path] = []
    workspaces: list[Path] = []
    for directory, names, _ in os.walk(root):
        names[:] = [name for name in names if name not in IGNORED_DIRS and not name.startswith(".")]
        current = Path(directory)
        for name in list(names):
            path = current / name
            if name.endswith(".xcodeproj"):
                projects.append(path)
                names.remove(name)
            elif name.endswith(".xcworkspace"):
                workspaces.append(path)
                names.remove(name)
    return projects, workspaces


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


def discover_apple(root: Path, host_platform: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    host = host_platform or sys.platform
    all_files = list(_files(root))
    swift_files = [path for path in all_files if path.suffix.lower() == ".swift"]
    interfaces = [path for path in all_files if path.suffix.lower() in {".storyboard", ".xib"}]
    package_files = [path for path in all_files if path.name in {"Package.swift", "Package.resolved", "Podfile"}]
    projects, workspaces = _bundles(root)
    detected = bool(swift_files or interfaces or projects or workspaces)
    preview_entries: list[dict[str, Any]] = []
    snapshot_markers = 0
    swiftui_views = 0
    source_inputs: list[Path] = []
    for path in swift_files:
        text = _read(path)
        if not text:
            continue
        if "SwiftUI" in text or "#Preview" in text or "PreviewProvider" in text or "SnapshotTesting" in text:
            source_inputs.append(path)
        swiftui_views += len(re.findall(r"\bstruct\s+\w+\s*:\s*View\b", text))
        snapshot_markers += len(re.findall(r"(?:SnapshotTesting|assertSnapshot|iOSSnapshotTestCase|FBSnapshotTestCase)", text))
        for match in re.finditer(r"#Preview(?:\s*\(\s*[\"']([^\"']+)[\"'][^)]*\))?", text):
            preview_entries.append({"symbol": match.group(1) or "#Preview", "file": _relative(path, root)})
        for match in re.finditer(r"\bstruct\s+(\w+)\s*:\s*PreviewProvider\b", text):
            preview_entries.append({"symbol": match.group(1), "file": _relative(path, root)})
    package_text = "\n".join(_read(path) for path in package_files)
    snapshot_configured = snapshot_markers > 0 or "swift-snapshot-testing" in package_text.lower()
    mac_host = host == "darwin"
    xcode_ready = bool(mac_host and shutil.which("xcodebuild"))
    simulator_ready = bool(xcode_ready and shutil.which("xcrun"))

    def status(configured: bool, requires_host: bool = True) -> str:
        if not detected:
            return "not-applicable"
        if requires_host and not mac_host:
            return "host-required"
        return "configured" if configured else "not-configured"

    providers = [
        {
            "id": "xcode-preview",
            "platform": "apple",
            "status": status(bool(preview_entries) and xcode_ready),
            "availableFidelityTier": "native-preview",
            "supports": ["swiftui"],
            "reason": "Xcode and SwiftUI preview entries are available." if preview_entries and xcode_ready else "Requires a macOS Xcode worker and a SwiftUI Preview entry point.",
            "execution": "explicit-only",
        },
        {
            "id": "swift-snapshot-testing",
            "platform": "apple",
            "status": status(snapshot_configured and xcode_ready),
            "availableFidelityTier": "native-preview",
            "supports": ["swiftui", "uikit", "appkit"],
            "reason": "Snapshot test markers and Xcode are available." if snapshot_configured and xcode_ready else "Requires a configured snapshot-test target on a macOS Xcode worker.",
            "execution": "explicit-only",
        },
        {
            "id": "apple-simulator",
            "platform": "apple",
            "status": status(simulator_ready),
            "availableFidelityTier": "device-verified",
            "supports": ["swiftui", "uikit", "appkit", "runtime-state"],
            "reason": "Xcode simulator tooling is available." if simulator_ready else "Requires an explicit run on a macOS Xcode worker.",
            "execution": "explicit-only",
        },
    ]
    configured = [provider["id"] for provider in providers if provider["status"] == "configured"]
    inputs = swift_files + interfaces + package_files
    return {
        "platform": "apple",
        "status": "detected" if detected else "not-applicable",
        "sourceFingerprint": _fingerprint(root, inputs),
        "project": {
            "hostPlatform": host,
            "requiresMacOSWorker": bool(detected and not mac_host),
            "xcodeProjectCount": len(projects),
            "xcodeWorkspaceCount": len(workspaces),
            "swiftFileCount": len(swift_files),
            "swiftUIViewCount": swiftui_views,
            "previewEntryCount": len(preview_entries),
            "interfaceResourceCount": len(interfaces),
            "snapshotTestMarkerCount": snapshot_markers,
        },
        "entryPoints": preview_entries[:200],
        "providers": providers,
        "recommendedProvider": configured[0] if configured else None,
        "currentFidelityTier": "structural",
        "nativeExecutionStarted": False,
        "limitations": [
            "Windows and Linux can discover Apple UI but cannot render it natively.",
            "A configured provider is capability evidence, not visual fidelity evidence.",
        ],
    }
