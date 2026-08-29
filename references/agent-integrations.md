# Agent integrations

The repository follows the open Agent Skills layout: one `SKILL.md` plus `scripts/`, `references/`, and optional agent-specific metadata. The core workflow communicates through files and shell commands, not a proprietary API.

## Discovery locations

`~/.agents/skills/ui-design-workbench` is the preferred portable installation where supported. Native locations are also available:

| Agent | Native user location |
| --- | --- |
| Codex | `~/.codex/skills/ui-design-workbench` |
| Claude Code | `~/.claude/skills/ui-design-workbench` |
| Cursor | `~/.cursor/skills/ui-design-workbench` |
| Gemini CLI | `~/.gemini/skills/ui-design-workbench` |
| GitHub Copilot CLI | `~/.copilot/skills/ui-design-workbench` |
| OpenCode | `~/.config/opencode/skills/ui-design-workbench` |

Install the published CLI and then copy its packaged Agent Skill into any supported discovery location:

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

Use `uidw install-skill all` for every supported location. Repeating the command refreshes UIDW-managed copies after a CLI upgrade and refuses to overwrite an unrelated existing skill. The packaged skill includes its references, schemas, and CLI fallback scripts, so it does not depend on a Git checkout.

For contributor checkouts, `./install.ps1 -Agent all` on Windows or `./install.sh all` on macOS/Linux still creates development links to the repository. Repository-local installation can use `.agents/skills/ui-design-workbench` when team policy prefers checked-out skills.

## Capability contract

An agent needs local file read/write access and Python 3.10+. Node.js plus Chromium/Edge is optional but required for headless interaction and geometry diagnostics. The target application, emulator, simulator, bridge server, and internet access are not required.

The portable handoff is `ui-agent-job.json`. It contains artifact directory, review scope, selected stable finding IDs, screen IDs, active/baseline versions, annotations, allowed output patterns, and `sourceChangeAllowed: false`. It also points to a bounded `ui-agent-context.json` and a sparse `ui-ir.patch.json`; the agent reads the bounded context and returns patch operations instead of loading or replacing the complete IR. Agents must modify only the declared review artifacts and return validation results.

For ordinary source tasks, `uidw init` can opt a project into lightweight UI guidance. The mode is off by default and appears in `ui-context.json` as `uiMode`. A compatible agent loads only the relevant platform guidance, preserves the project's components and tokens, and stays within the requested implementation scope. This is independent of the review handoff and must not create a workbench or claim a full audit unless requested.

Codex may opt into `render_preview.py --agent codex`, which enables the official local `codex://new` preparation path. Other agents use copied prompts or the JSON job. Provider-specific adapters are optional presentation conveniences and must not change the IR, cache, review semantics, permissions, or approval boundary.

The optional `uidw-mcp` stdio server is a transport facade over the same deterministic CLI core. It exposes compact project discovery, strictly bounded screen/finding context, job preparation, sparse patch application, preview building, and on-demand fidelity explanation. Scoped nodes omit full source expressions by default and expose a stable `scopeHash`; pass it back as `if_none_match` before repeating the same request. MCP is an optional dependency; installing or running the regular CLI must not require it. Configure an agent to launch `uidw-mcp --repo <absolute-project-path>` as a local stdio command; it opens no port and keeps project caches on the local machine. Selected model-facing context is still visible to the host agent and should be treated as derived source data.
