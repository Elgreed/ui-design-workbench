# Quality automation

Use these deterministic gates for every final reconstruction, generation, redesign, or expert-review bundle. They inspect IR and standalone HTML only; they never run the target application.

## 1. Platform profile

`references/platform-profiles.json` is the machine-readable source for profile IDs, standard-reference prefixes, minimum targets, required interaction states, and cross-platform framework adapters. The validation matrix covers Android, Android TV, iOS, macOS, Windows, and Web. Flutter and React Native require explicit target families; do not use one ambiguous shared profile.

```powershell
python <skill-dir>/scripts/validate_platform_profiles.py <review-dir>/ui-ir.json --output <review-dir>/platform-profile-report.json --strict
```

Fix a blocked report in IR. A `project` profile is valid only with a non-empty reason and project evidence.

## 2. Coverage gate

Run after the final IR update and before delivery:

```powershell
python <skill-dir>/scripts/coverage_report.py <review-dir>/ui-ir.json --output <review-dir>/ui-coverage.json --markdown <review-dir>/ui-coverage.md --strict
```

The report gates screen-tree uniqueness, discovered screens/routes/navigation, component mappings, appearance, profiles, and mode-specific source or design evidence. Generate/redesign additionally gate semantics, standards, target size, contrast, and required state coverage. Do not average away a failed category; every gate must pass or remain an explicit delivery blocker.

## 3. Interaction scenario plan

Generate the review plan from declared actions and states:

```powershell
python <skill-dir>/scripts/generate_interaction_matrix.py <review-dir>/ui-ir.json --output <review-dir>/ui-interaction-matrix.json
```

The plan covers single, repeated, reverse, chained, and boundary actions plus workbench zoom, menu, and panel continuity. `--max-pairs` bounds cross-control combinations without dropping individual control checks. Use `--merge-output <new-ir.json>` only when the plan should travel inside `review.scenarioPlan`; never overwrite the input IR. Generated scenarios are a plan, not proof of execution. Record actual results separately in `review.audit.interactionChecks`.

## 4. Reproducible snapshots

Capture both pixels and DOM geometry at the approved viewport:

```powershell
node <skill-dir>/scripts/smoke_preview.js <review-dir>/ui-preview.html --output <review-dir>/ui-diagnostics.json --screenshot <review-dir>/candidate.png --geometry-output <review-dir>/candidate-geometry.json --capture-view overview --capture-screen home --capture-left-panel open --capture-right-panel open --capture-inspector-tab review --viewport-width 1440 --viewport-height 960
```

Use `--capture-review-section summary|problems|changes` to capture each review workspace deterministically. A production reviewer workbench needs at least Summary at primary and compact widths plus Problems and Changes after representative decisions or imports.

Repeat for every primary and compact viewport. The `--capture-*` options restore a canonical view, screen, panel, and inspector state after smoke interactions, so regression screenshots do not accidentally capture the test residue. At widths up to 980 px, an explicitly open right panel closes the left panel to preserve the production mutual-exclusion invariant. Compare a candidate only with a deliberately approved baseline captured at the same viewport and state:

The smoke workflow must also validate the standalone Codex handoff descriptor without launching it: an absolute artifact path, a `codex://new` URL, the `$ui-design-workbench` prompt, immutable-baseline/source guards, selected finding IDs for proposal jobs, and visible copy/refresh recovery controls. It must not require a bridge server, localhost port, or background process.

```powershell
python <skill-dir>/scripts/visual_regression.py --baseline <baseline.png> --candidate <candidate.png> --baseline-geometry <baseline-geometry.json> --candidate-geometry <candidate-geometry.json> --output <visual-regression.json> --diff-image <visual-diff.png> --strict
```

Pixel thresholds tolerate small antialiasing differences; geometry defaults to a one-CSS-pixel tolerance and always fails new overlaps, missing elements, or changed visibility/overflow. Never replace an approved baseline automatically. Inspect every diff: accept intentional changes through a new review version; otherwise create a finding or record a justified validation gap.

Pixel comparison uses Pillow (`PIL`). If the default Python runtime lacks it, use the bundled workspace Python runtime that provides Pillow; do not silently skip the regression gate.

## Delivery gate

A production review bundle contains:

- `ui-ir.json` and `ui-preview.html`;
- `platform-profile-report.json`;
- `ui-coverage.json` and optional Markdown summary;
- `ui-interaction-matrix.json` for stateful work;
- `ui-diagnostics.json` for primary and compact profiles;
- candidate screenshots and geometry snapshots;
- `visual-regression.json` plus a diff image when pixels changed.

Report each non-pass result. A successful script invocation is not equivalent to a passing report.
