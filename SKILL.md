---
name: ui-design-workbench
description: Reconstruct, review, generate, or redesign repository UI as standards-aware interactive HTML previews; when a project's optional UI guidance mode is enabled, also guide ordinary UI implementation tasks with the matching Android, Android TV, Apple, Windows, or Web conventions. Do not use the workbench workflow when the user only wants to execute the real application.
metadata:
  compatibility: "Requires Python 3.10 or newer. Node.js and Chromium are optional for headless diagnostics."
---

# UI Design Workbench

Build a reviewable HTML UI workbench from repository evidence. Workbench design approval never authorizes application-source changes. In optional UI guidance mode, ordinary source edits remain limited to the user's implementation request and normal repository permissions.

## Start with cached project context

Resolve `<skill-dir>` as this file's directory and `<repo>` as the target repository. Prefer the installed CLI:

```text
uidw --repo <repo> context --json
```

If `uidw` is not on `PATH`, use `python <skill-dir>/scripts/uidw.py ...` as the bundled fallback. The CLI, not the skill prompt, owns scanning, cache invalidation, the UI source graph, rendering, and deterministic validation.

This lazily initializes or synchronizes a per-project UI index and returns the compact context path. Read that context first. Read only its `prioritySourceFiles`, the requested screen context, and directly referenced components unless the cache reports a gap. Do not rescan unchanged files manually.

Inspect `uiMode.enabled` in that context. When it is false, use this skill only for explicit reconstruct, generate, redesign, or review work. When it is true, use the lightweight guidance path in [references/ui-guidance-mode.md](references/ui-guidance-mode.md) for ordinary UI-related implementation tasks; do not build a preview or run a full audit unless requested.

Use `init` for an explicit first scan, `status` to inspect freshness, `sync` after known UI changes, and `context --screen <id-or-name>` for bounded screen work. `init --mock-data representative|exhaustive` opts into deterministic synthetic fixtures; the default is `none`. Representative mode creates one populated fixture plus only task-relevant critical states, never a universal state trio. The default derived state belongs in the operating-system user cache; use `init --project-cache` only when the user explicitly needs ignored project-local state for CI or a portable environment. See [references/cache-protocol.md](references/cache-protocol.md).

## Choose the mode

Set one explicit mode from [references/design-modes.md](references/design-modes.md):

- `reconstruct`: reproduce current repository UI without creative changes.
- `generate`: create new UI from a brief, project design system, and target-platform standards.
- `redesign`: improve named UX problems while preserving unrelated behavior and provenance.

For review, audit, critique, or simplification requests, follow [references/ui-reviewer.md](references/ui-reviewer.md). Reconstruct an immutable baseline first; put corrections only in proposal versions. For `generate`, `redesign`, review, and enabled UI guidance, read only the relevant target sections of [references/platform-standards.md](references/platform-standards.md). Never apply redesign rules while reconstructing the baseline. Ordinary guidance tasks do not set `design.mode` or create IR unless the user also requests a workbench operation.

## Workbench workflow

Use this workflow for reconstruct, generate, redesign, and review. Guidance mode follows its shorter reference instead.

1. Read repository instructions. If `.agents/ui-policy.json`, `.codex/ui-policy.json`, or root `ui-policy.json` exists, apply the first one in that order using [references/ui-policy-schema.md](references/ui-policy-schema.md). Use a repository index such as CodeGraph when available before broad text search.
2. Declare mode, target platforms, review scope, primary user task, evidence sources, preserved invariants, and mock-data mode. For reviews, declare covered screens, meaningful screen scenarios, profiles, and input methods before assigning severity.
3. Use the cached inventory to build complete screen, route, logical-view, state, token, asset, dependency, and component coverage. Treat selectable tabs, panels, drawers, and hash-linked admin sections as screens. Every screen appears exactly once in a hierarchical `screenTree`. Every visible navigation target resolves to a screen/action or has a written exclusion.
4. Follow [references/platforms.md](references/platforms.md) for platform discovery, [references/fidelity.md](references/fidelity.md) for reconstruction, and [references/review-workflow.md](references/review-workflow.md) for the component registry, versions, annotations, and approvals. Prefer mapped project components over invented controls.
5. Create a separate `<review-dir>/ui-ir.json` using [references/ir-schema.md](references/ir-schema.md). Keep review artifacts outside the source repository unless explicitly requested. When mock data is enabled, store reusable deterministic patches in `scenarioFixtures` and sparse, screen-specific references in `screen.scenarios`; preserve them for unaffected screens during sync. The cached starter IR is inventory, not a finished design.
6. Render with `uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html`. Add `--agent codex` only for an explicitly requested Codex deep-link adapter; the portable default copies or downloads a provider-neutral job. Use the bundled renderer script only when the CLI is unavailable.
7. Build the editor chrome with [references/workbench-ui.md](references/workbench-ui.md). Provide All screens, Prototype, Single screen, States when the current screen declares meaningful scenarios, and Compare. Single screen and Prototype expose a compact scenario switcher only for screens with alternatives. Entering Prototype always activates Interact, and choosing another screen from the tree preserves Prototype. Keep Problems as an independent canvas layer. Choose one active version in the document bar for ordinary views; make Compare a dedicated view with explicit left/right version selectors and its own split/overlay controls. Keep Interact, Inspect, and Comment independent. Iterate in IR, never in generated HTML.
8. Complete the gates in [references/validation.md](references/validation.md) and [references/quality-automation.md](references/quality-automation.md). Report every non-pass result and residual fidelity risk.
9. Keep two explicit correction paths. The safe path creates a proposal, requires design approval, then offers `Apply to project`. The fast path `Fix everything in project` is a separate explicit source-edit authorization. Both implementation jobs must modify real project UI files, run incremental `uidw sync` plus targeted verification, update existing finding statuses, and report every result as a numbered list in chat. Do not run a second full AI review unless the user separately requests it.

## Non-negotiable invariants

- HTML is a projection; `ui-ir.json` is the review source of truth. Base nodes remain the immutable Before version and proposals use sparse overrides.
- Never run the target application, emulator, simulator, build, or dev server unless separately requested. Headless diagnostics may open only the generated local HTML.
- Do not replace project controls with browser-default styling. Map tokens, typography, assets, layout semantics, component variants, states, and accessibility explicitly. Missing evidence remains unresolved; do not polish it with invented fallback styling.
- Each finding needs observable evidence, impact, recommendation, confidence, severity, source target, and project/platform/standard basis. Do not present taste, inferred runtime behavior, or unverified research as fact.
- Use restrained native idioms: Material/TV Material for Android/Android TV, Apple HIG patterns for iOS/iPadOS/macOS, Fluent plus the installed WinUI/WPF stack for Windows, and semantic HTML/WCAG 2.2/APG for Web. React Native and Flutter require explicit target-family profiles. Do not silently upgrade frameworks or mix platform idioms.
- Preserve all discovered screens and routes. All screens renders every screen on one stable shared canvas; Prototype alone follows navigation; Single screen keeps navigation frozen while allowing scenario and local-state inspection. Do not infer the same screen states for every route: model only source-evidenced or explicitly requested task states.
- Screen-tree current and hover-target highlights must be distinct. Side panels are independently collapsible/resizable. Zoom belongs in compact bottom-right controls and changes one shared canvas scale, never individual screen geometry or card flow.
- Findings use stable numbers shared by the Problems list and anchored canvas markers. A marker opens one inline finding card and its top-right collapse action restores the numbered marker; filtering or hiding Problems synchronizes both surfaces. A proposal version declares `resolvedFindingIds`; those markers disappear from that version while remaining visible on the immutable baseline and its review history. Unresolved user comments render as a separate numbered marker family with a distinct color and their own list.
- Anchor finding and comment markers in canvas coordinates, place them beside the owning device (outer left/right sides in Compare), resolve collisions per rendered device and side without changing stable numbers, and remeasure after zoom, canvas/device scroll, resize, version change, and panel layout change. Middle-button drag pans the whole canvas and must not activate the mockup or lose marker click handling.
- Keep File, Screens, Properties, Review, Comments, locale, and right-panel visibility directly reachable from the narrow rail. File is the first rail control and uses a centered conventional menu icon; File and locale menus must remain accessible, mutually exclusive, localized, and must not duplicate a persistent document-bar menu. Properties and Comments activate their canvas interaction modes from the rail; the bottom canvas palette must not repeat those commands or the Review layer toggle.
- The standalone workbench chrome supports runtime `ru` and `en` locale switching, persists the choice, and mirrors it in `?lang=`. Every built-in visible label, accessible name, tooltip, empty state, and toast needs both locales; stable internal IDs may remain English. Localize only tool chrome; never translate reconstructed product copy, screen names, version names, findings, comments, source evidence, or user-authored content.
- Menus are mutually exclusive and close after action, outside click, Escape, or view change. State values, labels, focus, history, persistence, dependent controls, scroll bounds, and geometry must stay synchronized through repeated and chained actions.
- The workbench is offline and provider-neutral. Review and proposal jobs may update review artifacts only, preserve the baseline, and set `sourceChangeAllowed: false`. Only the separate `Apply to project` or `Fix everything in project` action may create an implementation job with `sourceChangeAllowed: true`, the explicit project root, selected finding IDs, and bounded source targets. A provider adapter may prepare a task but must never claim it was submitted or started.
- Every review, proposal, and implementation agent job must return a plain numbered finding report in chat. Do not add a duplicate plain-text report to the generated HTML. Implementation reports include changed files and targeted verification; full repeat review remains opt-in.
- Keep generated review files and derived cache out of source control by default. Do not store per-project cache inside the installed skill.

## Portable agent handoff

The generated workbench creates a self-contained `ui-agent-job.json` or copies an equivalent prompt for any filesystem-capable coding agent. Native adapters are optional. Installation locations and adapter behavior are documented in [references/agent-integrations.md](references/agent-integrations.md).
