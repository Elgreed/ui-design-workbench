# Delivery validation

Run this checklist for every final bundle. The detailed commands and report formats live in [quality-automation.md](quality-automation.md).

## Coverage and fidelity

- Inventory includes platforms, all screens/logical views/routes/navigation targets, components, tokens, assets, and explicit exclusions. `screenTree` contains every screen exactly once.
- Coverage is 100% for declared screens, routes, and visible navigation. Component mappings and source/design evidence pass the mode-specific thresholds.
- The viewport content box matches the target size. Reconstruction reports `exact`, `high`, `approximate`, or `unsupported`; never claim pixel parity without runtime comparison.
- Platform profile, semantics, target size, states, contrast, accessibility, installed-framework constraints, and input methods are explicit and pass strict validation or remain named blockers.

## Workbench behavior

- All screens uses a single scalable canvas at Fit, 20%, 100%, and 200% without changing card dimensions, reflow, overlap, or incorrect scroll bounds. Zoom reset updates both geometry and displayed value.
- Prototype navigation, browser history, Single-screen freezing, active/hover-target tree colors, menu mutual exclusion/dismissal, panel collapse/resize persistence, compact overlay behavior, and selection/scroll persistence all work.
- Properties, Review, and Comments are isolated contextual panels. Icons use one coherent SVG family, icon-only actions have names/tooltips, and top chrome remains compact and unambiguous.
- Before/After split and overlay preserve anchors, highlight changes, retain decisions, and never edit source.

## Deep review

- Exercise default, loading, empty, error, offline, permission, disabled, success, destructive, focus, active/inactive, long-label/localization, text-scale, theme, narrow, and platform-specific states where applicable.
- Build interaction and cross-control scenarios for single, repeated, reverse, chained, boundary, and intermediate actions. Verify visual state, displayed values, focus, history, persistence, dependencies, scroll, and geometry after every transition.
- Measure typography hierarchy, baselines, four-side padding, icon-label gaps, box edges/heights, line counts, clipping, containment, overflow, and optical alignment at primary/compact viewports and zoom boundaries.
- Run a separate UX assessment of information architecture, discoverability, action priority/location, icon meaning/style, ergonomics, density/cognitive load, feedback/state visibility, progressive disclosure, adaptive behavior, platform fit, and visual coherence.
- Every non-pass check links to stable findings. Each finding has evidence, observation, impact, recommendation, severity, confidence, source target, standard/project basis, and proposal or `noProposalReason`. Consolidate repeated causal defects as systemic findings.

## Automation and approval

- Run strict platform validation, strict coverage, interaction-matrix generation for stateful UI, primary/compact diagnostics, screenshot plus geometry capture, and visual regression only against an explicitly approved matching baseline.
- The Review entry point checks the declared scope, records exact coverage/history, groups systemic failures, and exposes Problems and Changes with task-language decisions.
- Agent jobs include stable selection/scope/revision data, immutable-baseline rules, allowed writes, and `sourceChangeAllowed: false`. Preparing a proposal or review never claims execution started.
- A proposal requires explicit design acceptance. A separate source plan still requires approval of intended application files and diff.
- The preview performs no network requests. Report unsupported constructs, skipped tests, validation gaps, and residual risk.
