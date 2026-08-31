# UI Design Workbench

[Русская версия](README.ru.md) · [Changelog](CHANGELOG.md)

Turn repository UI source into an offline interactive HTML workbench—without building or running the application.

```text
UI source → cached UI map → strict UI IR → interactive HTML
```

Use it to understand unfamiliar UI, inspect screens and navigation, verify a reconstruction, or run an explicit UI/UX review.

## Install

Requires Python 3.10+ and [`pipx`](https://pipx.pypa.io/).

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

`install-skill` also supports `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents`, and `all`.

Optional local MCP support:

```sh
pipx inject ui-design-workbench-cli "mcp>=2,<3"
```

Verify the installation:

```sh
uidw --version
uidw doctor
```

## Quick start

Choose preview detail once:

```sh
uidw --repo <repo> config setup
```

Build and open the source-derived workbench:

```sh
uidw --repo <repo> workbench --output-dir <artifacts> --level full --open
```

Run a UI/UX audit only when product critique is wanted:

```sh
uidw --repo <repo> review --output-dir <review-dir> --level full
```

`workbench` and `check` validate the projection. Only `review` creates UI/UX findings.

## What it provides

- Screen, route, component, token, theme, and state inventory.
- Standalone HTML with source links and reconstructed navigation.
- Incremental scans that reprocess only changed UI files.
- Property-level evidence and explicit unsupported gaps instead of guessed UI.
- Sparse review patches and a separate, authorized source-apply step.
- Runtime-free Android, Apple, and Flutter source projection with deterministic geometry for the supported subset; native evidence is required only before claiming visual or pixel parity and is never launched automatically.

Supported source families include Web, React, Vue, Svelte, Jetpack Compose, Android Views XML, SwiftUI, Storyboard/XIB, WinUI/WPF, and Flutter.

## Main commands

| Command | Purpose |
| --- | --- |
| `uidw doctor` | Check installation and optional dependencies |
| `uidw --repo <repo> context --json` | Read compact cached project context |
| `uidw --repo <repo> scope ...` | Prepare bounded context for a screen or finding |
| `uidw --repo <repo> patch ...` | Validate or apply sparse review-artifact changes |
| `uidw --repo <repo> workbench ...` | Build and validate the HTML projection |
| `uidw --repo <repo> native status` | Discover native Android/Apple render providers without running them |
| `uidw --repo <repo> check ...` | Repeat projection checks without a UI/UX audit |
| `uidw --repo <repo> review ...` | Start an explicit UI/UX review |
| `uidw --repo <repo> fidelity ...` | Inspect source evidence and adapter limits |
| `uidw --repo <repo> mcp` | Start the optional local stdio MCP server |

Run `uidw help overview`, `uidw help advanced`, or `uidw <command> --help` for details.

## Accuracy and safety

- HTML is a deterministic runtime-free source projection for the supported shared layout subset, not proof of runtime or pixel parity.
- Android, Apple, and Flutter translation uses deterministic projection geometry for the supported shared layout subset; without separate native evidence it remains a structural projection, not proof of runtime or pixel parity.
- Unsupported bindings, custom drawing, runtime data, and platform behavior remain explicit gaps.
- Preview and review keep application source read-only; applying a proposal is a separate step.
- Derived cache and review state live outside the target repository by default.

## Upgrade

```sh
pipx upgrade ui-design-workbench-cli
uidw install-skill codex
```

A Windows `.exe` is not published yet. PyPI + `pipx` is the primary cross-platform installation path.

## Documentation

- [Changelog](CHANGELOG.md)
- [Agent integrations](references/agent-integrations.md)
- [Fidelity contract](references/fidelity.md)
- [Native rendering](references/native-rendering.md)
- [Cache protocol](references/cache-protocol.md)
- [Platform component catalog](references/component-catalog.md)
- [IR schema](references/ir-schema.md)
- [Review workflow](references/review-workflow.md)

Current CLI version: `0.6.5`.
