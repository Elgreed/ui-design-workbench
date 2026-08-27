# UI Design Workbench

**English** | [Русский](README.ru.md)

UI Design Workbench is a Codex skill for reconstructing, generating, redesigning, and reviewing application interfaces directly from source code.

It creates a standalone interactive HTML workbench without launching the target application, emulator, simulator, or development server. The workbench preserves source-backed UI details, exposes the screen hierarchy and navigation, supports element-level comments and Before/After proposals, and keeps application source unchanged until implementation is approved separately.

## Why use it

Most design-to-code tools start from an existing design file. UI Design Workbench also supports the opposite direction: it discovers the UI already implemented in a repository and turns it into a reviewable design workspace.

Use it to:

- inspect an existing UI without running the application;
- build an interactive map of discovered screens and transitions;
- review UI and UX against project and platform standards;
- annotate specific elements and collect structured feedback;
- generate new screens or alternative UI solutions;
- redesign selected screens while preserving unrelated behavior;
- compare the immutable current design with one or more proposals;
- approve the design before allowing source-code implementation.

## Supported platforms

- Android and Jetpack Compose;
- iOS, iPadOS, UIKit, and SwiftUI;
- Web applications;
- React Native;
- Flutter.

The workbench applies the matching platform baseline: Material for Android, Apple Human Interface Guidelines for Apple platforms, and semantic HTML, WCAG, and ARIA APG patterns for the Web. Project components and design tokens take priority when source evidence is available.

## Main capabilities

- **Repository UI discovery** — screens, routes, navigation targets, components, tokens, typography, and assets.
- **Screen hierarchy** — every translated screen appears once in a searchable, collapsible tree.
- **Multiple canvas modes** — All screens, Prototype, Single screen, and Before/After comparison.
- **Interactive prototype** — reconstructed navigation and local component-state actions.
- **Inspection and comments** — feedback linked to stable screen, node, version, and source references.
- **Deep UI/UX review** — hierarchy, spacing, typography, states, discoverability, density, accessibility, iconography, adaptive behavior, and cross-control interactions.
- **Deterministic diagnostics** — zoom synchronization, overlap, clipping, geometry, menus, navigation, target sizes, contrast, accessible names, and declared states.
- **Correction workflow** — accepted findings become sparse proposal versions without replacing the baseline.
- **Codex handoff** — a prepared local Codex task opens through the official `codex://new` deep link; no bridge server or open port is required.
- **Source protection** — design approval never implicitly authorizes edits to the application repository.

## Installation

Clone the repository into the Codex skills directory.

### Windows PowerShell

```powershell
git clone https://github.com/Elgreed/ui-design-workbench.git "$env:USERPROFILE\.codex\skills\ui-design-workbench"
```

### macOS or Linux

```bash
git clone https://github.com/Elgreed/ui-design-workbench.git ~/.codex/skills/ui-design-workbench
```

Restart Codex or open a new task after installation so the skill is rediscovered.

## Quick start

Open the target repository in Codex and invoke the skill explicitly:

```text
$ui-design-workbench reconstruct the UI from this repository and create an interactive HTML workbench
```

Other useful requests:

```text
$ui-design-workbench review the assembled UI and show corrected Before/After proposals
```

```text
$ui-design-workbench redesign the project settings screen while preserving the existing design system
```

```text
$ui-design-workbench generate a new onboarding flow that follows the target platform standards
```

The skill may also be selected automatically for matching UI reconstruction, design, redesign, or review requests.

## Working modes

### Reconstruct

Recreates the interface already present in source code. It prioritizes fidelity and provenance and does not introduce creative redesign decisions.

### Generate

Creates new interfaces from a brief, project tokens and components, and the standards of the selected platform.

### Redesign

Improves named UX problems while preserving unrelated behavior and the immutable current-design baseline.

### Review

Builds the current UI as the baseline, performs deterministic and expert analysis, records evidence-backed findings, and creates corrected proposals for review.

## Typical workflow

1. Codex scans the repository and discovers UI entry points, screens, routes, navigation, components, tokens, and assets.
2. It builds `ui-ir.json`, a portable intermediate representation of the interface and review state.
3. It renders a standalone `ui-preview.html` workbench outside the source repository by default.
4. Coverage, platform-profile, interaction, geometry, and accessibility checks are executed against the generated files.
5. The reviewer navigates screens, inspects elements, adds comments, and selects findings for correction.
6. Codex creates one or more sparse proposal versions and renders Before/After comparisons.
7. The reviewer accepts, rejects, or requests another design iteration.
8. Only after design approval may Codex prepare a separate source implementation plan and proposed diff.

## Using the generated workbench

- **All screens** displays every translated screen on one shared canvas.
- **Prototype** enables reconstructed screen transitions and browser history.
- **Single screen** freezes navigation for focused inspection.
- **Compare** displays any two retained versions side by side or as an overlay.
- **Interact** operates controls and prototype transitions.
- **Inspect** shows node, component, source, semantics, platform standard, and confidence data.
- **Comment** attaches feedback to the selected node and review version.
- **Review** runs diagnostics, presents findings, manages the correction queue, and tracks approval.

Screen navigation lives in the left panel. Properties, review findings, and comments live in separate tabs in the right panel. Both panels are collapsible and resizable. Canvas zoom is independent from screen dimensions and is controlled from the bottom-right zoom cluster or the mouse wheel over the canvas.

## Review and correction flow

1. Open the **Review** tab and choose the review scope.
2. Run **Review mockups** to execute deterministic checks across the selected screens and viewport profiles.
3. Inspect **Problems** and mark findings as Fix, Ignore, or Later.
4. Open **Changes** and create a proposal for the selected findings.
5. A prepared Codex task opens with the review artifact directory as its workspace. Review and send the prefilled prompt.
6. When Codex finishes rebuilding the artifacts, return to the workbench and refresh it.
7. Compare the proposal with the baseline and approve it or request another iteration.

The deep link only prepares a task. It does not submit the prompt or claim that AI work has started. Copyable prompts and JSON job files remain available as manual fallbacks.

## Generated artifacts

A complete review bundle can contain:

- `ui-scan.json` — discovered UI inventory;
- `ui-ir.json` — screens, nodes, components, actions, versions, findings, and provenance;
- `ui-preview.html` — standalone interactive workbench;
- `platform-profile-report.json` — platform-standard validation;
- `ui-coverage.json` and `ui-coverage.md` — translation and evidence coverage;
- `ui-interaction-matrix.json` — generated state and cross-control scenarios;
- `ui-diagnostics.json` — executed workbench diagnostics;
- screenshots and geometry snapshots for reproducible visual review;
- review feedback, correction jobs, and source-planning handoff JSON files.

Generated review files are kept outside the application repository unless the user explicitly requests otherwise.

## Safety and fidelity boundaries

- The target application is not run unless the user separately requests it.
- Reconstruction may only claim fidelity supported by source evidence.
- Browser-default controls must not silently replace project UI components.
- Missing assets or unsupported constructs remain explicit instead of being invented.
- The baseline is immutable; proposals are stored as separate sparse versions.
- Approving a design does not approve application-source changes.
- A separate confirmation is required before modifying the listed source files and diff.

## Requirements

- Codex with local skill support;
- Python 3.10 or newer;
- Node.js for headless smoke checks;
- Chrome, Edge, or Chromium for browser diagnostics, screenshots, and geometry capture.

No target-app runtime, emulator, simulator, bridge server, localhost service, or network development server is required to build the workbench.

## Repository structure

```text
ui-design-workbench/
├── SKILL.md              Skill entry point and operating contract
├── agents/openai.yaml    Codex UI metadata and default invocation
├── references/           Platform rules, schemas, fidelity and review guidance
└── scripts/              Scanner, renderer, validators and diagnostics
```

See [SKILL.md](SKILL.md) for the complete agent workflow and invariants. Detailed schemas and standards are in [`references/`](references/); deterministic tooling is in [`scripts/`](scripts/).

## Validation

Validate the installed skill:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" "$env:USERPROFILE\.codex\skills\ui-design-workbench"
```

The final UI bundle should also pass the platform-profile and coverage gates and complete the headless workbench smoke test described in [`references/quality-automation.md`](references/quality-automation.md).
