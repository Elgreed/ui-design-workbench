#!/usr/bin/env python3
"""Stable provider-neutral API for deterministic source-to-IR adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceContext:
    root: Path
    path: Path
    source: str
    text: str
    platforms: tuple[str, ...]
    role: str


@dataclass
class AdapterResult:
    adapter: str
    screens: list[dict[str, Any]] = field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    tokens: dict[str, dict[str, Any]] = field(default_factory=lambda: {"colors": {}, "spacing": {}, "radii": {}, "typography": {}})
    themes: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)


class UiSourceAdapter(Protocol):
    id: str

    def supports(self, context: SourceContext) -> bool: ...
    def translate(self, context: SourceContext) -> AdapterResult: ...


_ADAPTERS: list[UiSourceAdapter] = []


def register_adapter(adapter: UiSourceAdapter) -> None:
    if any(current.id == adapter.id for current in _ADAPTERS):
        raise ValueError(f"Adapter already registered: {adapter.id}")
    _ADAPTERS.append(adapter)


def registered_adapters() -> tuple[UiSourceAdapter, ...]:
    return tuple(_ADAPTERS)


def adapter_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "id": adapter.id,
            "platforms": list(getattr(adapter, "platforms", ())),
            "extensions": list(getattr(adapter, "extensions", ())),
            "maturity": str(getattr(adapter, "maturity", "conservative")),
            "structuralTier": str(getattr(adapter, "structural_tier", "translated")),
            "visualTier": str(getattr(adapter, "visual_tier", "none")),
            "nativeEvidenceRequired": bool(getattr(adapter, "native_evidence_required", False)),
            "nativeProviders": list(getattr(adapter, "native_providers", ())),
            "resourceResolution": list(getattr(adapter, "resource_resolution", ())),
            "layoutFeatures": list(getattr(adapter, "layout_features", ())),
            "limitations": list(getattr(adapter, "limitations", ())),
        }
        for adapter in _ADAPTERS
    ]


def translate_sources(contexts: list[SourceContext]) -> AdapterResult:
    combined = AdapterResult(adapter="registry")
    for adapter in _ADAPTERS:
        prepare = getattr(adapter, "prepare", None)
        if callable(prepare):
            prepare(contexts)
    for context in contexts:
        adapter = next((candidate for candidate in _ADAPTERS if candidate.supports(context)), None)
        if adapter is None:
            continue
        result = adapter.translate(context)
        combined.screens.extend(result.screens)
        combined.nodes.update(result.nodes)
        for group, values in result.tokens.items():
            combined.tokens.setdefault(group, {}).update(values if isinstance(values, dict) else {})
        combined.themes.extend(result.themes)
        combined.components.extend(result.components)
        combined.unsupported.extend(result.unsupported)
    return combined
