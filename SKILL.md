---
name: ui-design-workbench
description: Reconstruct repository UI, perform evidence-based UI/UX audits with corrected Before/After proposals, generate new interfaces, or redesign existing screens as standards-aware interactive HTML previews without running the app or changing source files. Use for UI review and design work across Android, Android TV, iOS, iPadOS, macOS, Windows, Web, React Native, and Flutter; do not use when the user wants to execute or test the real application.
---

# UI Design Workbench

Build a reviewable HTML UI workbench. Treat the repository as read-only until the user separately approves a source-code patch.

## Choose the mode

Set one explicit mode from [references/design-modes.md](references/design-modes.md):

- `reconstruct` copies the current repository UI without creative changes.
- `generate` creates new UI from a brief, the project design system, and platform standards.
- `redesign` improves named UX problems while preserving unrelated behavior and provenance.

When the user asks for a UI/UX review, audit, critique, simplification, or "what is wrong", use the review workflow in [references/ui-reviewer.md](references/ui-reviewer.md). Reconstruct the current UI as the immutable baseline, then use `redesign` only for the proposed corrections. For `generate`, `redesign`, and review, also read the matching sections of [references/platform-standards.md](references/platform-standards.md). Do not apply redesign rules during baseline reconstruction.

## Workflow

1. Resolve the repository root when present and read its nearest instructions. If `.codex/ui-policy.json` or `ui-policy.json` exists, read it using [references/ui-policy-schema.md](references/ui-policy-schema.md) before making design decisions. If `.codegraph/` exists, use CodeGraph before text search to locate screens, navigation, and design-system symbols.
2. Set `design.mode`, target platforms, and the review scope. For generation, record a concrete primary task before choosing visual treatment. For redesign, state the UX problem and preserved invariants. For an expert review, define the audited tasks, platforms, screen/state coverage, and evidence sources before assigning severity.
3. For reconstruction or redesign, run `scripts/scan_ui.py <repo> --output <review-dir>/ui-scan.json`. Keep `<review-dir>` outside the repository unless explicitly requested otherwise. Treat starter IR as inventory only.
4. Build the screen, route, logical view, state, token, asset, dependency, and component inventory. Treat independently selectable panels, tabs, drawers, and hash-linked admin sections as screens even when they share one source file or HTTP route. Build a complete `screenTree` that mirrors real navigation and ownership; every screen appears exactly once. Read recursively referenced project components. Use only the matching platform discovery rules in [references/platforms.md](references/platforms.md).
   When project components are found, build and enforce the component registry using [references/review-workflow.md](references/review-workflow.md); prefer mapped project components over new controls.
5. In reconstruction, follow [references/fidelity.md](references/fidelity.md). In generation or redesign, follow [references/design-modes.md](references/design-modes.md) and [references/platform-standards.md](references/platform-standards.md); inspect installed framework versions before selecting APIs. For a review, additionally follow [references/ui-reviewer.md](references/ui-reviewer.md), recording findings before creating correction versions.
6. Create or refine `<review-dir>/ui-ir.json` using [references/ir-schema.md](references/ir-schema.md). Reconstruction preserves source provenance. Generated/redesigned nodes preserve project, platform-standard, or explicit decision evidence.
7. Run `scripts/render_preview.py <review-dir>/ui-ir.json --output <review-dir>/ui-preview.html`. The renderer blocks incomplete fidelity, missing standards profiles, unsupported placeholders, unexplained custom controls, missing semantics, and undersized targets. Use `--allow-draft` only for internal diagnostics.
   For an autonomous DOM/geometry pass without running the application, use `node scripts/smoke_preview.js <review-dir>/ui-preview.html --output <review-dir>/ui-diagnostics.json`. It launches only the generated local HTML in headless Chrome/Edge/Chromium; add `--fail-on-findings` when a non-zero exit is desired for CI.
   Before delivery, follow [references/quality-automation.md](references/quality-automation.md): validate the machine-readable platform profile, pass the coverage gate, generate the interaction scenario plan, capture primary and compact pixel/geometry snapshots, and compare them with an explicitly approved baseline when one exists.
8. Present `All screens`, `Prototype`, `Single screen`, and, when a proposal exists, `Before / After` views. Keep `Interact`, `Inspect`, and `Comment` independent. Build the surrounding editor chrome with [references/workbench-ui.md](references/workbench-ui.md): canvas-first regions, a narrow navigation rail, searchable screen tree, one document bar, a floating canvas-tool palette, zoom-only bottom-right controls, coherent SVG icons, and a contextual tabbed right panel. Follow [references/review-workflow.md](references/review-workflow.md) for versioned proposals, annotation export, diagnostics, and incremental approval. Iterate in IR without changing source.
9. Only after preview approval, propose a platform-specific source patch with intended files and diff. Preview approval is not source-edit approval.

## Rendering invariants

- HTML is a projection, not the source of truth. Edit the IR, not generated HTML.
- Keep base nodes as the immutable `Before` snapshot. Put proposed changes in sparse review-version overrides; never erase rejected review history.
- A review finding is not an aesthetic opinion. It must identify observable evidence, user impact, a concrete recommendation, confidence, severity, and its project/platform/standard basis. Do not invent research evidence or claim runtime behavior that source cannot establish.
- Group related findings into the smallest coherent correction version. Every blocker/high finding needs a linked proposal or a concrete `noProposalReason`; offer extra variants only for meaningful tradeoffs.
- Never run the application, emulator, simulator, build, or dev server unless the user separately requests it.
- Do not use browser-default visual styling for project controls. Map project tokens, typography, assets, layout semantics, and component variants explicitly.
- Do not add fallback colors, padding, radii, borders, shadows, device chrome, or typography to make an incomplete translation look polished. Missing evidence must remain unresolved.
- In generation and redesign, use the restrained platform baseline first. A visual or behavioral choice without project evidence, a platform reference, a user requirement, or a recorded decision is invalid.
- For Android mobile/tablet default to the project's Material system, normally Material 3; for Android TV use TV Material and D-pad-first focus/navigation; for iOS/iPadOS use Apple-native HIG patterns; for macOS use Mac windows, menus, commands, toolbars, keyboard/pointer workflows, and HIG; for Windows use the installed WinUI/WPF stack with Fluent, keyboard, Narrator, high-contrast, scaling, and resizable-window behavior; for Web use semantic HTML, WCAG 2.2 AA, and APG keyboard behavior for custom widgets. Do not mix platform idioms without an explicit reason.
- Do not silently upgrade dependencies, adopt experimental UI APIs, or emulate unavailable system materials.
- Use the exact content viewport from the target platform. A decorative device frame is off by default and must never reduce the content dimensions.
- Reuse repository SVG, raster assets, and font files when licensing and local paths allow. Record missing or remote assets as unresolved instead of inventing replacements.
- Use interactions only to model UI state and navigation declared or reasonably implied by source. Mark inferred behavior with `confidence: approximate`.
- Preserve every discovered screen and route in the final IR. Exclude false-positive candidates only with a stable source key and written reason. Do not stop after the representative screen when the requested deliverable covers the application.
- Always include a hierarchical `screenTree`, even for a small preview. Prefer product area → navigation group → screen; do not flatten nested navigation merely because the renderer can infer a fallback.
- Every discovered menu, tab, or hash navigation target must resolve to a translated screen and a `navigate` action, or have an explicit exclusion reason. A visible menu made of inert buttons is incomplete.
- `All screens` must render every translated screen simultaneously without firing interactions. `Prototype` must follow declared navigation and local state actions. `Single screen` must keep navigation frozen while allowing focused inspection and non-navigation state changes.
- The workbench chrome must remain visually distinct from the reconstructed product UI. Its view mode and whether navigation is active must be obvious without trial clicks. A navigation click outside `Prototype` must explain that transitions are disabled instead of failing silently.
- Keep the screen tree dense enough for large products: compact rows, collapsible groups, small count badges, no redundant depth labels, and an active path. Both side panels must be independently collapsible and pointer/keyboard resizable; persist their widths locally.
- Keep zoom out of the primary action bar. Provide a compact floating bottom-right control for zoom out, percentage/reset, zoom in, and fit, with tooltips or accessible names for icon-only actions.
- Report fidelity as `exact`, `high`, `approximate`, or `unsupported`. Never claim pixel-perfect parity without runtime comparison.
- Keep generated review files separate from source control by default.
- Preview approval and annotation acceptance authorize only the design version. Require separate approval before modifying application source.

## First-pass command

Resolve `<skill-dir>` as the directory containing this `SKILL.md`.

```powershell
python <skill-dir>/scripts/scan_ui.py <repo> --output <review-dir>/ui-scan.json --starter-ir <review-dir>/ui-ir.json
```

This command applies to reconstruction and redesign with an existing repository. The starter IR is deliberately non-renderable for review.

## Validation

- Confirm that the scan lists detected platforms, candidate screens, navigation, tokens, and assets.
- Run `validate_platform_profiles.py` and `coverage_report.py --strict`; deliver their reports and do not average a failed coverage category into an overall pass.
- For stateful UI, generate `ui-interaction-matrix.json`; distinguish generated scenarios from executed `review.audit.interactionChecks`.
- Confirm that every rendered interactive node has a stable ID and source provenance when available.
- When project components exist, confirm the component catalog is ready and every used project component has a mapped `componentRef`.
- Confirm the fidelity audit reports at least 80% source mapping and no untranslated placeholders.
- For generation/redesign, confirm at least 90% evidence coverage and 100% standards, semantics, target-size, state-matrix, and resolvable WCAG text-contrast coverage.
- Confirm the design mode, primary task, target platforms, installed framework constraints, and standard profiles are explicit.
- For Windows, confirm mouse/touch/pen/keyboard inputs, access keys/accelerators, visible focus, Narrator/UI Automation, text/display scaling, high contrast, activation, title-bar insets, and window resizing. For macOS, confirm menu-bar commands, shortcuts, pointer and keyboard workflows, Full Keyboard Access, VoiceOver, active/inactive and resizable/multiwindow states. For Android TV, confirm initial and restored focus, a single visible focused element, complete D-pad reachability, Select/Back, focus-driven scrolling, 16:9 layout, ten-foot readability, and overscan-safe primary content.
- Check relevant default/loading/empty/error/offline/permission/disabled/success/destructive states, recording justified non-applicable states.
- Confirm screen and route coverage are 100%, accounting for explicitly reasoned exclusions.
- Confirm logical-view and navigation-target coverage are 100%; in Prototype, every visible sidebar or tab destination must be reachable.
- Confirm `screenTree` contains every screen exactly once, the active screen and full path are visible, group levels can collapse, and the whole tree sidebar can be hidden and restored. Hovering or focusing any control with `action.type: navigate` must preview its target in the tree with a color distinct from the current-screen highlight.
- Confirm the workbench top area does not crowd or obscure the preview at the target review viewport: menus remain recognizable, mode controls have unambiguous labels/tooltips, the action bar is visually separated, and auxiliary panel actions use compact icons.
- Confirm both side panels can be resized, hidden, and restored; widths persist after reload, resize handles support arrow keys, and double-click restores a sensible default width.
- At compact widths, confirm the side panels become task-focused overlays and opening one closes the other; the canvas must retain a useful working area.
- Confirm the right panel exposes only one of `Properties`, `Review`, or `Comments` at a time and automatically selects the matching tab when a tool, finding, diagnostic, comment, or menu action opens it.
- Confirm the workbench uses one coherent inline SVG icon family rather than mixed Unicode glyphs, and that every icon-only action has an accessible name and tooltip.
- Confirm the viewport content box has exactly the requested width and height.
- Confirm large desktop screens start in `Fit` mode, remain horizontally reachable, and can be zoomed from 20% to 200% with controls or the mouse wheel over the canvas (`Ctrl`/`Command` + wheel over scrollable screen content).
- In `All screens`, confirm that Fit, 20%, 100%, and 200% scale one shared canvas without changing per-screen preview dimensions, reflowing cards, or producing overlap; confirm the canvas scroll bounds track the scaled content.
- Open every workbench menu in sequence and confirm menus are mutually exclusive. Confirm the active menu closes after an action, outside click, `Escape`, and view change.
- Confirm `All screens` contains every screen, `Prototype` follows navigation and browser back/forward, and `Single screen` does not leave the selected screen after a navigation click.
- Confirm `Before / After` supports split and overlay views, changed-node highlighting, stable annotation anchors, feedback export, and version-level accept/reject without changing source files.
- Confirm every failed interaction/layout check and every UX assessment with `status: finding` links to concrete `findingIds`. In the workbench, each audit row must show its linked problem count, open only those cards, and allow adding the whole group to the correction queue.
- Confirm finding actions use task language: `В исправление`, `Не исправлять`, and `Позже`. The correction queue must show selected count, distinguish existing Before/After proposals from findings needing a new proposal, and support both an official `codex://new` handoff and a self-contained `ui-fix-request.json` fallback. The deep link may open a new Codex task with a prepared prompt and review-directory workspace; it must never claim the prompt was sent or execution started.
- Confirm the queue exposes five explicit phases: problems, selected fixes, generated proposal, design approval, and project implementation. `Создать вариант макета` may change only IR/HTML. Enable a separate source handoff only for an accepted proposal, and keep source modification blocked until the user explicitly approves the intended files and diff.
- Configure `review.diagnostics` for every review deliverable and run the Diagnostics Runner after the final render. Its scenarios must cover zoom reset, shared-overview geometry at 20%/100%/200%, mutually exclusive menus, per-screen layout integrity, and basic accessible names. Use deterministic primary and narrow `{width,height}` sandbox profiles instead of relying only on the current browser window. Resolve runner failures or retain them explicitly as findings/validation gaps; include the runtime report in feedback export.
- Confirm every non-pass runtime diagnostic can focus its measured nodes, create a complete evidence-backed finding, and add that finding to `ui-fix-request.json`; verify `merge_review_state.py` preserves those runtime findings in the next IR.
- Confirm the Review tab begins with one `Запустить ревью` action that checks every assembled screen/profile, focuses all non-pass findings without duplicating deterministic IDs on rerun, reports progress and completion, and enables the expert handoff only after a completed run. Embed the absolute review-directory path in generated HTML. The official `codex://new?prompt=...&path=...` action must prepare a self-contained task restricted to review artifacts, require the user to send the prefilled prompt, preserve the immutable baseline, and keep source changes blocked; retain `ui-expert-review-request.json` as a manual fallback.
- Structure Review as isolated `Сводка`, `Проблемы`, and `Изменения` workspaces with one contextual primary action. Show exact screen/profile/check/state coverage and named run history; never label coverage as all states unless every declared variant was executed in every included deterministic profile.
- Group repeated runtime failures by scenario and screen into systemic findings, preserve measured instances, and provide severity/source/screen filters plus bulk decisions. Support `All screens` and `Current screen` review scopes; include the chosen scope in history and exported jobs.
- Accept a revision/project-validated `ui-design-workbench-expert-review-result`, the legacy `ui-code-preview-expert-review-result`, or returned complete UI IR; merge stable findings and sparse proposal versions without changing the immutable baseline, record the import in history, and keep source modification blocked. Compare any two retained review versions in split or overlay mode.
- Confirm rerenders preserve selected node, active finding/diagnostic highlight, inner screen scroll, overview-stage scroll, panel widths, and review filters. Change view or zoom during selection and verify the reviewer does not lose context.
- Set a stable `review.revision`. Confirm saved state from a different computed revision is never silently applied: the workbench must offer explicit migration of still-valid annotations/findings or a clean reset.
- For expert review, confirm every finding has a stable ID, category, severity, confidence, observation, user impact, recommendation, evidence, source target, and proposal/no-proposal disposition. Confirm screen coverage and state coverage are explicit, repeated systemic problems are separated from individual instances, and blocker/high findings open directly in a corrected comparison.
- For expert review, build a state-transition and cross-control matrix for every stateful control. Verify visible values, pressed/open/disabled state, focus, history, persistence, dependent controls, scroll bounds, and geometry after single, reverse, repeated, chained, boundary, and intermediate actions; store the executed scenarios in `review.audit.interactionChecks`.
- Run a separate UX assessment covering information architecture, discoverability, action placement and priority, icon meaning and stylistic consistency, control ergonomics, density/cognitive load, feedback/state visibility, progressive disclosure, and adaptive behavior; store it in `review.audit.uxAssessment` and link problems to findings.
- Run a measured typography/geometry pass at primary and narrow viewports plus Fit, 100%, and boundary zoom: verify typography roles, sibling baselines and box edges, four-side padding, icon-label gaps, line counts, clipping/ellipsis/overflow, text containment, and optical alignment across control states; store results in `review.audit.layoutChecks`.
- Capture and visually inspect workbench screenshots plus geometry snapshots at primary and compact viewport sizes. When an approved baseline exists, run `visual_regression.py --strict`; reject unexplained pixel changes, geometry drift, new overlaps, permanent instructional copy, duplicated controls, panel competition, ambiguous selection states, or floating controls that obscure the reviewed UI.
- Confirm the preview works without network requests.
- Report unsupported constructs and residual fidelity risk.
