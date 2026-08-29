# UI Design Workbench

[Русская версия](README.ru.md) · [Changelog](CHANGELOG.md) · [Release guide](RELEASING.md)

Turn repository UI source into an offline, interactive HTML workbench—without building or running the application.

```text
UI source → cached UI map → strict UI IR → interactive HTML
```

Use it to understand an unfamiliar UI, inspect screens and navigation, compare a proposal with the source-derived baseline, or run an explicit UI/UX review.

## What you get

- A reusable inventory of screens, routes, components, tokens, themes, and states.
- An interactive HTML prototype with source links and declared navigation.
- Incremental scans: unchanged UI files are not analyzed again.
- Traceable reconstruction: unsupported source is reported instead of guessed.
- A safe review flow: project source stays read-only until a separate apply step.

Supported sources include Web, React, Vue, Svelte, Jetpack Compose, Android Views XML, SwiftUI, Storyboard/XIB, WinUI/WPF, Flutter, and React Native.

## Install

Requirements: Python 3.10+. A local AI agent is optional. Node.js and Chrome/Edge/Chromium are also optional and enable full browser diagnostics.

Install `pipx` once if it is not already available:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

```sh
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Then install the CLI and its Agent Skill—no repository clone is needed:

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

Replace `codex` with `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents`, or `all`.

Before the first PyPI release, install the same package directly from the GitHub archive:

```sh
pipx install "https://github.com/Elgreed/ui-design-workbench/archive/refs/heads/main.zip"
uidw install-skill codex
```

For optional local MCP support:

```sh
pipx inject ui-design-workbench-cli "mcp>=2,<3"
```

Verify the installation:

```sh
uidw --version
uidw doctor
```

Upgrade both the CLI and its installed skill with:

```sh
pipx upgrade ui-design-workbench-cli
uidw install-skill codex
```

A Windows `.exe` is not published yet; it remains a future convenience artifact, not the primary package format. See [RELEASING.md](RELEASING.md).

## Quick start

Choose the amount of preview detail once:

```sh
uidw --repo <repo> config setup
```

Build and open a source-derived workbench:

```sh
uidw --repo <repo> workbench --output-dir <artifacts> --level full --open
```

Open one screen or follow the reconstructed navigation:

```sh
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view single --screen <screen-id>
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view prototype --screen <screen-id>
```

Run UI/UX review only when you want product critique and proposals:

```sh
uidw --repo <repo> review --output-dir <review-dir> --level full
```

`workbench` and `check` validate the reconstruction. Only `review` starts a UI/UX audit.

## Main commands

| Command | Purpose |
| --- | --- |
| `uidw doctor` | Check the installation and optional dependencies |
| `uidw --repo <repo> context --json` | Read compact cached project context |
| `uidw --repo <repo> workbench ...` | Build and validate the HTML workbench |
| `uidw --repo <repo> check ...` | Re-run projection checks without UI/UX review |
| `uidw --repo <repo> review ...` | Start an explicit UI/UX review |
| `uidw --repo <repo> scope ...` | Prepare bounded context for one screen or finding |
| `uidw --repo <repo> patch ...` | Validate or apply sparse review-artifact changes |
| `uidw --repo <repo> fidelity ...` | Inspect source evidence and adapter limits |
| `uidw --repo <repo> mcp` | Start the optional local stdio MCP server |

Run `uidw help overview`, `uidw help advanced`, or `uidw <command> --help` for details.

## Accuracy and safety

- The HTML is a static source projection, not proof of runtime or pixel parity.
- Unsupported bindings, custom drawing, runtime data, and unresolved platform behavior remain explicit gaps.
- Android XML reconstruction does not execute Data Binding, custom views, constraints, or theme inheritance. Visual parity requires Layoutlib, emulator screenshots, or golden-image evidence.
- Review artifacts never authorize source changes. Applying a proposal is a separate, explicit step.
- Derived cache and review state live outside the target repository by default.

## Agent and MCP integration

The bundled Agent Skill teaches filesystem-capable agents to use the CLI as the deterministic engine. For large reviews, `scope` returns a structurally complete bounded context and `patch` accepts only sparse review operations; agents do not need the full IR.

The optional `uidw-mcp` server exposes the same bounded operations over local stdio. It opens no port, and the regular CLI remains the complete fallback.

## Documentation

- [Changelog](CHANGELOG.md)
- [Release and distribution guide](RELEASING.md)
- [Agent integrations](references/agent-integrations.md)
- [Fidelity contract](references/fidelity.md)
- [IR schema](references/ir-schema.md)
- [Review workflow](references/review-workflow.md)
- [Validation contract](references/validation.md)

Development version: `0.3.5` (not yet published). See [CHANGELOG.md](CHANGELOG.md).
