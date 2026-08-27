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

Use `init` for an explicit first scan, `status` to inspect freshness, `sync` after known UI changes, and `context --screen <id-or-name>` for bounded screen work. The default derived state belongs in the operating-system user cache; use `init --project-cache` only when the user explicitly needs ignored project-local state for CI or a portable environment. See [references/cache-protocol.md](references/cache-protocol.md).

## Choose the mode

Set one explicit mode from [references/design-modes.md](references/design-modes.md):

- `reconstruct`: reproduce current repository UI without creative changes.
- `generate`: create new UI from a brief, project design system, and target-platform standards.
- `redesign`: improve named UX problems while preserving unrelated behavior and provenance.

For review, audit, critique, or simplification requests, follow [references/ui-reviewer.md](references/ui-reviewer.md). Reconstruct an immutable baseline first; put corrections only in proposal versions. For `generate`, `redesign`, review, and enabled UI guidance, read only the relevant target sections of [references/platform-standards.md](references/platform-standards.md). Never apply redesign rules while reconstructing the baseline. Ordinary guidance tasks do not set `design.mode` or create IR unless the user also requests a workbench operation.

## Workbench workflow

Use this workflow for reconstruct, generate, redesign, and review. Guidance mode follows its shorter reference instead.

1. Read repository instructions. If `.agents/ui-policy.json`, `.codex/ui-policy.json`, or root `ui-policy.json` exists, apply the first one in that order using [references/ui-policy-schema.md](references/ui-policy-schema.md). Use a repository index such as CodeGraph when available before broad text search.
2. Declare mode, target platforms, review scope, primary user task, evidence sources, and preserved invariants. For reviews, declare covered screens, states, profiles, and input methods before assigning severity.
3. Use the cached inventory to build complete screen, route, logical-view, state, token, asset, dependency, and component coverage. Treat selectable tabs, panels, drawers, and hash-linked admin sections as screens. Every screen appears exactly once in a hierarchical `screenTree`. Every visible navigation target resolves to a screen/action or has a written exclusion.
4. Follow [references/platforms.md](references/platforms.md) for platform discovery, [references/fidelity.md](references/fidelity.md) for reconstruction, and [references/review-workflow.md](references/review-workflow.md) for the component registry, versions, annotations, and approvals. Prefer mapped project components over invented controls.
5. Create a separate `<review-dir>/ui-ir.json` using [references/ir-schema.md](references/ir-schema.md). Keep review artifacts outside the source repository unless explicitly requested. The cached starter IR is inventory, not a finished design.
6. Render with `uidw render <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html`. Add `--agent codex` only for an explicitly requested Codex deep-link adapter; the portable default copies or downloads a provider-neutral job. Use the bundled renderer script only when the CLI is unavailable.
7. Build the editor chrome with [references/workbench-ui.md](references/workbench-ui.md). Provide All screens, Prototype, Single screen, and Compare. Keep Problems as an independent canvas layer, but expose Before, Compare, and After as one stable three-state version-visibility group; reserve comparison-layout control space so the toolbar never jumps. Keep Interact, Inspect, and Comment independent. Iterate in IR, never in generated HTML.
8. Complete the gates in [references/validation.md](references/validation.md) and [references/quality-automation.md](references/quality-automation.md). Report every non-pass result and residual fidelity risk.
9. Only after design approval, propose intended application files and a platform-specific diff. Design approval is not source-edit approval.

## Non-negotiable invariants

- HTML is a projection; `ui-ir.json` is the review source of truth. Base nodes remain the immutable Before version and proposals use sparse overrides.
- Never run the target application, emulator, simulator, build, or dev server unless separately requested. Headless diagnostics may open only the generated local HTML.
- Do not replace project controls with browser-default styling. Map tokens, typography, assets, layout semantics, component variants, states, and accessibility explicitly. Missing evidence remains unresolved; do not polish it with invented fallback styling.
- Each finding needs observable evidence, impact, recommendation, confidence, severity, source target, and project/platform/standard basis. Do not present taste, inferred runtime behavior, or unverified research as fact.
- Use restrained native idioms: Material/TV Material for Android/Android TV, Apple HIG patterns for iOS/iPadOS/macOS, Fluent plus the installed WinUI/WPF stack for Windows, and semantic HTML/WCAG 2.2/APG for Web. React Native and Flutter require explicit target-family profiles. Do not silently upgrade frameworks or mix platform idioms.
- Preserve all discovered screens and routes. All screens renders every screen on one stable shared canvas; Prototype alone follows navigation; Single screen keeps navigation frozen while allowing local state inspection.
- Screen-tree current and hover-target highlights must be distinct. Side panels are independently collapsible/resizable. Zoom belongs in compact bottom-right controls and changes one shared canvas scale, never individual screen geometry or card flow.
- Findings use stable numbers shared by the Problems list and anchored canvas markers. A marker opens one inline finding card and its top-right collapse action restores the numbered marker; filtering or hiding Problems synchronizes both surfaces.
- Anchor finding markers in canvas coordinates, resolve collisions per rendered device without changing stable numbers, and remeasure after zoom, canvas/device scroll, resize, version change, and panel layout change. Middle-button drag pans the whole canvas and must not activate the mockup or lose marker click handling.
- The standalone workbench chrome supports runtime `ru` and `en` locale switching, persists the choice, and mirrors it in `?lang=`. Localize only tool chrome; never translate reconstructed product copy, screen names, findings, comments, source evidence, or user-authored content.
- Menus are mutually exclusive and close after action, outside click, Escape, or view change. State values, labels, focus, history, persistence, dependent controls, scroll bounds, and geometry must stay synchronized through repeated and chained actions.
- The workbench is offline and provider-neutral. Agent jobs may update review artifacts only, preserve the baseline, and set `sourceChangeAllowed: false`. A provider adapter may prepare a task but must never claim it was submitted or started.
- Keep generated review files and derived cache out of source control by default. Do not store per-project cache inside the installed skill.

## Portable agent handoff

The generated workbench creates a self-contained `ui-agent-job.json` or copies an equivalent prompt for any filesystem-capable coding agent. Native adapters are optional. Installation locations and adapter behavior are documented in [references/agent-integrations.md](references/agent-integrations.md).
