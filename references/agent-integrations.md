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

Run `./install.ps1 -Agent all` on Windows or `./install.sh all` on macOS/Linux from a clone. The installers create links and refuse to overwrite an existing installation. Repository-local installation can use `.agents/skills/ui-design-workbench` when team policy prefers checked-out skills.

Install the deterministic engine separately with `pipx install .` (preferred) or `python -m pip install --user .`. This exposes the `uidw` command. A skill can fall back to `python <skill-dir>/scripts/uidw.py` when the CLI is not installed.

## Capability contract

An agent needs local file read/write access and Python 3.10+. Node.js plus Chromium/Edge is optional but required for headless interaction and geometry diagnostics. The target application, emulator, simulator, bridge server, and internet access are not required.

The portable handoff is `ui-agent-job.json`. It contains artifact directory, review scope, selected stable finding IDs, screen IDs, active/baseline versions, annotations, allowed output patterns, and `sourceChangeAllowed: false`. Agents must modify only the declared review artifacts and return validation results.

For ordinary source tasks, `uidw init` can opt a project into lightweight UI guidance. The mode is off by default and appears in `ui-context.json` as `uiMode`. A compatible agent loads only the relevant platform guidance, preserves the project's components and tokens, and stays within the requested implementation scope. This is independent of the review handoff and must not create a workbench or claim a full audit unless requested.

Codex may opt into `render_preview.py --agent codex`, which enables the official local `codex://new` preparation path. Other agents use copied prompts or the JSON job. Provider-specific adapters are optional presentation conveniences and must not change the IR, cache, review semantics, permissions, or approval boundary.
