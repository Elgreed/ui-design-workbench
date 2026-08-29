#!/usr/bin/env python3
"""Optional local stdio MCP facade over the deterministic UIDW CLI core."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import uidw
from scoped_context import apply_patch_file, build_scoped_context


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
    return {
        "status": initialization.get("status"),
        "cache": initialization.get("initialization", {}).get("status"),
        "repoRoot": str(root),
        "uiIrFile": str(paths["ir"]),
        "contextFile": str(paths["context"]),
        "screens": [{"id": item.get("id"), "name": item.get("name"), "platform": item.get("platform")} for item in ir.get("screens", [])],
        "findingCount": len(ir.get("review", {}).get("audit", {}).get("findings", [])),
        "detailLevel": config.get(uidw.DETAIL_KEY),
        "uiModeEnabled": bool(config.get(uidw.UI_MODE_KEY, {}).get("enabled")),
        "next": "Use ui_scope for one screen or a small finding set; do not read the full IR.",
    }


def scoped_payload(
    repo: str | None,
    default_repo: Path,
    ui_ir_file: str | None,
    screen_ids: list[str],
    finding_ids: list[str],
    max_tokens: int,
) -> dict[str, Any]:
    root = _root(repo, default_repo)
    ir_path, ir = _ir(root, ui_ir_file)
    return build_scoped_context(
        ir,
        screen_ids=screen_ids,
        finding_ids=finding_ids,
        token_budget=max_tokens,
        ui_ir_file=str(ir_path),
    )


def compact_workbench_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in ("version", "status", "previewFile", "url", "workflow", "initialization")
        if result.get(key) is not None
    }


def create_server(default_repo: Path, name: str = "UI Design Workbench") -> Any:
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "MCP support is optional. Install it with `pip install \"ui-design-workbench-cli[mcp]\"` "
            "or `pip install \"mcp>=2,<3\"`. The regular uidw CLI does not require it."
        ) from exc

    server = MCPServer(name)

    @server.tool()
    def ui_project(repo: str = "") -> dict[str, Any]:
        """Get a compact cached UI catalog and the next bounded action."""
        return project_summary(repo or None, default_repo)

    @server.tool()
    def ui_scope(
        screen_ids: list[str],
        finding_ids: list[str],
        repo: str = "",
        ui_ir_file: str = "",
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Read complete UI evidence only for named screens/findings."""
        return scoped_payload(repo or None, default_repo, ui_ir_file or None, screen_ids, finding_ids, max_tokens)

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
        root = _root(repo or None, default_repo)
        ir_path, _ = _ir(root, ui_ir_file or None)
        destination = Path(output_dir).expanduser().resolve() if output_dir else ir_path.parent / "workbench"
        result = uidw.build_workbench(root, ir_path, destination, level, False, "generic", False, None, None, None, None, None)
        return compact_workbench_result(result)

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
