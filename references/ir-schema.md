# UI IR schema

Use JSON with `version: 1`. The renderer tolerates omitted optional fields but every screen needs `id`, `name`, and `root`.

```json
{
  "version": 1,
  "project": {"name": "Example", "root": "C:/repo"},
  "platforms": ["android-compose"],
  "design": {"mode": "reconstruct", "targetPlatforms": ["android"]},
  "screenTree": [
    {
      "id": "area-admin",
      "label": "Admin",
      "children": [
        {
          "id": "group-system",
          "label": "System",
          "children": [
            {"screenId": "home", "label": "Overview"}
          ]
        }
      ]
    }
  ],
  "discoveredScreens": [
    {"name": "HomeScreen", "file": "feature/home/HomeScreen.kt", "line": 18, "platform": "android-compose"}
  ],
  "discoveredRoutes": [
    {"route": "/home", "file": "navigation/AppNav.kt", "line": 22}
  ],
  "discoveredNavigationTargets": [
    {"target": "#processes", "label": "Processes", "file": "admin.html", "line": 47}
  ],
  "viewport": {"width": 390, "height": 844, "device": "phone", "frame": false, "background": "$colors.surface"},
  "fidelity": {"status": "translated", "sourceDerived": true},
  "fonts": [
    {"family": "Project Sans", "asset": "assets/fonts/project-sans.woff2", "weight": 400, "style": "normal"}
  ],
  "tokens": {
    "colors": {"primary": "#6750A4", "surface": "#FFFBFE", "onSurface": "#1D1B20"},
    "spacing": {"sm": 8, "md": 16},
    "radii": {"md": 12},
    "typography": {"body": {"fontFamily": "Roboto", "fontSize": 16, "lineHeight": 24}}
  },
  "componentCatalog": {
    "status": "ready",
    "enforce": true,
    "components": [
      {
        "id": "ui/components/PrimaryButton.kt#PrimaryButton",
        "name": "PrimaryButton",
        "platform": "android-compose",
        "kind": "project",
        "source": {"file": "ui/components/PrimaryButton.kt", "line": 14, "symbol": "PrimaryButton"},
        "inspection": "mapped",
        "variants": ["primary", "secondary"],
        "states": ["enabled", "disabled", "loading"],
        "tokenRefs": ["$colors.primary", "$typography.body"],
        "mapping": {"nodeType": "button", "confidence": "high"}
      }
    ]
  },
  "screens": [
    {
      "id": "home",
      "name": "Home",
      "route": "/home",
      "fragment": "#home",
      "logicalView": true,
      "platform": "android",
      "source": {"file": "feature/home/HomeScreen.kt", "line": 18, "symbol": "HomeScreen"},
      "confidence": "high",
      "root": "home-root",
      "viewport": {"width": 390, "height": 844, "device": "phone"}
    }
  ],
  "nodes": {
    "home-root": {
      "type": "container",
      "component": "Column",
      "layout": {"direction": "column", "gap": 16, "padding": 24, "width": "fill", "height": "fill"},
      "style": {"background": "$colors.surface", "color": "$colors.onSurface"},
      "children": ["home-title", "home-action"],
      "source": {"file": "feature/home/HomeScreen.kt", "line": 19, "symbol": "Column"},
      "confidence": "high"
    },
    "home-title": {
      "type": "text",
      "text": "Home",
      "style": {"typography": "$typography.body"},
      "source": {"file": "feature/home/HomeScreen.kt", "line": 22, "symbol": "Text"},
      "confidence": "exact"
    },
    "home-action": {
      "type": "button",
      "text": "Continue",
      "component": "PrimaryButton",
      "componentRef": "ui/components/PrimaryButton.kt#PrimaryButton",
      "layout": {"minHeight": 48, "paddingHorizontal": 20, "paddingVertical": 12},
      "style": {"background": "$colors.primary", "color": "#FFFFFF", "radius": 20, "typography": "$typography.body"},
      "standardRef": "material3.Button",
      "semantics": {"role": "button", "label": "Continue", "targetSize": {"width": 120, "height": 48}},
      "action": {"type": "back"},
      "source": {"file": "feature/home/HomeScreen.kt", "line": 28, "symbol": "PrimaryButton"},
      "confidence": "high"
    }
  }
}
```

Versioned proposals, expert-audit findings, and annotations live under `review`; base `nodes` remain the `Before` snapshot. Read [review-workflow.md](review-workflow.md) for the schema and approval lifecycle and [ui-reviewer.md](ui-reviewer.md) for finding quality and severity rules.

## Platform families and profiles

`design.targetPlatforms` uses platform families rather than framework names. Supported families and their default machine-readable profiles are:

| Platform family | Default profile | Common scanner adapters | Standard-reference prefix |
| --- | --- | --- | --- |
| `android` | `material3` | `android-compose`, `android-views` | `material3.` |
| `android-tv` | `android-tv` | `android-tv-compose`, `android-tv-views`, `android-tv-leanback` | `androidtv.` |
| `ios` | `apple-hig` | `swiftui`, `uikit` | `apple.` |
| `macos` | `macos-hig` | `swiftui-macos`, `appkit`, `mac-catalyst` | `macos.` |
| `windows` | `windows-fluent` | `windows-winui`, `windows-wpf`, `windows-xaml` | `windows.` |
| `web` | `web-platform` | `web`, `react-web` | `web.` |

Flutter and React Native adapters resolve to explicit target families; never infer one shared visual profile for all outputs. A TV screen uses a 16:9 reference viewport (`960×540` dp at mdpi) and records safe-content insets. Desktop screens record a resizable window viewport, not a fixed device frame. Use `standardRef` on every generated or redesigned control, for example `androidtv.Card`, `macos.Toolbar`, or `windows.NavigationView`.

An optional generated interaction plan lives at `review.scenarioPlan` and follows the output of `scripts/generate_interaction_matrix.py`. It is a bounded test plan, not an executed result. Store observations and `pass`/`fail` outcomes only in `review.audit.interactionChecks`. Machine-readable platform profile IDs and constraints come from [platform-profiles.json](platform-profiles.json); final quality artifacts follow [quality-automation.md](quality-automation.md).

## Runtime diagnostics

`review.diagnostics` configures the autonomous checks embedded in the standalone HTML:

```json
{
  "review": {
    "revision": "checkout-review-v1",
    "diagnostics": {
      "profiles": [
        {"id": "desktop", "label": "Desktop 1180×760", "viewport": {"width": 1180, "height": 760}, "zoomLevels": [0.2, 1, 2]},
        {"id": "narrow", "label": "Narrow 760×820", "viewport": {"width": 760, "height": 820}, "zoomLevels": [0.2, 1, 2]}
      ],
      "scenarios": [
        {"id": "zoom-reset", "label": "Zoom reset", "kind": "zoom-reset"},
        {"id": "overview-geometry", "label": "Overview geometry", "kind": "overview-geometry"},
        {"id": "menu-exclusivity", "label": "Menu interaction", "kind": "menu-exclusivity"},
        {"id": "layout-integrity", "label": "Layout integrity", "kind": "layout-integrity"},
        {"id": "accessibility-basics", "label": "Accessibility basics", "kind": "accessibility-basics"},
        {"id": "state-matrix", "label": "Component states", "kind": "state-matrix"},
        {"id": "navigation-flow", "label": "Navigation flow", "kind": "navigation-flow"},
        {"id": "contrast-focus", "label": "Contrast and keyboard", "kind": "contrast-focus"}
      ]
    }
  }
}
```

Profile IDs and scenario IDs are unique. `viewport` is `current` or a positive `{width,height}` object. Fixed objects run in isolated same-document iframe sandboxes whose CSS viewport really has that width and height; use at least one primary and one narrow deterministic profile for a completed audit. `current` is useful for ad-hoc inspection but is not a substitute for the deterministic matrix. Zoom levels stay between `0.2` and `2`. Supported scenario kinds are `zoom-reset`, `overview-geometry`, `menu-exclusivity`, `layout-integrity`, `accessibility-basics`, `state-matrix`, `navigation-flow`, and `contrast-focus`. The renderer adds the last three hardening scenarios when an older IR omits them; new IR should declare them explicitly.

The generated runtime report is local review state rather than baseline IR evidence. It contains timestamps, active version, profiles, scenarios, pass/warning/fail counts, and individual checks with metrics. The workbench persists it in browser storage and includes it as `diagnostics` in `ui-review-feedback.json`. A non-pass check may produce a complete item in `runtimeFindings`; it uses the expert-finding fields plus `runtimeDiagnosticId` and optional measured `instances`, and is validated/merged into `review.audit.findings` by `merge_review_state.py`. Runtime diagnostics supplement the expert audit; they do not replace task analysis, platform judgment, or UX findings.

`review.revision` identifies the authored review revision. The workbench combines it with a content hash and stores that computed value beside browser state. On mismatch, stale state is quarantined until the reviewer explicitly migrates still-valid references or discards the snapshot; it is never applied silently.

## Expert audit

An evidence-based review uses this shape:

```json
{
  "review": {
    "audit": {
      "status": "complete",
      "summary": "The primary task is understandable, but recovery and action priority need correction.",
      "scope": {
        "tasks": ["Create and publish a project"],
        "screens": ["project-form", "project-summary"],
        "states": ["default", "loading", "error", "success"],
        "interactions": ["Submit and recover from an error", "Navigate back without losing input"],
        "uxLenses": ["information-architecture", "discoverability", "action-placement", "iconography", "control-ergonomics", "density", "feedback", "adaptive-behavior"],
        "excluded": [{"area": "Billing", "reason": "Outside requested flow"}]
      },
      "interactionChecks": [
        {
          "id": "interaction-submit-error-retry",
          "startState": "Completed form",
          "actions": ["Submit", "Observe error", "Correct field", "Submit again"],
          "expected": "Input is retained, error and focus identify the field, retry succeeds.",
          "observed": "The error replaces the form and clears input.",
          "result": "fail",
          "viewports": ["desktop-primary", "narrow"],
          "inputMethods": ["pointer", "keyboard"],
          "findingIds": ["finding-project-error-recovery"]
        }
      ],
      "layoutChecks": [
        {
          "id": "layout-primary-actions",
          "kind": "control-padding",
          "scope": "Primary action row",
          "viewports": ["desktop-primary", "narrow"],
          "zoomLevels": ["Fit", "100%", "200%"],
          "metrics": ["baseline delta", "four-side padding", "line count", "scrollWidth/clientWidth", "scrollHeight/clientHeight"],
          "expected": "Sibling controls share a baseline, equal padding, and one-line contained labels.",
          "observed": "The secondary action wraps and shifts below the primary label.",
          "result": "fail",
          "findingIds": ["finding-project-error-recovery"]
        }
      ],
      "uxAssessment": [
        {
          "lens": "action-placement",
          "status": "finding",
          "observation": "The consequential submit action is visually grouped with secondary navigation.",
          "findingIds": ["finding-project-error-recovery"]
        }
      ],
      "validationGaps": ["Runtime focus order requires testing after implementation."],
      "scorecard": [
        {"category": "error-recovery", "open": 2, "high": 1, "basis": "finding-counts"}
      ],
      "findings": [
        {
          "id": "finding-project-error-recovery",
          "title": "Submission failure loses recovery context",
          "category": "error-recovery",
          "severity": "high",
          "confidence": "high",
          "screenId": "project-form",
          "nodeId": "project-submit-error",
          "observation": "The error replaces the form and removes the entered values.",
          "impact": "The user must repeat work and cannot identify which value failed.",
          "recommendation": "Keep entered values, place an inline summary above the form, and focus it after failure.",
          "evidence": [
            {"type": "source", "ref": "ProjectForm.kt#SubmitError", "note": "The error branch replaces form content."},
            {"type": "accessibility-standard", "ref": "WCAG22.3.3.1", "note": "Errors need identification in text."}
          ],
          "effort": "medium",
          "proposalVersionId": "proposal-recovery",
          "decisionId": "decision-project-error-recovery",
          "status": "open"
        }
      ]
    }
  }
}
```

Finding IDs are stable across iterations. `severity` is `blocker`, `high`, `medium`, or `low`; `confidence` is `high`, `medium`, or `low`; `effort` is `small`, `medium`, or `large`. Each finding needs at least one evidence entry with `type`, `ref`, and `note`. Use `systemic: true` plus `instances` for one repeated root cause. A finding links to `proposalVersionId` or provides `noProposalReason`. Correction versions may list `findingIds` so the workbench can open the applicable comparison directly. They separately list only verified corrections in `resolvedFindingIds`; those findings are hidden on that version but retained on the immutable baseline. Do not infer resolution merely from `findingIds`.

For a completed expert audit, `scope.interactions`, `scope.uxLenses`, `interactionChecks`, `layoutChecks`, and `uxAssessment` are required. Interaction and layout results are `pass`, `fail`, or `not-run`; `complete` audits cannot include `not-run`. Every failed interaction/layout entry needs non-empty `findingIds`, and every referenced ID must exist in `audit.findings`. `layoutChecks.kind` must cover `typography`, `sibling-alignment`, `control-padding`, `text-containment`, and `icon-label-optics`. UX statuses are `pass`, `finding`, or `gap`; `finding` requires valid `findingIds`. Use `gap` only when `validationGaps` explains the missing evidence.

## Screen hierarchy

`screenTree` is required. Group nodes contain `id`, `label`, and non-empty `children`; leaf nodes contain `screenId` and an optional shorter `label`. Every screen must occur exactly once. Use as many group levels as the real information architecture requires, normally product area → navigation group → screen.

The workbench renders this tree in the left sidebar, opens ancestors of the active screen, highlights the active leaf in blue, shows its full breadcrumb in the toolbar, and lets the reviewer hide or restore the entire sidebar. Hovering or focusing a `navigate` control previews its destination in amber and shows the destination breadcrumb, so current and prospective screens remain visually distinct. When the scan only knows files and platforms, it creates a provisional platform → source file → screen tree; refine that tree from actual navigation before review.

## Node types

- `container`: flex/grid/overlay structure. `layout.direction` is `row`, `column`, `grid`, or `overlay`.
- `text`: visible text.
- `button`: interactive action.
- `input`: text input; use `placeholder`, `value`, and `inputType`.
- `image`: use `asset` with a repo-relative path.
- `icon`: use `asset`, inline `svg`, or a textual `iconName` fallback marked approximate.
- `card`: bounded content surface.
- `list`: repeated content; provide explicit fixture children for review.
- `spacer`: layout-only node.
- `custom`: unsupported or project-specific construct; render a labeled placeholder and explain the fidelity risk.

## Layout and style

Supported layout fields include:

- structure: `direction`, `display`, `gap`, `rowGap`, `columnGap`, `columns`, `rows`, `align`, `justify`, `alignSelf`, and `wrap`;
- geometry: `width`, `height`, `minWidth`, `maxWidth`, `minHeight`, `maxHeight`, and `aspectRatio`;
- insets: `padding`, `paddingHorizontal`, `paddingVertical`, `paddingTop`, `paddingRight`, `paddingBottom`, `paddingLeft`, and equivalent `margin*` fields;
- positioning: `position`, `top`, `right`, `bottom`, `left`, `zIndex`, `order`, `grow`, `shrink`, `flexBasis`, `overflow`, `overflowX`, and `overflowY`.

Supported style fields include backgrounds, color, whole/per-side borders, whole/per-corner radii, outlines, opacity, shadows, font family/size/weight/style, line height, letter spacing, alignment, decoration, transform, filtering, object fit/position, whitespace, overflow wrapping, text overflow, cursor, visibility, and `placeholderColor`. Use `style.css` only for source-derived CSS properties not represented by named fields; it must not contain invented presentation defaults.

Local font records use `family`, repo-relative `asset`, `weight`, and `style`. The renderer embeds them as data URLs. Remote assets and paths outside the project root are rejected.

Token references start with `$`, for example `$colors.primary` or `$spacing.md`. Keep unresolved references intact and list them in `warnings`.

## Fidelity and provenance

Use one of:

- `exact`: literal asset, token, text, or mapped component renderer.
- `high`: direct declarative translation with complete layout and style information.
- `approximate`: inferred platform behavior or incomplete styling.
- `unsupported`: custom drawing, runtime-generated UI, or missing source context.

Meaningful nodes should carry `source.file`, `source.line`, `source.symbol`, and `component` when known. These fields let preview annotations map back to code.

When a project component catalog is enforced, nodes using catalogued components also carry `componentRef`. The catalog entry must be inspected and mapped before review.

The scanner emits `fidelity.status: inventory`. In `reconstruct`, change it to `translated` with `sourceDerived: true` only after replacing placeholders. In `generate` or `redesign`, use `fidelity.status: designed` and provide the `design` metadata described in [design-modes.md](design-modes.md). The renderer refuses unsupported placeholders, incomplete appearance, weak provenance/evidence, missing platform profiles, missing semantics, unexplained custom controls, and undersized interactive targets. If a leaf intentionally inherits all presentation, set `inheritsAppearance: true`; use `inheritsTypography: true` only when a control's typography is inherited but its geometry and surface are explicit. `--allow-draft` exists only for diagnostics.

Generated/redesigned interactive nodes use `standardRef` or per-platform `standardRefs`, plus `semantics.role`, `semantics.label`, and `semantics.targetSize`. Use `decisionId` only when it matches a reasoned entry in `design.decisions`. See [platform-standards.md](platform-standards.md).

## Screens, modes, and interactions

Keep `discoveredScreens` and `discoveredRoutes` from the scan. Screen identity is `<source.file>#<source.symbol>` and should match `<file>#<name>` in the discovery record. False positives use entries such as `{"key":"generated/FakeScreen.kt#FakeScreen","reason":"generated preview-only wrapper"}` in `fidelity.excludedScreens`; route exclusions use `{"route":"/legacy","reason":"unreachable legacy route"}`.

For one-document applications, use one screen per independently selectable panel and preserve its `fragment`, for example `#processes`. Keep the common sidebar in each logical screen (shared node subtrees are allowed), and map the matching menu item to that screen with `action: {"type":"navigate","target":"processes"}`. The audit blocks discovered navigation targets that have no screen or no incoming navigation action.

The renderer automatically provides:

- `All screens`: every screen rendered simultaneously as a non-interactive overview;
- `Prototype`: the selected screen with navigation and state actions enabled;
- `Single screen`: the selected screen with navigation frozen for focused review;
- `Before / After`: version comparison in split or overlay form;
- `Interact` / `Inspect` / `Comment`: an independent switch for clicks, provenance inspection, or node-anchored annotations.

Supported actions are `navigate`, `back`, `set-node-state`, `toggle-node-state` (alias `toggle`), and `reset-state`. `navigate` uses a screen ID in `target`. State actions use a node ID in `target`, plus `state` and optional `offState`. Define visual variants in `node.states`, where each named variant can override node fields and merge `layout` and `style`.
