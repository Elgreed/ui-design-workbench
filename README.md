# UI Design Workbench

[Русская версия](README.ru.md)

UI Design Workbench is a CLI-first UI analysis and design tool with a thin portable Agent Skill adapter. It reconstructs, generates, redesigns, and deeply reviews product interfaces from repository source code, producing an offline interactive HTML workbench without running the target app, emulator, simulator, build, or development server.

The repository UI remains the evidence source. The generated `ui-ir.json` is the editable design model; `ui-preview.html` is its standalone projection. Application source stays read-only until the user separately approves a concrete implementation diff.

## What it provides

- Repository-aware discovery of screens, routes, logical views, navigation targets, components, tokens, fonts, and assets.
- Incremental, content-fingerprinted project context that avoids repeated repository-wide scans and reduces model context usage.
- Complete hierarchical screen tree with active-screen and navigation-target preview states.
- All screens, Prototype, Single screen, and a dedicated Compare workspace with explicit left/right versions plus split or overlay layouts.
- Stable shared-canvas zoom, middle-button drag panning, resizable/collapsible panels, inspect mode, and per-view finding/comment markers with separate colors and anchored popovers.
- A compact command rail for Screens, Properties, Review, Comments, File actions, locale selection, and panel visibility.
- Runtime Russian/English workbench localization that never translates reconstructed product content.
- Evidence-based UI/UX review with deterministic interaction/geometry diagnostics and separate expert UX assessment.
- Sparse correction proposals that preserve an immutable Before baseline.
- Platform profiles for Android, Android TV, iOS/iPadOS, macOS, Windows, Web, React Native, and Flutter.
- Provider-neutral AI jobs plus an optional Codex deep-link adapter. No bridge server or open port.

## Supported agents

The skill follows the open Agent Skills layout and uses only files, Python, and optional local browser diagnostics. It can be discovered by Codex, Claude Code, Cursor, Gemini CLI, GitHub Copilot CLI, OpenCode, and other Agent Skills-compatible tools.

Clone the repository, then install links from that clone:

```powershell
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
./install.ps1 -Agent all
```

```sh
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
./install.sh all
```

You can replace `all` with `codex`, `claude`, `cursor`, `gemini`, `copilot`, `opencode`, or `agents`. The installers create directory links and refuse to overwrite an existing installation. Restart the selected agent or open a new session after installation.

Install the standalone CLI from the same clone (prefer `pipx` for isolation):

```text
pipx install .
uidw --version
```

Without `pipx`, `python -m pip install --user .` is supported. The bundled `python scripts/uidw.py ...` entry point remains available without installation.

The preferred portable location is `~/.agents/skills/ui-design-workbench`; native locations are listed in [Agent integrations](references/agent-integrations.md).

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

## Optional UI guidance mode

`uidw init` explains and offers a lightweight UI guidance mode. The default answer is **No**, and non-interactive/JSON initialization also keeps it off unless explicitly enabled:

```text
uidw --repo <repo> init --ui-mode
uidw --repo <repo> init --no-ui-mode
uidw --repo <repo> ui-mode
uidw --repo <repo> ui-mode --enable
uidw --repo <repo> ui-mode --disable
```

When enabled, the compact project context tells compatible agents to use existing project components and the detected Android, Android TV, iOS/iPadOS, macOS, Windows, or Web conventions during ordinary UI implementation tasks. It checks only relevant platform, accessibility, state, input, and adaptive-layout concerns. It does **not** automatically start an audit, redesign, HTML preview, emulator, or application run.

The setting is stored per project in the same user cache as the UI index by default. Switching it refreshes only compact context and does not rescan unchanged UI source. Use `init --project-cache` only when the project intentionally needs portable ignored configuration.

## Efficient project context

Agents should start with:

```text
uidw --repo <repo> context --json
```

The first call builds the UI inventory. Later calls compare candidate fingerprints and analyze only added or content-modified files. The returned compact context tells the agent which source files matter. A bounded screen context is available with:

```text
uidw --repo <repo> context --screen <screen-id> --json
```

Useful commands:

```text
uidw --repo <repo> init
uidw --repo <repo> status --json
uidw --repo <repo> sync
uidw --repo <repo> sync --force
uidw --repo <repo> map --output <artifact-dir>/ui-graph.json
uidw --repo <repo> doctor --json
uidw --repo <repo> ui-mode
```

By default, derived state is stored in the OS user cache, never in the installed skill or source repository. `init --project-cache` is an explicit CI/portable-mode opt-in and creates an ignored `.ui-design-workbench` directory. See [Cache protocol](references/cache-protocol.md).

## Review artifact workflow

1. The agent reads compact cached context and only the necessary project UI sources.
2. It creates a separate review directory with `ui-ir.json`.
3. It reconstructs the immutable baseline or records a generated/redesigned version with explicit evidence.
4. It renders `ui-preview.html` and runs strict coverage/platform checks.
5. For review work, it runs interaction, state, typography, geometry, accessibility, and UX passes across declared screens and profiles.
6. The user selects findings, compares correction proposals, comments, and accepts or rejects a design version.
7. Only after acceptance can the agent prepare a separate source-change plan. Editing source still requires explicit approval of intended files and diff.

Render a completed IR:

```text
uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html
```

The default handoff copies or downloads a provider-neutral job. For Codex only, opt into its local task adapter:

```text
uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html --agent codex
```

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

Visual regression is allowed only against an explicitly approved baseline captured at the same viewport/state. A successful command is not automatically a passing report; every non-pass result must be fixed or retained as a named blocker/gap. See [Delivery validation](references/validation.md) and [Quality automation](references/quality-automation.md).

## Cache versus durable project knowledge

Technical fingerprints and per-file records are disposable user-cache data. A human-readable screen map, accepted UX decisions, or redesign history may be exported to project documentation or an Obsidian vault, but Obsidian is optional and is not part of the cache protocol.

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

No target runtime, emulator, bridge server, localhost service, or network request is needed for the generated preview.

## Version

The repository currently has the `v0.1` initial public release tag. Ongoing `main` development may contain newer unreleased capabilities.
