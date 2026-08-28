# UI Design Workbench

[Русская версия](README.ru.md)

UI Design Workbench turns UI source code into an offline interactive HTML workbench. It finds screens, navigation, components, themes, and states without running the application, build, dev server, emulator, or simulator.

```text
repository UI → cached UI map → strict ui-ir.json → interactive ui-preview.html
```

The CLI is provider-neutral. The included Agent Skill teaches Codex, Claude Code, Cursor, Gemini CLI, Copilot CLI, OpenCode, and other filesystem-capable agents how to use it.

## Why this tool exists

A typical AI UI task starts with a few source files or screenshots. The agent may miss hidden screens, repeatedly rescan the repository, invent unsupported styling, or edit production code before the result can be reviewed. Checking the result usually requires running the application or assembling screenshots manually.

UI Design Workbench adds a deterministic layer between source code and AI decisions:

| Typical workflow without the workbench | With UI Design Workbench |
| --- | --- |
| The agent reads whichever UI files it finds first | The scanner builds a reusable inventory of screens, routes, components, tokens, themes, and states |
| Hidden routes, tabs, drawers, or admin screens may be missed | Every discovered screen is placed once in a hierarchical screen tree |
| UI is recreated from memory or generic HTML controls | The preview is generated from strict IR with source mappings and project tokens |
| The app, emulator, simulator, or dev server is needed to inspect flows | A standalone HTML prototype shows screens and declared transitions offline |
| The repository is rescanned in later tasks | Content-addressed cache refreshes only changed UI files |
| The AI may mix reconstruction with unsolicited redesign advice | Projection checks and UI/UX review are separate explicit operations |
| Production UI files may change before visual approval | Proposals live in the workbench first; project edits require a separate apply authorization |
| Before/After and comments are spread across chat and screenshots | Versions, comparisons, findings, and anchored comments stay in one artifact |
| Platform conventions depend on the current prompt | Optional profiles provide consistent Android, Android TV, Apple, Windows, and Web guidance |

Use it when you need to understand an unfamiliar UI codebase, inspect all screens without running it, create an interactive design artifact, compare a redesign safely, or perform a deliberate platform-aware review. It is not a replacement for final testing in the real application.

## Important behavior

- `uidw workbench` and `uidw check` validate reconstruction and HTML behavior only. They do not judge the product UI or create UI/UX findings.
- `uidw review` is the only command that starts a UI/UX audit. Use it only when a review is explicitly wanted.
- Rendering, review, and proposals keep application source read-only.
- Source changes require a separate authorized apply job.
- Generated HTML is standalone and requires no local server.

## Main features

- Complete screen and route inventory with a hierarchical screen tree.
- Interactive prototype navigation using reconstructed controls.
- Single-screen, all-screens, variants, and dedicated comparison views.
- Separate theme and state dropdowns; light/dark/custom themes appear only when found in source.
- Deterministic mock data, including repeated items for lists, tables, grids, and collections.
- Shared-canvas zoom, middle-button panning, resizable panels, inspection, and anchored comments.
- Optional UI/UX review with stable numbered findings and Before/After proposals.
- Property-level source provenance, strict IR validation, token resolution, and immutable baselines.
- Platform profiles for Android, Android TV, iOS/iPadOS, macOS, Windows, Web, Flutter, and React Native.
- Incremental source cache to avoid repeated repository-wide scans and reduce token use.
- Russian and English workbench chrome.

## Requirements

- Python 3.10 or newer.
- Git.
- A local AI agent with filesystem and shell access.
- Optional: Node.js and Chrome, Edge, or Chromium for headless HTML checks.
- Optional: Pillow for pixel regression.

The target application's runtime and SDK are not required for preview generation.

## Installation

Clone the repository first:

```sh
git clone https://github.com/Elgreed/ui-design-workbench.git
cd ui-design-workbench
```

### Windows 10/11

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install .
.\install.ps1 -Agent codex
```

Replace `codex` with `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents`, or `all` when needed.

If PowerShell blocks the installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Agent codex
```

### macOS and Linux

```sh
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install .
sh ./install.sh codex
```

Replace `codex` with another supported agent or `all`.

Restart the selected agent or open a new session, then verify the installation:

```sh
uidw --version
uidw --json doctor
```

Without installation, run `python scripts/uidw.py` on Windows or `python3 scripts/uidw.py` on macOS/Linux.

## Quick start

### 1. Choose preview detail

```sh
uidw --repo <repo> config setup
```

| Level | Includes |
| --- | --- |
| `low` | Screens, basic layout, minimal mock data |
| `medium` | Low plus navigation, interactions, relevant states, representative data |
| `high` | Medium plus expanded data, detected themes, variant boards, exhaustive reconstruction/HTML checks |

Mock data is always enabled. Its depth follows the selected level. No level starts UI/UX review.

### 2. Build the HTML workbench

```sh
uidw --repo <repo> workbench --output-dir <artifacts> --level full --open --view overview --lang en
```

The first run creates the UI index, graph, and starter IR. Later runs reuse the cache and rescan only changed UI files.

### 3. Inspect one screen or prototype navigation

```sh
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view single --screen <screen-id> --lang en
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view prototype --screen <screen-id> --lang en
```

The workbench uses the reconstructed UI controls. It does not replace them with browser-default buttons or inputs.

## Preview views

| View | Purpose |
| --- | --- |
| All screens | Browse every discovered screen on one canvas |
| Prototype | Follow declared navigation by clicking reconstructed controls |
| Single screen | Inspect one screen without navigation changing the view |
| Variants | Compare themes or states, or show a grouped theme/state matrix |
| Compare | Compare two explicit versions side by side or as an overlay |

Theme and state dropdowns remain separate. In Matrix view they select the current combination without hiding the other variants. Zoom affects mockups, not the variant controls.

## UI/UX review

Run review only when it is explicitly needed:

```sh
uidw --repo <repo> review --output-dir <review-dir> --level full --lang en
```

The review flow is:

1. Run the audit.
2. Select findings to address.
3. Generate one restrained proposal, or two only when a real UX trade-off exists.
4. Compare the immutable Before version with the proposal.
5. Approve the proposal.
6. Prepare an apply job for the real project.
7. Run targeted verification after implementation.

Review findings are always bound to the immutable reviewed version. Proposal versions may describe which findings they address, but a finding is complete only after the project change passes targeted verification.

The CLI prepares portable agent jobs; it does not silently launch an AI provider or edit project source.

Useful review commands:

```sh
uidw findings list --ir <review-dir>/ui-ir.json
uidw findings accept 7 25 --ir <review-dir>/ui-ir.json
uidw proposal prepare --ir <review-dir>/ui-ir.json
uidw apply prepare --ir <review-dir>/ui-ir.json
uidw apply prepare --direct --ir <review-dir>/ui-ir.json
```

`--direct` is an explicit fast path that skips proposal approval. Use it only when that behavior is intended.

## Cache and token use

Manual `init` is optional. `context`, `workbench`, and `review` initialize the project cache when required.

```sh
uidw --repo <repo> status
uidw --repo <repo> sync
uidw --repo <repo> diff
uidw --repo <repo> context --screen <screen-id> --budget 4000
```

By default, derived state is stored in the operating-system user cache, not in the project or installed skill. Content hashes invalidate only changed UI files. Set `UIDW_CACHE_HOME` to override the cache root.

## Optional platform guidance

Platform guidance for ordinary UI implementation tasks is off by default:

```sh
uidw --repo <repo> ui-mode --enable
uidw --repo <repo> ui-mode --disable
```

When enabled, the agent uses existing project components and the detected platform conventions for the requested change. It does not scan unrelated UI or start a review automatically.

## Fidelity Core

Fidelity Core makes reconstruction evidence inspectable:

```sh
uidw fidelity capabilities
uidw fidelity report --ir <artifacts>/ui-ir.json
uidw fidelity explain <node-id-or-evidence-id> --ir <artifacts>/ui-ir.json
```

Built-in adapters cover HTML/CSS, React/JSX, Vue, Svelte, Jetpack Compose, Android Views XML, SwiftUI, Storyboard/XIB, WinUI/WPF XAML, Flutter, and React Native. Unsupported syntax is reported instead of being replaced with invented UI.

Flutter and React Native require an explicit target platform before platform-specific UX conclusions can be made.

## Common commands

| Command | Purpose |
| --- | --- |
| `uidw doctor` | Check installation and optional dependencies |
| `uidw --repo <repo> context --json` | Return compact cached project context |
| `uidw --repo <repo> workbench ...` | Build and validate the HTML projection |
| `uidw --repo <repo> check --ir <file> --level full` | Repeat projection checks without UI/UX audit |
| `uidw --repo <repo> review ...` | Explicitly start UI/UX review |
| `uidw --repo <repo> scenarios validate --ir <file>` | Validate screen scenarios and populated collections |
| `uidw pack --ir <file> --output review.uidw.zip` | Create a portable artifact bundle |
| `uidw unpack review.uidw.zip --output-dir <dir>` | Unpack a portable bundle |
| `uidw help config` | Explain configuration |
| `uidw help advanced` | List advanced commands |

## AI-agent installation targets

| Agent | Installer value | Skill directory |
| --- | --- | --- |
| Codex | `codex` | `~/.codex/skills/ui-design-workbench` |
| Claude Code | `claude` | `~/.claude/skills/ui-design-workbench` |
| Cursor | `cursor` | `~/.cursor/skills/ui-design-workbench` |
| Gemini CLI | `gemini` | `~/.gemini/skills/ui-design-workbench` |
| GitHub Copilot CLI | `copilot` | `~/.copilot/skills/ui-design-workbench` |
| OpenCode | `opencode` | `~/.config/opencode/skills/ui-design-workbench` |
| Generic local agent | `agents` | `~/.agents/skills/ui-design-workbench` |

For an agent without skill discovery, use this minimal instruction:

```text
Use UI Design Workbench as the deterministic UI engine. Start with:
uidw --repo <repo> context --json
Do not run the application. Build or review in a separate artifact directory.
Do not edit project source unless an apply job explicitly sets sourceChangeAllowed: true.
```

## More documentation

- [Agent integrations](references/agent-integrations.md)
- [Cache protocol](references/cache-protocol.md)
- [Fidelity and reconstruction](references/fidelity.md)
- [IR schema](references/ir-schema.md)
- [Platform standards](references/platform-standards.md)
- [Review workflow](references/review-workflow.md)
- [Validation](references/validation.md)
- [Workbench UI](references/workbench-ui.md)

## Repository layout

```text
SKILL.md                    Agent workflow adapter
scripts/uidw.py             Main CLI
scripts/scan_ui.py          Incremental source scanner
scripts/render_preview.py   Standalone HTML renderer
scripts/smoke_preview.js    Headless workbench checks
schemas/                    JSON schemas
references/                 Behavior and platform contracts
fixtures/golden/            Adapter regression fixtures
```

## Version

Current CLI version: `0.3.2`.
