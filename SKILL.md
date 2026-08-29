---
name: ui-design-workbench
description: Reconstruct, review, generate, or redesign repository UI as standards-aware interactive HTML previews; optionally guide ordinary UI implementation with Android, Android TV, Apple, Windows, or Web conventions. Do not use when the user only wants to run the real application.
metadata:
  compatibility: "Python 3.10+. MCP is optional; CLI works standalone."
---

# UI Design Workbench router

Use UIDW as a deterministic local utility. The CLI, not the skill prompt, owns scanning, cache invalidation, source graphs, IR, rendering, and projection checks.

## 1. Get compact context

Prefer MCP tools `ui_project` then `ui_scope` when the local UIDW MCP is configured. Otherwise use the complete CLI fallback:

```text
uidw --repo <repo> context --json
uidw --repo <repo> scope --ir <ui-ir.json> --screen <id> --budget 4000
```

If `uidw` is unavailable, run `python <skill-dir>/scripts/uidw.py ...`. Reuse a clean cache. Never paste or read the complete `ui-ir.json` when a scoped context can answer the task. Request another screen/finding scope only when needed.

If first-use context says `setupRequired`, ask only for `low`, `medium`, or `high` using its short descriptions. Mock-data depth follows that choice. Do not recommend a level. Optional `uiMode` remains off until explicitly enabled.

## 2. Route the request

- Reconstruct/generate/redesign: read [references/design-modes.md](references/design-modes.md), then only the matching platform section from [references/platform-standards.md](references/platform-standards.md). Use cached evidence and `uidw workbench`; validate transfer fidelity, not product UX.
- Explicit review/audit/critique: read [references/ui-reviewer.md](references/ui-reviewer.md) and [references/review-workflow.md](references/review-workflow.md). Review immutable Before only and work in bounded screen batches.
- Workbench chrome behavior: read [references/workbench-ui.md](references/workbench-ui.md).
- Ordinary UI source task with `uiMode.enabled=true`: read [references/ui-guidance-mode.md](references/ui-guidance-mode.md). Do not create a preview or review unless requested.
- Cache/install/agent integration question: read only [references/cache-protocol.md](references/cache-protocol.md) or [references/agent-integrations.md](references/agent-integrations.md), respectively.

## 3. Return sparse changes

Review/proposal agents write `ui-ir.patch.json`, never a replacement full IR:

```text
uidw patch validate <ui-ir.patch.json> --ir <ui-ir.json>
uidw patch apply <ui-ir.patch.json> --ir <ui-ir.json> --output <ui-ir.proposed.json>
```

Allowed operations are `upsert-findings`, `upsert-versions`, `merge-annotations`, and `record-verifications`. Baseline screens, nodes, tokens, themes, fixtures, and application source are immutable in this path. Create one restrained proposal by default; add a second only for a real UX tradeoff.

## Invariants

- Reconstruction, generation, redesign, Low/Medium/High, `workbench`, and `check` never trigger an automatic UI/UX audit. Only an explicit review request creates findings.
- Do not run the target app, emulator, simulator, build, or dev server unless separately requested. Headless checks may open only generated local HTML.
- Preserve discovered screens, routes, project components, platform idioms, tokens, themes, states, provenance, and unsupported gaps. Do not invent polish or browser-default replacements.
- For Android Views, treat navigation destinations and Activity/Fragment/Dialog classes as screens; treat layout items, cells, partials, Data Binding metadata, and navigation XML as components or topology rather than visual screens. Static includes may be expanded, but Data Binding expressions, custom views, constraints, styles/theme attributes, and runtime-injected content remain explicit gaps.
- HTML is a projection. Base IR is immutable Before; proposal versions are sparse overrides.
- Never label an Android HTML projection visually verified without separate Layoutlib/emulator screenshots or golden-image comparison evidence.
- Applying a proposal to real source requires a separate explicit `Apply to project` or direct-fix authorization, bounded source targets, incremental sync, and targeted verification. Never repeat the full AI review automatically.
- Keep cache and review artifacts outside source control unless the user explicitly requests otherwise.
