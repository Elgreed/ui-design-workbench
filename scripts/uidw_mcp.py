#!/usr/bin/env python3
"""Optional local stdio MCP facade over the deterministic UIDW CLI core."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import uidw
from native_render_registry import native_render_status
from scoped_context import apply_patch_file, build_scoped_context


SERVER_INSTRUCTIONS = (
    "Start with ui_project, then call ui_scope for one screen or a small finding set. "
    "If ui_project returns setupRequired, ask the user only for low, medium, or high, then call "
    "ui_configure with that choice before continuing. "
    "Do not request or embed the complete UI IR when bounded context is sufficient. "
    "ui_scope returns compact provenance by default; call ui_fidelity only for nodes that need full evidence. "
    "Reuse scopeHash through if_none_match before requesting the same scope again. "
    "Use ui_prepare_job for review, proposal, or implementation handoffs. Review and proposal work "
    "must preserve immutable baseline UI and return sparse ui-ir.patch.json operations; application "
    "source changes require an explicit implementation request. Use ui_build_preview for projection "
    "checks only; do not infer UI/UX findings unless the user explicitly requests a review. "
    "For Android or Apple visual accuracy, call ui_native_status and never describe source projection as a native render. "
    "Native builds, simulators, and captures are explicit-only operations."
)


def _root(value: str | None, default: Path) -> Path:
    path = Path(value).expanduser().resolve() if value else default.resolve()
    if not path.is_dir():
        raise ValueError(f"Repository directory does not exist: {path}")
    return path


def _ir(root: Path, value: str | None) -> tuple[Path, dict[str, Any]]:
    return uidw.load_ir_argument(uidw.state_paths(root), Path(value).expanduser() if value else None)


def project_summary(repo: str | None, default_repo: Path) -> dict[str, Any]:
    root = _root(repo, default_repo)
    initialization, paths, config = uidw.ensure_initialized(root)
    ir = uidw.load_project_ir(paths) or {}
    configuration = uidw.configuration_context(config)
    setup_required = bool(configuration.get("setupRequired"))
    return {
        "cliVersion": uidw.CLI_VERSION,
        "status": initialization.get("status"),
        "cache": initialization.get("initialization", {}).get("status"),
        "repoRoot": "<project-root>",
        "uiIrFile": paths["ir"].name,
        "contextFile": paths["context"].name,
        "screens": [{"id": item.get("id"), "name": item.get("name"), "platform": item.get("platform")} for item in ir.get("screens", [])],
        "findingCount": len(ir.get("review", {}).get("audit", {}).get("findings", [])),
        "setupRequired": setup_required,
        "detailLevel": configuration.get("detailLevel"),
        "detailChoices": ["low", "medium", "high"] if setup_required else [],
        "questionsForUser": configuration.get("questionsForUser", []),
        "uiModeEnabled": bool(config.get(uidw.UI_MODE_KEY, {}).get("enabled")),
        "next": (
            "Ask the user to choose low, medium, or high, then call ui_configure."
            if setup_required
            else "Use ui_scope for one screen or a small finding set; do not read the full IR."
        ),
    }


def scoped_payload(
    repo: str | None,
    default_repo: Path,
    ui_ir_file: str | None,
    screen_ids: list[str],
    finding_ids: list[str],
    max_tokens: int,
    provenance_mode: str = "summary",
    if_none_match: str | None = None,
) -> dict[str, Any]:
    root = _root(repo, default_repo)
    ir_path, ir = _ir(root, ui_ir_file)
    return build_scoped_context(
        ir,
        screen_ids=screen_ids,
        finding_ids=finding_ids,
        token_budget=max_tokens,
        ui_ir_file=str(ir_path),
        provenance_mode=provenance_mode,
        if_none_match=if_none_match,
    )


def compact_workbench_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: result.get(key)
        for key in ("version", "status", "previewFile", "url", "workflow", "initialization")
        if result.get(key) is not None
    }
    compact["cliVersion"] = uidw.CLI_VERSION
    check = result.get("check")
    if isinstance(check, dict):
        compact["check"] = {
            "status": check.get("status"),
            "level": check.get("level"),
            "checks": {
                key: {
                    "status": value.get("status"),
                    **({"issues": value.get("issues")} if value.get("issues") else {}),
                    **({"errors": value.get("errors")} if value.get("errors") else {}),
                }
                for key, value in check.get("checks", {}).items()
                if isinstance(value, dict)
            },
        }
    return compact


def configure_detail(repo: str | None, default_repo: Path, detail: str) -> dict[str, Any]:
    root = _root(repo, default_repo)
    normalized = detail.strip().lower()
    if normalized not in {"low", "medium", "high"}:
        return {
            "status": "blocked",
            "error": "detail must be low, medium, or high",
            "detailChoices": ["low", "medium", "high"],
        }
    result = uidw.configure_project(root, "set", "detail", normalized)
    configuration = result.get("configuration", {})
    return {
        "status": result.get("status"),
        "repoRoot": "<project-root>",
        "setupRequired": bool(configuration.get("setupRequired")),
        "detailLevel": configuration.get("detailLevel"),
        "mockData": configuration.get(uidw.MOCK_DATA_KEY),
        "contextFile": result.get("contextFile"),
        "next": "Use ui_scope, then ui_build_preview when the requested screens are ready.",
    }


def build_preview(
    repo: str | None,
    default_repo: Path,
    ui_ir_file: str | None,
    output_dir: str | None,
    level: str,
) -> dict[str, Any]:
    root = _root(repo, default_repo)
    paths = uidw.state_paths(root)
    configuration = uidw.configuration_context(uidw.load_config(paths["config"]))
    if configuration.get("setupRequired"):
        return {
            "status": "needs-setup",
            "setupRequired": True,
            "detailChoices": ["low", "medium", "high"],
            "questionsForUser": configuration.get("questionsForUser", []),
            "next": "Ask the user to choose low, medium, or high, then call ui_configure.",
        }

    ir_path, _ = _ir(root, ui_ir_file)
    destination = Path(output_dir).expanduser().resolve() if output_dir else ir_path.parent / "workbench"
    allow_draft = False
    try:
        result = uidw.build_workbench(
            root,
            ir_path,
            destination,
            level,
            allow_draft,
            "generic",
            False,
            None,
            None,
            None,
            None,
            None,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        return {
            "status": "blocked",
            "error": str(exc),
            "uiIrFile": str(ir_path),
            "next": "Resolve the reported IR or fidelity problem, then call ui_build_preview again.",
        }
    return compact_workbench_result(result)


def create_server(default_repo: Path, name: str = "UI Design Workbench") -> Any:
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "MCP support is optional. Install it with `pip install \"ui-design-workbench-cli[mcp]\"` "
            "or `pip install \"mcp>=2,<3\"`. The regular uidw CLI does not require it."
        ) from exc

    server = MCPServer(
        name,
        version=uidw.CLI_VERSION,
        instructions=SERVER_INSTRUCTIONS,
    )

    @server.tool()
    def ui_project(repo: str = "") -> dict[str, Any]:
        """Get a compact cached UI catalog and the next bounded action."""
        return project_summary(repo or None, default_repo)

    @server.tool()
    def ui_configure(detail: str, repo: str = "") -> dict[str, Any]:
        """Set the required low, medium, or high preview detail after the user chooses it."""
        return configure_detail(repo or None, default_repo, detail)

    @server.tool()
    def ui_scope(
        screen_ids: list[str],
        finding_ids: list[str],
        repo: str = "",
        ui_ir_file: str = "",
        max_tokens: int = 4000,
        provenance_mode: str = "summary",
        if_none_match: str = "",
    ) -> dict[str, Any]:
        """Read bounded UI structure; fetch full evidence only when explicitly requested."""
        return scoped_payload(
            repo or None,
            default_repo,
            ui_ir_file or None,
            screen_ids,
            finding_ids,
            max_tokens,
            provenance_mode,
            if_none_match or None,
        )

    @server.tool()
    def ui_prepare_job(
        kind: str,
        finding_ids: list[str],
        repo: str = "",
        ui_ir_file: str = "",
        output_file: str = "",
        scope: str = "current",
        direct: bool = False,
    ) -> dict[str, Any]:
        """Prepare a portable bounded job plus context and ui-ir.patch.json."""
        root = _root(repo or None, default_repo)
        ir_path, ir = _ir(root, ui_ir_file or None)
        if kind not in {"expert", "proposal", "implementation"}:
            raise ValueError("kind must be expert, proposal, or implementation")
        output = Path(output_file).expanduser().resolve() if output_file else ir_path.parent / f"ui-agent-job-{kind}.json"
        return uidw.prepare_agent_job(root, ir_path, ir, kind, output, identifiers=finding_ids, scope=scope, direct=direct)

    @server.tool()
    def ui_apply_patch(
        patch_file: str,
        repo: str = "",
        ui_ir_file: str = "",
        output_file: str = "",
    ) -> dict[str, Any]:
        """Validate and apply sparse review/proposal operations without touching baseline UI."""
        root = _root(repo or None, default_repo)
        ir_path, _ = _ir(root, ui_ir_file or None)
        output = Path(output_file).expanduser().resolve() if output_file else ir_path.with_name("ui-ir.patched.json")
        return apply_patch_file(ir_path, Path(patch_file).expanduser(), output)

    @server.tool()
    def ui_build_preview(
        repo: str = "",
        ui_ir_file: str = "",
        output_dir: str = "",
        level: str = "quick",
    ) -> dict[str, Any]:
        """Render and projection-check the HTML workbench; never auto-review UX."""
        return build_preview(repo or None, default_repo, ui_ir_file or None, output_dir or None, level)

    @server.tool()
    def ui_native_status(repo: str = "", platform: str = "all") -> dict[str, Any]:
        """Discover native Android/Apple render providers without executing builds or simulators."""
        if platform not in {"all", "android", "apple"}:
            raise ValueError("platform must be all, android, or apple")
        root = _root(repo or None, default_repo)
        return native_render_status(root, uidw.state_paths(root)["native"], platform)

    @server.tool()
    def ui_fidelity(identifier: str, repo: str = "", ui_ir_file: str = "") -> dict[str, Any]:
        """Explain one node/evidence id without returning the complete IR."""
        root = _root(repo or None, default_repo)
        _, ir = _ir(root, ui_ir_file or None)
        return uidw.fidelity_command(ir, "explain", identifier, None, "json")

    return server


def run_server(default_repo: Path, name: str = "UI Design Workbench") -> None:
    create_server(default_repo, name).run()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local stdio MCP server for UI Design Workbench")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--name", default="UI Design Workbench")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        run_server(args.repo.resolve(), args.name)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"uidw mcp: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
