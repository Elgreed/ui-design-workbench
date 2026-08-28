# UI Design Workbench

[Русская версия](README.ru.md)

UI Design Workbench is a CLI-first UI analysis and design tool with a thin portable Agent Skill adapter. It reconstructs, generates, redesigns, and deeply reviews product interfaces from repository source code, producing an offline interactive HTML workbench without running the target app, emulator, simulator, build, or development server.

The repository UI remains the evidence source. The generated `ui-ir.json` is the editable design model; `ui-preview.html` is its standalone projection. Review and proposal jobs keep application source read-only. The explicit **Apply to project** or **Fix everything in project** action authorizes a separate implementation job that changes real UI source, runs incremental sync and targeted checks, and reports every finding in chat.

## What it provides

- Repository-aware discovery of screens, routes, logical views, navigation targets, components, tokens, fonts, and assets.
- Incremental, content-fingerprinted project context that avoids repeated repository-wide scans and reduces model context usage.
- Complete hierarchical screen tree with active-screen and navigation-target preview states.
- All screens, Prototype, Single screen, an optional per-screen States gallery, and a dedicated Compare workspace with explicit left/right versions plus split or overlay layouts.
- Deterministic synthetic fixtures with sparse, screen-specific scenarios and real repeated items for source-evidenced lists, tables, and grids; no universal loading/error/success set is stamped onto every screen.
- Stable shared-canvas zoom, middle-button drag panning, resizable/collapsible panels, inspect mode, and per-view finding/comment markers with separate colors and anchored popovers.
- A compact command rail with the File/menu trigger first, followed by Screens, Properties, Review, Comments, locale selection, and panel visibility.
- Runtime Russian/English workbench localization that never translates reconstructed product content.
- Evidence-based UI/UX review bound to the immutable Before version: selectors never retarget the audit, and baseline error markers never appear on After proposals.
- Sparse correction proposals that preserve an immutable Before baseline.
- Platform profiles for Android, Android TV, iOS/iPadOS, macOS, Windows, Web, React Native, and Flutter.
- Provider-neutral AI jobs plus an optional Codex deep-link adapter.

## Architecture: one CLI, thin agent adapters

The deterministic engine is the `uidw` CLI. It scans and caches source UI, builds the screen graph, renders the workbench, validates artifacts, and prepares portable AI jobs. `SKILL.md` is a small instruction adapter that teaches an AI agent when and how to call that engine. This separation keeps the generated IR and review behavior identical across agents.

Automatic skill discovery is convenient but not required. Any local coding agent can use UI Design Workbench when it can read files, run shell commands, and edit only the paths authorized by a prepared job. If a particular agent version does not discover skills, install only the CLI and use the generic prompt shown below.

## Installation by operating system

Prerequisites on every platform:

- Git and Python 3.10 or newer;
- `pipx` is recommended so the CLI is isolated and still available as `uidw`;
- Node.js plus Chrome, Edge, or Chromium is optional and only needed for headless interaction/geometry diagnostics.

### Windows 10/11 (PowerShell)

```powershell
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install .
.\install.ps1 -Agent all
```

Open a new terminal and a new agent session, then verify:

```powershell
uidw --version
uidw --json doctor
```

Replace `all` with one agent name to avoid unnecessary links. If PowerShell blocks local scripts, run the installer once with a process-only policy override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Agent codex
```

If `py` is unavailable, use `python`. A no-install fallback is `python scripts\uidw.py --help`.

### macOS

Install Python 3.10+ and Git using your preferred package manager, then run:

```sh
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install .
sh ./install.sh all
```

Open a new terminal and agent session, then run `uidw --version` and `uidw --json doctor`. A no-install fallback is `python3 scripts/uidw.py --help`.

### Linux

Install Python 3.10+, `python3-venv` when required by your distribution, and Git, then run:

```sh
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install .
sh ./install.sh all
```

Open a new shell and agent session, then run `uidw --version` and `uidw --json doctor`. A no-install fallback is `python3 scripts/uidw.py --help`.

When working through WSL, keep the repository, CLI, artifact directory, and browser on the same filesystem side when possible. A Linux `file:///` URL is not the same as a Windows file URL; use Windows Python for a Windows-hosted agent/browser or open the generated file from its translated Windows path.

Without `pipx`, `python -m pip install --user .` (Windows) or `python3 -m pip install --user .` (macOS/Linux) is supported. User-level script directories may need to be added to `PATH`.

## Connect an AI agent

The installer accepts `codex`, `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents`, or `all`. It creates a directory link to the clone and refuses to overwrite an existing installation.

| Agent | Installer selector | User skill location | Recommended invocation |
| --- | --- | --- | --- |
| Codex | `codex` | `~/.codex/skills/ui-design-workbench` | `Use $ui-design-workbench to ...` |
| Claude Code | `claude` | `~/.claude/skills/ui-design-workbench` | `Use ui-design-workbench; read its SKILL.md, then ...` |
| Cursor | `cursor` | `~/.cursor/skills/ui-design-workbench` | Use the same prompt in Agent mode |
| Gemini CLI | `gemini` | `~/.gemini/skills/ui-design-workbench` | Use the same prompt in the CLI session |
| GitHub Copilot CLI | `copilot` | `~/.copilot/skills/ui-design-workbench` | Use the same prompt in the CLI session |
| OpenCode | `opencode` | `~/.config/opencode/skills/ui-design-workbench` | Use the same prompt in the CLI session |
| Generic/local agent | `agents` | `~/.agents/skills/ui-design-workbench` | Point the agent to `SKILL.md` or use the generic contract below |

On Windows, `~` means `%USERPROFILE%`. Skill discovery varies by agent version and configuration; a created link does not guarantee that an agent will load it automatically. The authoritative integration paths and capability boundary are documented in [Agent integrations](references/agent-integrations.md).

For an agent without native skill discovery, add this compact rule to its project instructions or paste it at the start of a UI task:

```text
Use UI Design Workbench as the deterministic UI engine. Start with:
uidw --repo <repo> context --format json
Read only the compact context and relevant source files. Do not run the target app.
For reconstruction/review, keep project source read-only and work in a separate artifact directory.
Use provider-neutral ui-agent-job.json for proposal/review handoff. Edit real source only
when the user explicitly authorizes an apply job with sourceChangeAllowed: true.
```

Codex can additionally use the optional local deep-link adapter. All other agents use the copied prompt or `ui-agent-job.json`.

## Quick start

Ask your agent to use `ui-design-workbench` and specify a mode and scope, for example:

```text
Use ui-design-workbench to reconstruct every admin screen from this repository.
Do not run the app or edit source. Build a navigable HTML prototype and a complete screen tree.
```

```text
Use ui-design-workbench to run a deep UI/UX review of the assembled screens for Windows.
Test interactions, transient states, zoom, typography, spacing, accessibility, and platform fit.
Show evidence-backed Before/After corrections without changing application source.
```

```text
Use ui-design-workbench to redesign this Android TV browse screen using the existing design system,
TV Material, D-pad navigation, restored focus, ten-foot readability, and overscan-safe content.
```

Workbench controls are intentionally editor-like: hold the middle mouse button and drag to pan the full canvas; choose one active version for ordinary views; open the dedicated Compare view to select its left and right versions; enable or hide numbered Problems independently. Findings declared as resolved by a proposal disappear on that version while remaining visible on the immutable baseline. The language menu persists `Русский` or `English` and can also be selected with `?lang=ru` or `?lang=en`. Only workbench chrome is localized.

For the common local flow, one command synchronizes the cached source index, renders the workbench, runs deterministic checks, and returns a canonical `file:///` URL without starting a server:

```text
uidw --repo <repo> workbench --ir <review-dir>/ui-ir.json --output-dir <review-dir> --level full
uidw --repo <repo> open <review-dir>/ui-preview.html --launch --view prototype --lang en
```

## Optional UI guidance mode

`uidw init` explains and offers a lightweight UI guidance mode. The default answer is **No**, and non-interactive/JSON initialization also keeps it off unless explicitly enabled:

```text
uidw --repo <repo> init --ui-mode
uidw --repo <repo> init --no-ui-mode
uidw --repo <repo> ui-mode
uidw --repo <repo> ui-mode --enable
uidw --repo <repo> ui-mode --disable
```

Initialization can also opt into mock data. The default is `none`; `representative` creates one realistic populated fixture plus only critical states justified by each screen, while `exhaustive` adds evidenced boundary states:

```text
uidw --repo <repo> init --mock-data representative
uidw --repo <repo> mock-data --set representative --seed qa
uidw --repo <repo> scenarios validate --ir <review-dir>/ui-ir.json
```

Populated collection fixtures use separate synthetic item nodes rather than replacing an empty list with one descriptive text line. `scenarios validate` fails when a `mock-data` scenario leaves a declared data-driven collection empty.

When enabled, the compact project context tells compatible agents to use existing project components and the detected Android, Android TV, iOS/iPadOS, macOS, Windows, or Web conventions during ordinary UI implementation tasks. It checks only relevant platform, accessibility, state, input, and adaptive-layout concerns. It does **not** automatically start an audit, redesign, HTML preview, emulator, or application run.

The setting is stored per project in the same user cache as the UI index by default. Switching it refreshes only compact context and does not rescan unchanged UI source. Use `init --project-cache` only when the project intentionally needs portable ignored configuration.

## Efficient project context

Agents should start with:

```text
uidw --repo <repo> context --format json
```

The first call builds the UI inventory. Later calls compare candidate fingerprints and analyze only added or content-modified files. The returned compact context tells the agent which source files matter. A bounded screen context is available with:

```text
uidw --repo <repo> context --screen <screen-id> --format json
uidw --repo <repo> context --screen <screen-id> --budget 4000 --format markdown
uidw --repo <repo> context --changed-only --budget 2500
```

Useful commands:

```text
uidw --repo <repo> init
uidw --json --repo <repo> status
uidw --repo <repo> sync
uidw --repo <repo> sync --force
uidw --repo <repo> map --output <artifact-dir>/ui-graph.json
uidw --repo <repo> diff
uidw --repo <repo> check --ir <review-dir>/ui-ir.json --level quick
uidw --repo <repo> workbench --ir <review-dir>/ui-ir.json --output-dir <review-dir>
uidw --json --repo <repo> doctor
uidw --repo <repo> ui-mode
```

By default, derived state is stored in the OS user cache, never in the installed skill or source repository. `init --project-cache` is an explicit CI/portable-mode opt-in and creates an ignored `.ui-design-workbench` directory. See [Cache protocol](references/cache-protocol.md).

| Platform | Default cache root |
| --- | --- |
| Windows | `%LOCALAPPDATA%\UI Design Workbench\Cache\projects` |
| macOS | `~/Library/Caches/ui-design-workbench/projects` |
| Linux | `${XDG_CACHE_HOME:-~/.cache}/ui-design-workbench/projects` |

Set `UIDW_CACHE_HOME` to override the user cache root. Do not put generated cache files inside the installed skill directory.

## Review artifact workflow

1. The agent reads compact cached context and only the necessary project UI sources.
2. It creates a separate review directory with `ui-ir.json`.
3. It reconstructs the immutable baseline or records a generated/redesigned version with explicit evidence.
4. It renders `ui-preview.html` and runs strict coverage/platform checks.
5. For review work, it runs interaction, state, typography, geometry, accessibility, and UX passes across declared screens and profiles.
6. The user selects findings, compares correction proposals, comments, and accepts or rejects a design version.
7. The safe path applies an approved proposal to the project; the fast path fixes all findings directly. Both are explicit source-edit actions. The agent updates real source and existing finding statuses, runs incremental sync plus targeted checks, and returns a numbered chat report. A second full AI review is never automatic.

Render a completed IR:

```text
uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html
```

The default handoff copies or downloads a provider-neutral job. For Codex only, opt into its local task adapter:

```text
uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html --agent codex
```

The same lifecycle is available directly from the CLI. These commands only prepare or import portable files; they never invoke a provider or silently edit application source:

```text
uidw findings list --ir <review-dir>/ui-ir.json --screen settings
uidw findings accept 7 25 --ir <review-dir>/ui-ir.json
uidw proposal prepare --ir <review-dir>/ui-ir.json
uidw apply prepare --ir <review-dir>/ui-ir.json
uidw review prepare --ir <review-dir>/ui-ir.json
uidw review import <result.json> --ir <review-dir>/ui-ir.json --output <review-dir>/ui-ir.imported.json
```

`apply prepare` is the only command that creates a source-enabled job. It requires accepted findings with verified source targets inside the selected repository. It still does not execute the job.

## Deep review contract

A complete review is not a screenshot critique. It must separately cover:

- information architecture, discoverability, action placement, icon meaning/style, density, feedback, progressive disclosure, adaptive behavior, and platform fit;
- single, reverse, repeated, chained, boundary, and intermediate transitions, including cross-control state synchronization;
- menus, popovers, dialogs, panels, navigation, history, focus, persistence, scroll bounds, and shared-canvas zoom;
- typography roles, baselines, four-side padding, icon-label gaps, containment, wrapping, clipping, overflow, and optical alignment;
- primary and compact viewports, zoom boundaries, long localization, text scaling, themes, input methods, and relevant product states;
- semantic/accessibility behavior and platform-specific conventions.

Every problem must have stable evidence, user impact, recommendation, severity, confidence, a source target, a standards/project basis, and a linked proposal or explicit reason why no visual proposal is responsible.

## Validation

The production gate includes:

```text
python <skill-dir>/scripts/validate_platform_profiles.py <review-dir>/ui-ir.json --output <review-dir>/platform-profile-report.json --strict
python <skill-dir>/scripts/coverage_report.py <review-dir>/ui-ir.json --output <review-dir>/ui-coverage.json --strict
python <skill-dir>/scripts/generate_interaction_matrix.py <review-dir>/ui-ir.json --output <review-dir>/ui-interaction-matrix.json
node <skill-dir>/scripts/smoke_preview.js <review-dir>/ui-preview.html --output <review-dir>/ui-diagnostics.json
```

The consolidated equivalents are:

```text
uidw check --ir <review-dir>/ui-ir.json --level quick --format sarif
uidw check --ir <review-dir>/ui-ir.json --level full --format junit
uidw visual-test --baseline approved.png --candidate current.png --output-dir <review-dir>/visual
uidw pack --ir <review-dir>/ui-ir.json --output review.uidw.zip
uidw unpack review.uidw.zip --output-dir <portable-review-dir>
```

Visual regression is allowed only against an explicitly approved baseline captured at the same viewport/state. A successful command is not automatically a passing report; every non-pass result must be fixed or retained as a named blocker/gap. See [Delivery validation](references/validation.md) and [Quality automation](references/quality-automation.md).

## Repository structure

```text
SKILL.md                       Agent-facing workflow
agents/openai.yaml             Optional Codex metadata
install.ps1 / install.sh       Multi-agent installers
references/                    Platform, review, IR, cache, and validation contracts
scripts/uidw.py                Incremental project-context CLI
scripts/scan_ui.py             Source discovery and per-file analysis
scripts/render_preview.py      Standalone HTML renderer
scripts/smoke_preview.js       Headless interaction/geometry diagnostics
scripts/*                      Coverage, profiles, scenarios, merge, regression, tests
```

## Requirements

- Python 3.10 or newer.
- An agent with local filesystem and shell access.
- Node.js plus Chrome, Edge, or Chromium only for headless diagnostics.
- Pillow only for pixel regression.

No target runtime, emulator, localhost service, or network request is needed for the generated preview.

## Version

The repository has the `v0.1` initial public release tag. The current CLI development version is `0.2.0`.
