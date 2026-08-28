#!/usr/bin/env python3
"""Native renderer discovery and cache-state orchestration."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from native_render_android import discover_android
from native_render_apple import discover_apple
from native_render_contracts import empty_native_state, load_native_state, write_native_state


def discover_native_render(root: Path) -> dict[str, Any]:
    platforms = [discover_android(root), discover_apple(root)]
    detected = [item for item in platforms if item.get("status") == "detected"]
    providers = [provider for item in platforms for provider in item.get("providers", [])]
    configured = [provider for provider in providers if provider.get("status") == "configured"]
    host_required = [provider for provider in providers if provider.get("status") == "host-required"]
    if configured:
        next_action = "Choose one configured provider and explicitly request a native capture."
    elif host_required:
        next_action = "Configure a macOS Xcode worker before requesting Apple native captures."
    elif detected:
        next_action = "Configure a supported screenshot provider; source projection remains structural-only."
    else:
        next_action = "No Android or Apple native project was detected."
    return {
        "schemaVersion": 1,
        "type": "ui-design-workbench-native-render-state",
        "repository": {"root": str(root.resolve())},
        "status": "pass" if detected else "not-applicable",
        "currentFidelityTier": "structural",
        "nativeExecutionStarted": False,
        "platforms": platforms,
        "providers": providers,
        "captures": [],
        "summary": {
            "detectedPlatforms": [item["platform"] for item in detected],
            "configuredProviders": [item["id"] for item in configured],
            "hostRequiredProviders": [item["id"] for item in host_required],
            "nativeCaptureCount": 0,
            "staleCaptureCount": 0,
        },
        "next": next_action,
    }


def native_render_status(root: Path, state_file: Path, platform: str = "all") -> dict[str, Any]:
    root = root.resolve()
    previous = load_native_state(state_file, root)
    discovered = discover_native_render(root)
    current_fingerprints = {
        item.get("platform"): item.get("sourceFingerprint")
        for item in discovered.get("platforms", [])
        if item.get("platform")
    }
    captures: list[dict[str, Any]] = []
    for original in previous.get("captures", []):
        capture = copy.deepcopy(original)
        platform_name = capture.get("platform")
        if capture.get("status") == "ready" and current_fingerprints.get(platform_name) != capture.get("sourceFingerprint"):
            capture["status"] = "stale"
        captures.append(capture)
    discovered["captures"] = captures
    discovered["summary"]["nativeCaptureCount"] = sum(1 for item in captures if item.get("status") == "ready")
    discovered["summary"]["staleCaptureCount"] = sum(1 for item in captures if item.get("status") == "stale")
    comparable_previous = {key: value for key, value in previous.items() if key != "cache"}
    cache_status = "reused" if comparable_previous == discovered else "updated" if state_file.is_file() else "created"
    discovered["cache"] = {"status": cache_status, "stateFile": str(state_file.resolve())}
    if cache_status != "reused":
        write_native_state(state_file, {key: value for key, value in discovered.items() if key != "cache"})
    if platform != "all":
        selected = copy.deepcopy(discovered)
        selected["platforms"] = [item for item in selected["platforms"] if item.get("platform") == platform]
        selected["providers"] = [item for item in selected["providers"] if item.get("platform") == platform]
        selected["captures"] = [item for item in selected["captures"] if item.get("platform") == platform]
        selected["summary"]["detectedPlatforms"] = [item for item in selected["summary"]["detectedPlatforms"] if item == platform]
        selected["summary"]["configuredProviders"] = [item["id"] for item in selected["providers"] if item.get("status") == "configured"]
        selected["summary"]["hostRequiredProviders"] = [item["id"] for item in selected["providers"] if item.get("status") == "host-required"]
        selected["summary"]["nativeCaptureCount"] = sum(1 for item in selected["captures"] if item.get("status") == "ready")
        selected["summary"]["staleCaptureCount"] = sum(1 for item in selected["captures"] if item.get("status") == "stale")
        selected["status"] = "pass" if selected["summary"]["detectedPlatforms"] else "not-applicable"
        return selected
    return discovered
