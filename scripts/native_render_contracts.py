#!/usr/bin/env python3
"""Provider-neutral contracts for opt-in native UI rendering.

Native artifacts are deliberately stored outside the baseline UI IR. Source
adapters may reconstruct structure, but only a native provider can supply
evidence for pixel appearance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol


NATIVE_STATE_SCHEMA_VERSION = 1
CAPTURE_STATUSES = {"ready", "blocked", "failed", "stale"}
PROVIDER_STATUSES = {"configured", "available", "not-configured", "host-required", "not-applicable"}
NATIVE_FIDELITY_TIERS = {"native-preview", "device-verified"}


def _relative_artifact(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("native artifact reference must not be empty")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError(f"native artifact reference must be relative: {value}")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise ValueError(f"native artifact reference escapes its bundle: {value}")
    return "/".join(parts)


@dataclass(frozen=True)
class NativeRenderRequest:
    provider_id: str
    platform: str
    screen_id: str
    state_id: str = "default"
    variant: str = "default"
    viewport: dict[str, Any] = field(default_factory=dict)
    locale: str = ""
    theme: str = ""

    def cache_key(self, source_fingerprint: str, provider_version: str = "") -> str:
        payload = {
            **asdict(self),
            "sourceFingerprint": source_fingerprint,
            "providerVersion": provider_version,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NativeRenderProvider(Protocol):
    id: str
    platforms: tuple[str, ...]

    def discover(self, root: Path) -> dict[str, Any]: ...

    def capture(self, root: Path, request: NativeRenderRequest, output_dir: Path) -> dict[str, Any]: ...


def empty_native_state(repo_root: Path) -> dict[str, Any]:
    return {
        "schemaVersion": NATIVE_STATE_SCHEMA_VERSION,
        "type": "ui-design-workbench-native-render-state",
        "repository": {"root": str(repo_root.resolve())},
        "status": "not-applicable",
        "currentFidelityTier": "structural",
        "nativeExecutionStarted": False,
        "platforms": [],
        "providers": [],
        "captures": [],
    }


def validate_native_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("schemaVersion") != NATIVE_STATE_SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {NATIVE_STATE_SCHEMA_VERSION}")
    if state.get("type") != "ui-design-workbench-native-render-state":
        errors.append("type must be ui-design-workbench-native-render-state")
    if state.get("nativeExecutionStarted") not in {True, False}:
        errors.append("nativeExecutionStarted must be boolean")
    providers = state.get("providers", [])
    if not isinstance(providers, list):
        errors.append("providers must be an array")
        providers = []
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            errors.append(f"providers[{index}] must be an object")
            continue
        if not provider.get("id") or not provider.get("platform"):
            errors.append(f"providers[{index}] requires id and platform")
        if provider.get("status") not in PROVIDER_STATUSES:
            errors.append(f"providers[{index}].status is invalid")
    captures = state.get("captures", [])
    if not isinstance(captures, list):
        errors.append("captures must be an array")
        captures = []
    for index, capture in enumerate(captures):
        if not isinstance(capture, dict):
            errors.append(f"captures[{index}] must be an object")
            continue
        for key in ("id", "providerId", "platform", "screenId", "sourceFingerprint"):
            if not capture.get(key):
                errors.append(f"captures[{index}].{key} is required")
        if capture.get("status") not in CAPTURE_STATUSES:
            errors.append(f"captures[{index}].status is invalid")
        if capture.get("fidelityTier") not in NATIVE_FIDELITY_TIERS:
            errors.append(f"captures[{index}].fidelityTier is invalid")
        for key in ("image", "semantics", "geometry"):
            value = capture.get("artifacts", {}).get(key) if isinstance(capture.get("artifacts"), dict) else None
            if value:
                try:
                    _relative_artifact(str(value))
                except ValueError as exc:
                    errors.append(f"captures[{index}].artifacts.{key}: {exc}")
        if capture.get("status") == "ready" and not isinstance(capture.get("artifacts"), dict):
            errors.append(f"captures[{index}].artifacts is required for a ready capture")
    return errors


def load_native_state(path: Path, repo_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_native_state(repo_root)
    return payload if isinstance(payload, dict) and not validate_native_state(payload) else empty_native_state(repo_root)


def write_native_state(path: Path, state: dict[str, Any]) -> None:
    errors = validate_native_state(state)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

