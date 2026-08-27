# Evidence-based UI/UX reviewer

Use this workflow when the user asks to review, audit, critique, simplify, or improve an existing interface and expects corrected visual proposals.

## Review contract

The reviewer must produce three connected artifacts:

1. an accurate, source-linked `Before` reconstruction;
2. a prioritized audit whose findings are anchored to screens and nodes;
3. one or more restrained correction versions that can be opened directly in `Before / After`.

Do not edit application source during the review. Do not redesign untouched regions, invent product requirements, or turn personal taste into a defect. A missing runtime fact remains a validation gap rather than a confident finding.

## Evidence order

Use the strongest applicable evidence in this order:

1. explicit product requirements, user feedback, research, analytics, or support evidence supplied in scope;
2. repository behavior, task flow, content, design tokens, components, platform versions, and intentional project conventions;
3. official target-platform guidance from [platform-standards.md](platform-standards.md), including accessibility requirements;
4. established usability heuristics for visibility, match to user language, control and recovery, consistency, error prevention, recognition, efficiency, minimalism, error recovery, and help;
5. a clearly labelled inference with `confidence: low` when stronger evidence is unavailable.

Never fabricate research, analytics, user intent, legal requirements, or runtime accessibility results. Heuristics can identify risk, not prove that users fail.

Use stable heuristic references when needed: `heuristic.visibility`, `heuristic.real-world-language`, `heuristic.user-control`, `heuristic.consistency`, `heuristic.error-prevention`, `heuristic.recognition`, `heuristic.efficiency`, `heuristic.minimalism`, `heuristic.error-recovery`, and `heuristic.help`. Pair a heuristic with source evidence and a platform/accessibility reference whenever the finding depends on a concrete control or behavior.

## Scope before scoring

Record:

- audited platforms and installed UI frameworks;
- primary and secondary user tasks;
- included screens, logical views, routes, and relevant states;
- excluded areas with reasons;
- available evidence and validation gaps;
- viewport classes, input methods, themes, localization/RTL, and accessibility conditions in scope.

Review the complete requested flow, not only a visually representative screen. Check default, loading, empty, error, offline, permission, disabled, success, destructive confirmation, long content, text scaling, and adaptive layouts where applicable.

## Review lenses

Evaluate only lenses relevant to the product and platform:

- task flow and information architecture;
- navigation, orientation, back/cancel, and context preservation;
- visual hierarchy, density, grouping, alignment, spacing, and typography;
- action priority, affordance, labels, discoverability, and icon comprehension;
- forms, validation, error prevention, retained input, and recovery;
- feedback, progress, system status, empty/loading/error/success states;
- platform component and interaction conformity;
- accessibility semantics, focus, keyboard, target size, contrast, scaling, motion, and assistive technology structure;
- responsive/adaptive behavior, safe areas, localization expansion, RTL, and long content;
- transient surfaces and interaction sequences: menus, popovers, drawers, dialogs, tooltips, selection changes, repeated actions, and dismissal behavior;
- consistency with the project's mapped component system;
- content clarity, terminology, destructive wording, and unnecessary cognitive load;
- privacy, trust, irreversible actions, and exposure of sensitive information when visible in the UI.

Do not reward decoration. Simpler means fewer decisions, clearer grouping, safer defaults, less repetition, or a shorter task path—not merely fewer visible elements.

## Mandatory interactive behavior pass

A visual snapshot is insufficient when the deliverable contains working controls. Exercise the generated HTML preview before completing the review, without running the real application:

1. Run every workbench view at least once: `All screens`, `Prototype`, `Single screen`, and the dedicated `Compare` view when retained versions are available. Switch the active ordinary-view version independently.
2. In `All screens`, test Fit plus manual zoom at 20%, 100%, and 200%. Screen geometry and relative positions must remain stable: zoom scales one shared canvas, its scrollable bounds grow or shrink with that canvas, and cards must not reflow into or overlap one another.
3. Open each application-menu item in sequence. At most one menu or popover may remain open. Verify dismissal by selecting an item, clicking outside, pressing `Escape`, changing view, and reopening the same trigger.
4. Exercise navigation, back/forward, panel show/hide, panel resizing, interaction-mode changes, repeated clicks, and the relevant product menus, drawers, dialogs, tabs, and state actions. Check both the end state and intermediate/transient states.
5. Repeat the interaction pass at the primary review viewport and one narrower adaptive viewport, using pointer and keyboard paths where the control supports both.

Record an observed failure as a finding with the exact action sequence, start state, resulting state, affected screen or workbench region, and user impact. If browser interaction is unavailable, list these scenarios as validation gaps and do not claim the interactive review is complete.

### State-transition and cross-control matrix

Inventory every stateful control and every visible value derived from it. For each transition, verify the complete contract rather than checking only whether the main content changed:

- trigger state, action, expected next state, and a repeated/reverse action;
- visual selection/pressed/open/disabled state;
- text, number, badge, tooltip, status, and accessible-name synchronization;
- focus destination, keyboard path, dismissal, and history behavior;
- effects on dependent controls, panels, menus, selection, scroll position, and persisted state;
- geometry at the new state: clipping, overlap, reflow, occlusion, reachable scroll bounds, and stable anchors.

Include paired and chained actions that can expose stale or conflicting state, for example: zoom → reset → zoom, Fit → resize panel → Fit, open menu A → open menu B → outside click, select node → zoom → hide panel → restore panel, and switch view → browser Back/Forward. Test boundary values and at least one intermediate value, not only defaults.

The audit records these checks under `review.audit.interactionChecks`. Each entry states `id`, `startState`, `actions`, `expected`, `observed`, `result`, `viewports`, and `inputMethods`. A `complete` audit cannot contain an untested (`not-run`) interaction check.

After the reasoned audit and proposal render, run the HTML Diagnostics Runner. Use its measured report to catch state synchronization, shared-canvas drift/overlap, menu conflicts, text containment, padding/height variance, small targets, and missing accessible names across every rendered screen. Reconcile every failure with the expert findings or a documented false-positive/validation gap. Automated geometry and DOM checks never replace the separate UX assessment: they cannot decide whether information architecture, icon meaning, action priority, cognitive load, or platform idiom is appropriate.

### Mandatory typography and geometry pass

Treat text and spacing as measurable layout, not as subjective polish. For every toolbar, menu, form row, repeated card, and button group at the reviewed viewport/zoom combinations:

- define the intended typography roles and verify a coherent hierarchy of family, size, weight, line height, color, and emphasis;
- compare sibling label baselines and the top, center, and bottom edges of their control boxes; investigate visible deviation greater than 1 CSS px after normalizing page transforms;
- measure effective top/right/bottom/left padding, icon-label gap, target box, and spacing between adjacent controls; equal variants must use equal geometry unless the difference is intentional and recorded;
- count rendered text lines and compare `scrollWidth/clientWidth` and `scrollHeight/clientHeight`; flag unintended wrapping, clipping, ellipsis, overflow, or text leaving its container;
- verify active, inactive, hover, focus, disabled, loading, and selected variants do not change label position or control dimensions unexpectedly;
- repeat with long localized labels, text scaling, narrow width, Fit, 100%, and the supported zoom boundaries; distinguish deliberate wrapping from accidental wrapping;
- visually check optical alignment of icons and text after numeric measurements, because equal boxes do not guarantee equal perceived alignment.

Store results under `review.audit.layoutChecks`. Each entry includes `id`, `scope`, `viewports`, `zoomLevels`, `metrics`, `expected`, `observed`, `result`, and linked `findingIds` when it fails. A completed audit requires checks for typographic hierarchy, sibling alignment/baseline, control padding, text containment, and icon-label optical alignment. If geometry cannot be measured, mark the audit partial and record the validation gap.

## Separate UX assessment

Run a dedicated UX assessment after correctness and interaction testing. Do not collapse UX into a list of rendering bugs. Evaluate:

- whether the primary task, current mode, current screen, navigation availability, and next likely action are evident without trial clicks;
- whether information architecture and grouping match the user's mental model and keep related controls together;
- whether actions are placed where users expect them, ordered by frequency and consequence, and separated when accidental activation is costly;
- whether labels, icons, and tooltips make the outcome predictable before activation;
- whether icon metaphors are conventional for the target platform, visually consistent in family, stroke/fill, optical size, alignment, and emphasis, and distinguishable from adjacent icons;
- whether icon-only controls have accessible names and whether unfamiliar or ambiguous icons retain a visible label or concise tooltip;
- whether button size, target area, spacing, hierarchy, disabled/pressed/loading feedback, and destructive styling fit the platform and input method;
- whether density, repeated controls, competing emphasis, long panels, and simultaneous tool groups overload the interface or hide the primary workflow;
- whether progressive disclosure removes complexity without hiding essential state or navigation;
- whether the interface remains coherent at supported widths, zoom levels, text scaling, localization expansion, themes, and input methods.
- whether typography roles create an intentional hierarchy and repeated controls share stable baselines, padding, label position, and optical alignment.

Treat visual beauty as coherence, balance, craft, and fit with the project/platform—not as personal taste. Record assessments under `review.audit.uxAssessment`, with one entry per relevant lens containing `lens`, `status`, `observation`, and linked `findingIds` or a validation gap. A deep review must explicitly cover information architecture, discoverability, action placement, iconography, typographic hierarchy, spacing/alignment, control ergonomics, density/cognitive load, feedback/state visibility, and adaptive behavior.

## Finding quality gate

Every finding under `review.audit.findings` contains:

- stable `id` and concise `title`;
- `category` and `severity`;
- `confidence`: `high`, `medium`, or `low`;
- `screenId` and, when possible, `nodeId` plus source mapping;
- `observation`: what is verifiably present;
- `impact`: the user or business consequence;
- `recommendation`: a concrete correction that preserves stated constraints;
- non-empty `evidence`, each with `type`, `ref`, and a short `note`;
- `effort`: `small`, `medium`, or `large`;
- `proposalVersionId` and optional `decisionId`, or `noProposalReason`.

Valid evidence types are `requirement`, `user-feedback`, `research`, `analytics`, `source`, `project-pattern`, `platform-standard`, `accessibility-standard`, and `heuristic`. A URL or standard identifier must be specific enough to verify; `best practice` is not evidence.

Use one finding for one causal problem. When a design-system defect repeats, create one `systemic: true` finding with `instances` rather than flooding the audit with duplicates.

## Severity and prioritization

- `blocker`: prevents the primary task, causes data loss/security/safety risk, or excludes a required user group with no viable workaround.
- `high`: creates likely errors, severe disorientation, inaccessible core interaction, or substantial abandonment risk.
- `medium`: adds recurring friction, ambiguity, unnecessary effort, or inconsistent platform behavior without blocking completion.
- `low`: localized clarity, consistency, or polish issue with limited task impact.

Do not infer severity from visual ugliness. Consider task criticality, reach/frequency, reversibility, evidence confidence, and implementation effort. Keep the scorecard traceable to findings; never invent an overall numeric score from intuition.

## Correction proposals

1. Preserve the baseline nodes and routes.
2. Create a primary proposal that fixes the highest-value coherent group with the fewest unrelated changes.
3. Link the version's `findingIds` and `decisionIds` to the audit.
4. Use project components first, then the platform baseline. Record deviations.
5. Preserve business rules, data availability, analytics hooks, accessibility labels, and accepted content unless the finding explicitly addresses them.
6. Add another variant only when it demonstrates a meaningful tradeoff such as density versus guidance or persistent versus progressive disclosure.
7. Keep unresolved runtime questions in `review.audit.validationGaps`; do not fake them in HTML.

Each blocker/high finding must either open a corrected comparison or explain why a responsible visual proposal cannot be made without more evidence.

## Presentation order

Present:

1. a concise audit summary and coverage statement;
2. blocker/high findings first, then medium/low;
3. systemic findings before repeated instances;
4. direct navigation to the affected screen/node;
5. `Before / After` for each linked proposal;
6. tradeoffs and validation gaps;
7. explicit design approval controls, separate from source-edit approval.

The HTML workbench lets the user filter findings, focus the affected element, compare its proposed correction, and accept/reject the finding. Export those decisions with annotations for the next iteration.
