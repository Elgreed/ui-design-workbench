# Component registry and review workflow

Use this reference when a task includes project-component reuse, Before/After comparison, comments, or staged design approval.

## Component catalog

`scan_ui.py` emits conservative `componentCatalog.components` candidates. The inventory is not a usable design system until each relevant entry has been inspected recursively.

For every project component used by a screen:

1. Inspect its implementation, default parameters, variants, states, reached tokens, assets, semantics, and platform dependency.
2. Update the catalog entry with `inspection: mapped`, its actual `variants`, `states`, and `tokenRefs`, plus a renderer mapping such as `{"nodeType":"button","confidence":"high"}`.
3. Set the corresponding node's `componentRef` to the catalog entry ID.
4. Use `inspection: excluded` only with a non-empty `reason`, for example a preview-only wrapper or a component unrelated to rendered UI.
5. Mark `componentCatalog.status: ready` only when every component used in the review scope is mapped or reasonedly excluded.

When `componentCatalog.enforce` is true, the renderer blocks an uninspected catalog or project component use without a mapped `componentRef`. New project components require a design decision explaining why existing catalog entries are insufficient.

## Review versions

Base `nodes` are the immutable `Before` snapshot. Store proposals as sparse overrides rather than overwriting base nodes:

```json
{
  "review": {
    "sessionId": "checkout-review-2026-08-24",
    "revision": "checkout-review-v1",
    "baselineVersion": "baseline",
    "activeVersion": "proposal-1",
    "versionDecision": "pending",
    "versions": [
      {
        "id": "baseline",
        "label": "Before",
        "kind": "baseline",
        "status": "approved",
        "nodeOverrides": {}
      },
      {
        "id": "proposal-1",
        "label": "After · clearer checkout action",
        "kind": "proposal",
        "parent": "baseline",
        "status": "proposal",
        "summary": "Clarifies the primary action without changing checkout behavior.",
        "findingIds": ["finding-checkout-action-priority"],
        "decisionIds": ["decision-checkout-action"],
        "nodeOverrides": {
          "checkout-action": {
            "text": "Review order",
            "style": {"background": "$colors.primary"}
          }
        }
      }
    ],
    "annotations": []
  }
}
```

Version inheritance follows `parent`; later overrides merge node fields and merge `layout` and `style`. Keep IDs stable across iterations. Create a new proposal version for a materially different alternative instead of mutating an already reviewed version.

Set `review.revision` to a stable human-readable revision for the review bundle. The renderer combines it with a content hash. When browser storage belongs to an older revision, it does not silently replay stale selections or decisions; the reviewer can migrate annotations, decisions for still-existing finding IDs, diagnostics, and view context, or discard the old snapshot. Migration must filter missing screen, node, finding, and version references.

The HTML workbench provides split and overlay comparisons, highlights overridden nodes, and stores local review state in browser storage. Its canvas-first shell uses a narrow navigation rail, searchable screen tree, one compact document bar with the active ordinary-view version, a floating view palette with one pointer escape action, zoom-only bottom-right controls, and a contextual right panel. Properties and Comments activate their matching canvas modes from the rail, while Problems visibility is controlled inside the Problems panel rather than duplicated in the bottom palette. Compare is a dedicated view with explicit left/right version selectors. Side panels are independently collapsible and resizable on wide screens and mutually exclusive overlays at compact widths. `Approve version` means design approval only; it never authorizes source changes. Read [workbench-ui.md](workbench-ui.md) for the complete shell contract.

Workbench menus are transient, mutually exclusive surfaces: opening one closes the previous menu, and selecting an action, clicking outside, pressing `Escape`, or changing view closes the open menu. In `All screens`, zoom applies to one shared overview canvas; it must not change the per-screen preview scale, grid geometry, or relative card positions.

## Diagnostics Runner

Every review preview exposes a local Diagnostics Runner in the right panel. Configure it through `review.diagnostics`, run it after the final render, and export its report with the review state. For every fixed `{width,height}` profile, the renderer loads an isolated same-document sandbox at that real CSS viewport size; do not emulate a narrow profile by merely recording a label. The runner changes workbench states only temporarily and restores the starting screen, view, version, zoom, comparison mode, selected node, active highlight, scroll positions, and node states when it finishes.

The primary `Review` entry point is one button, `Запустить ревью`. It runs the configured scenarios across every assembled screen and fixed profile, creates or refreshes evidence-backed cards for every non-pass result, focuses that generated set in the findings list, and leaves the technical report under the collapsed `Диагностика` section. A repeated run reuses deterministic diagnostic finding IDs instead of duplicating cards. The launcher must show scope, running state, final issue count, and a clear rerun label.

The Review panel uses three isolated workspaces: `Сводка`, `Проблемы`, and `Изменения`. Summary reports exact screen/profile/check/state coverage and named run history. Problems groups automated failures by causal scenario and screen, keeps systemic findings ahead of instances, and supports source/screen/severity filtering plus bulk decisions. Changes contains the five-phase correction queue, result import, version comparison, design approval, and the source-planning boundary. A single sticky primary action advances to the next valid stage.

Never claim `all states` from screen count alone. Enumerate every declared `node.states` variant for each included screen and deterministic viewport profile, execute it, and report tested versus expected combinations. Keep unavailable loading/error/offline/localization/RTL or assistive-technology conditions as explicit gaps. `Current screen` scope may reduce runtime; `All screens` remains the default final-review scope.

After a completed local run, enable `Подготовить AI-ревью`. The generated HTML embeds its absolute review-directory path and creates a portable prompt/job for any filesystem-capable agent. A user still reviews and sends the prompt. With the optional `--agent codex` renderer adapter, the same job can also be prepared through the official `codex://new?prompt=...&path=...` deep link. Keep `ui-expert-review-request.json` as a portable fallback containing the complete IR, screen IDs, active version, runtime report, existing findings and decisions.

The workbench accepts either a complete returned UI IR or `ui-design-workbench-expert-review-result` with `requestRevision`, `project`, `summary`, `findings`, `versions`, and `resolvedFindingIds`. Continue accepting the legacy `ui-code-preview-expert-review-result` so existing review jobs remain importable. Reject an explicit mismatched request revision or project. Merge nodes, stable finding IDs, and sparse proposal versions without replacing baseline nodes; register new versions in Changes, make the latest imported proposal the active ordinary-view version and the default right side of Compare, record an import-history entry, and open Changes. Import never authorizes source edits.

For a headless/local smoke pass, open the generated file with `?diagnostics=run`; the runner starts automatically and exposes the same report in the diagnostics panel. This remains an offline HTML check and does not execute the application.

The dependency-free Node helper performs that pass and writes a reusable report:

```powershell
node <skill-dir>/scripts/smoke_preview.js <review-dir>/ui-preview.html --output <review-dir>/ui-diagnostics.json
```

Add `--screenshot <review-dir>/workbench.png --geometry-output <review-dir>/workbench-geometry.json --viewport-width 1440 --viewport-height 960` for reproducible pixel and DOM-geometry QA. Repeat at a compact width before delivery. Compare approved and candidate snapshots with `scripts/visual_regression.py` as described in [quality-automation.md](quality-automation.md).

Set `CHROME_PATH` when Chrome, Edge, or Chromium is outside the common Windows, macOS, or Linux locations. Add `--fail-on-findings` for CI gating; without it, detected UI problems are reported but do not make the helper itself fail.

The built-in scenarios check zoom-label/reset synchronization, stable overview-card geometry and scroll bounds, menu exclusivity, per-screen layout, declared component-state variants, navigation reachability, computed text contrast, keyboard reachability, toolbar alignment, target size, and accessible names. Group repeated non-pass checks by scenario and screen into one systemic runtime finding with measured instances. Exported runtime findings merge into `review.audit.findings`, so they remain actionable in the next revision. A failed automated check is evidence for investigation, not an automatic UX verdict: confirm the affected task and platform context, then link it to a finding or record why it is a false positive or validation gap.

## Expert audit findings

When `review.audit` exists, its findings appear above user annotations. Every failed `interactionCheck` or `layoutCheck`, and every `uxAssessment` with `status: finding`, links to one or more concrete cards through `findingIds`. Audit rows show the linked count and provide `Показать проблемы` plus `Все в исправление`; they are evidence summaries, not separate invisible work items.

Each finding has one stable review number used in both the Problems list and its canvas marker. A reliably mapped screen/node receives a numbered circle; clicking it opens one anchored description card and the top-right collapse action restores the circle. Current finding filters and the Problems visibility toggle update list and canvas together. Each finding can focus its affected screen/node and, when linked to `proposalVersionId`, open the dedicated Compare view. A proposal declares only verified corrections in `resolvedFindingIds`; those markers disappear on the corrected version but remain on the baseline side and in review history. The reviewer chooses `В исправление`, `Не исправлять`, or `Позже`. The correction queue reports how many selected findings already have a proposal and how many need a new one. `Создать вариант макета` prepares an agent task scoped to the review directory. The task includes selected finding IDs, active and baseline versions, annotations, review scope, and `sourceChangeAllowed: false`; it may create up to two alternatives only when a real UX tradeoff exists. `Скопировать задание` and `ui-fix-request.json` remain portable fallbacks.

The queue communicates five phases: `Проблемы → Выбрано → Макет → Согласовано → Проект`. Preparing a proposal never changes application source. Only after a proposal version is explicitly accepted does `Подготовить внедрение в проект` become available; it exports `ui-source-change-request.json` as a planning handoff and still requires a separate approval of files and diff before source edits.

Use [ui-reviewer.md](ui-reviewer.md) for evidence, severity, coverage, and proposal rules. Keep expert findings separate from user annotations: findings are the AI reviewer's reasoned analysis, while annotations are reviewer feedback on the current or proposed design.

## Annotation lifecycle

Annotations use statuses `new`, `in-progress`, `proposed`, `accepted`, `rejected`, or `resolved` and stay anchored to `screenId`, `nodeId`, and `versionId`. Preserve the source snapshot included by the workbench.

Process comments incrementally:

1. Export or copy `ui-review-feedback.json` from the preview.
2. Merge it into a new IR file. The merge preserves the exported runtime report as `review.diagnosticsReport`, appends validated `runtimeFindings` to `review.audit.findings`, and records the feedback revision, so an agent can reconcile failed checks with findings and proposals:

```powershell
python <skill-dir>/scripts/merge_review_state.py <review-dir>/ui-ir.json <review-dir>/ui-review-feedback.json --output <review-dir>/ui-ir-reviewed.json
```

3. Select one coherent group of `new` comments. Mark them `in-progress` before proposing changes.
4. Add a child proposal version containing only the required node overrides and link its decisions to the relevant annotations with `proposalVersionId` and a short response.
5. Render again. The reviewer accepts or rejects each annotation and the version separately.
6. Mark an annotation `resolved` only after its proposal is accepted. Rejected proposals remain in history and are never silently replaced.

Do not edit application source during this loop. After explicit source-edit approval, implement only the accepted version and list its affected source mappings.

## Offline boundary

The preview remains a standalone local HTML file and makes no network requests. It can copy or download a portable task and may optionally navigate to a provider's official local deep link. This requires no bridge server, localhost port, CLI process, or background service. Preparing or navigating is not submission: the workbench must ask the user to send the prompt and never claim that AI review or remediation started.

The agent task is restricted to the generated review directory. It may update `ui-ir.json`, regenerate `ui-preview.html`, and write validation artifacts, but it must not modify the source project or immutable baseline. When complete, the user returns to the preview and chooses `Обновить макет`. Export/copy of `ui-agent-job.json`, `ui-fix-request.json`, and `ui-expert-review-request.json` remains the recovery path when a native adapter is unavailable.

`merge_review_state.py` accepts either ordinary `ui-review-feedback.json` or the wrapped `ui-fix-request.json`. For a fix request it also preserves the selected IDs and requested action as `review.correctionRequest` before a new proposal is authored.
