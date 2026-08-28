# Production workbench UI

Use this reference when generating the review workbench shell itself. It governs the editor chrome around reconstructed screens; it must never leak into the product UI being reviewed.

## Canvas-first information architecture

Give each persistent region one job:

- a narrow left rail starts with the conventional File/menu trigger, then switches Screens, Properties, Review, and Comments, exposes the language icon menu, controls right-panel visibility, and remains available when panels collapse;
- the left panel contains project/screen navigation, hierarchy, search, and low-priority coverage metadata;
- one compact document bar contains product identity, current screen path, and the single active version used by ordinary views; document actions and locale selection stay in the rail instead of consuming canvas width;
- the canvas owns screen previews and comparisons;
- a floating canvas palette switches view and interaction tools and independently toggles `Problems`;
- Compare is a dedicated view: its compact contextual bar selects the left and right versions and then the split/overlay layout. Do not mix version selection with view selection through a `Before / Compare / After` visibility group;
- a small bottom-right cluster owns zoom only;
- the right panel is contextual and shows only `Properties`, `Review`, or `Comments`. Every area is directly reachable from the rail, while Inspect and Comment canvas tools also open their matching area; do not add a duplicate tab row inside the panel.

Do not duplicate the same primary control in several persistent regions. Menu commands may repeat toolbar actions only as a conventional keyboard/menu fallback. Keep document actions, canvas tools, object properties, review decisions, and navigation visually distinct.

This structure follows stable patterns documented in Figma, Sketch, and Penpot: navigation/layers on the left, a dominant scrollable canvas, contextual properties on the right, dedicated prototype/comment modes, and collapsible UI for more canvas space.

Official pattern references:

- Figma navigation and panels: https://help.figma.com/hc/en-us/articles/360039831974-Explore-the-navigation-bar-and-left-sidebar
- Figma properties and prototype modes: https://help.figma.com/hc/en-us/articles/360039832014-Design-Prototype-and-view-Code-in-the-Properties-Panel
- Figma comments: https://help.figma.com/hc/en-us/articles/360039825314
- Sketch toolbar: https://www.sketch.com/docs/interface-and-settings/the-mac-app-interface/the-toolbar/
- Sketch layer list: https://www.sketch.com/docs/interface-and-settings/the-mac-app-interface/the-layer-list/
- Sketch canvas: https://www.sketch.com/docs/interface-and-settings/the-mac-app-interface/the-canvas/
- Penpot interface: https://help.penpot.app/user-guide/first-steps/the-interface/

## Progressive disclosure

- Show the screen tree by default on wide windows.
- Show only the active right-panel tab. Selecting an inspection or comment tool opens its matching tab.
- Keep diagnostics collapsed until requested or until a run has non-pass results.
- Present Review as three explicit user steps: `Проверка`, `Проблемы`, and `Исправление`. Each step must show its completion state and a short plain-language outcome.
- Keep exactly one visually primary contextual action in the sticky footer. It advances the workflow: check the interface, inspect issues, prepare a fix, compare it, approve it, and apply it.
- Selection is a separate transition: after choosing findings, step 2 says exactly how many are selected and offers `Перейти к исправлению · N`. It must not start proposal generation or show an apply-to-project action.
- Show `Применить исправления · N` only while step 3 is active, only after the selected proposal has been compared and approved. Steps 1 and 2 must never expose source-application wording.
- Count expert and runtime findings together in the human-facing result. Never report “no issues” while unresolved expert findings exist.
- Keep coverage, history, raw diagnostics, AI handoff, JSON import/export, and direct source changes inside collapsed `Дополнительно` or caution regions. They are escape hatches for advanced users, not parallel primary workflows.
- Keep finding observation and actions visible; place impact, recommendation, and evidence in an expandable detail region.
- Use the same stable number for each finding in the Problems list and on the canvas. Canvas markers remain circles until clicked, open one compact anchored card at a time, and expose an unambiguous top-right collapse control that restores the circle.
- Render unresolved user comments on the canvas as numbered markers from a distinct, non-severity color family. They open and collapse like findings but remain a separate semantic layer and list.
- Use short empty states that name the next direct action. Do not add tutorial paragraphs to compensate for ambiguous controls.
- Do not vertically stack the three steps or expose multiple competing “start/fix/export” buttons. Secondary actions may remain available inside expandable details but must not compete visually with the contextual primary action.
- Name versions by user meaning: `Исходный макет` and `Новый макет`, optionally followed by a concise proposal name. Do not expose unexplained `Before`/`After` labels. Fresh redesign previews open the newest proposal by default and clearly identify it as the new mockup; this does not imply that source files were changed.
- Keep the finding lifecycle explicit: `Найдена → Выбрана → Учтена в новом макете → Макет подтверждён → Применена → Проверена`. `resolvedFindingIds` stops at “Учтена в новом макете”; it must never make a card, step, or version look applied or verified. Only a targeted passing `verification` record may produce `Применено и проверено`.
- Show the proposal status persistently beside the version selector. Until source implementation and targeted verification are recorded, use `Ещё не применён к проекту` (or `Задание на применение подготовлено` after handoff), even after the proposal is approved.

## Controls and visual system

- Use one coherent inline SVG icon family with equal view boxes, stroke behavior, optical size, and alignment. Do not use mixed Unicode glyphs as workbench icons.
- Keep icon-only controls for conventional actions such as panel collapse, zoom, and export. Give every icon-only control an accessible name and concise tooltip.
- Retain visible labels for modes whose meaning is not safely conveyed by an icon alone. Labels may collapse at narrow widths.
- Use restrained neutral surfaces, one primary accent, semantic success/warning/error colors, subtle borders, and elevation only for floating or transient surfaces.
- Base dense desktop controls on a 28–32 px visual box while preserving at least a 24×24 CSS px WCAG target and larger targets where space permits.
- Use stable typography roles: 13 px panel/page title, 10–11 px primary control/body text, 8–9 px metadata. Never shrink essential task text merely to fit a panel.
- Equivalent segmented controls must share height, padding, baseline, icon box, and selected-state geometry.
- Localize every built-in workbench label, accessible name, tooltip, empty state, and toast at runtime with native-language choices (`Русский`, `English`) and persist the locale in local storage plus `?lang=`. Stable internal values may remain English. Never translate the reconstructed product, screen names, version names, findings, comments, or evidence.

## Adaptive behavior

- Wide layout: left navigation and contextual right panel may coexist.
- Compact desktop/tablet layout: panels become overlays. Opening one closes the other so the canvas retains a useful working width.
- Narrow layout: rail remains; panel labels and nonessential document-bar items collapse before controls disappear.
- Panel width, active tab, selected node, review filter, scroll, and collapse state persist by review revision.
- Persist review results independently from the generated shell version. Rebuilding `ui-preview.html` with unchanged target screens/nodes/versions must restore diagnostics, run history, selections, decisions, annotations, and view context automatically. Never let unload or incidental UI interaction overwrite a quarantined stale snapshot before the reviewer chooses migrate or discard.
- Version runtime diagnostics independently. An engine upgrade or a new run removes obsolete runtime findings but preserves expert findings, decisions, annotations, run history, and view context.
- Put `Сохранить ревью` and `Восстановить ревью` in File. Both are explicit actions; opening or checking a preview must never download a file.
- A panel opened from a finding, comment, inspection tool, diagnostic, or application menu must select the relevant tab automatically.

## Interaction contract

- `All screens`, `Prototype`, `Single screen`, optional `Variants`, and `Compare` are view modes and stay in one group. `Variants` is disabled when the current screen has neither extra scenarios nor extra source-evidenced themes; do not create filler states or themes merely to enable it. No other persistent control may also enter Compare.
- The bottom canvas palette keeps view modes plus only the pointer/Interact escape action. `Properties` and `Comments` in the rail activate Inspect and Comment respectively; the Problems visibility toggle lives inside the Problems panel, so these commands are not duplicated in the persistent bottom palette.
- Prototype is the only mode in which declared navigation changes screens. Entering it activates Interact, and selecting a screen in the tree preserves Prototype instead of silently falling back to Single screen.
- Single screen and Prototype show one stable compact control bar only when alternatives exist. Use fixed-width native selectors for Theme and State rather than one button per value; changing long labels must not resize the bar, move the canvas, or lose keyboard focus. One grid action opens `Variants`, which provides `By theme`, `By state`, and, only when both dimensions vary, `Matrix`. The matrix is split into visually separate theme sections; it must not flatten every combination into one unlabelled grid. Every device retains its theme, scenario patch, stable geometry, and label.
- Selecting a node synchronizes canvas highlight, layer/screen context, and the Properties or Comments panel without losing canvas scroll.
- Menus and popovers are mutually exclusive and close on action, outside click, `Escape`, or view change.
- Diagnostics must be observational: menu, keyboard, and interaction checks may use inert diagnostic controls but must never activate export, source-change, clipboard, navigation, or other consequential user commands. `ui-review-state.json` is downloaded only after an explicit user click on `Сохранить ревью`.
- The current screen and hovered navigation destination use distinct colors.
- Design approval and source implementation are separate phases with separate actions. The primary safe flow is preview → approve → `Apply to project`; the Problems workspace also exposes one unmistakable `Fix everything in project` fast path. Never label a generated After mockup as a completed project fix.
- Ordinary views render exactly one version chosen in the document bar. Version selection never changes the view mode.
- Compare mode allows any two retained review versions, not only baseline versus latest, while preserving the immutable baseline. Its left/right selectors and Split/Overlay controls appear only inside the dedicated Compare context and never duplicate the main view switcher.
- `Problems` is a visibility layer, not a separate review mode. Its marker set follows the current severity/source/screen/focused-block filters and never invents an anchor for a finding whose screen cannot be located.
- Clicking a finding marker opens its description on the canvas without navigating away. Opening a second marker closes the first; hiding Problems, changing screen/version, or collapsing the card leaves list state and numbering synchronized.
- Place markers beside the device they annotate, not in one global right-hand stack. In Compare, markers for the left version use the outer left edge and markers for the right version use the outer right edge; in ordinary views choose the nearest device edge to the anchor. User-comment markers follow the same placement rule in their own color.
- Bind each review to an immutable `reviewVersionId`, defaulting to the baseline. Version selectors change only what is displayed; they never retarget or rerun the review. Baseline finding markers appear only on that reviewed version, never on proposal versions, and only on the original side of Compare. A correction version lists the baseline findings it addresses in `resolvedFindingIds`; this means “shown as corrected in this proposal”, not source implementation or verification. Merely linking a finding with `findingIds`, setting legacy `status: resolved`, approving the proposal, or preparing an agent handoff is also insufficient.
- Finding and comment markers use the scrollable canvas as their containing block, resolve collisions independently for each rendered device and side, and are remeasured after zoom, canvas/device scroll, resize, version change, and panel layout change. They must remain beside the owning device; leader lines preserve the exact node relationship when collision avoidance changes the vertical slot.
- Holding the middle mouse button and dragging pans the entire canvas in both axes where overflow exists. Prevent browser autoscroll, show a grabbing cursor while active, and release capture on pointer up/cancel without activating product controls.
- Large reviews default to all screens but may be scoped to the current screen. The scope and exact counts must travel in diagnostics and AI handoff payloads.

## Production acceptance gate

Before delivery:

1. Render screenshots at a primary viewport and one compact viewport.
2. Inspect visual hierarchy, canvas area, panel competition, icon consistency, label baselines, spacing, clipping, selected states, empty states, and floating-control occlusion.
3. Run the Diagnostics Runner and the review workflow smoke test.
4. Click the one-button review launcher and confirm that it covers every screen/profile, converts every non-pass result into a focused finding set without duplicates, and enables a self-contained expert-review export only after completion.
5. Verify the agent handoff uses an absolute review-directory path, prepares only a prompt/job, clearly asks the user to send it, requires no server or open port, and leaves source modification blocked. Verify `Скопировать запрос`, `Обновить макет`, and the JSON fallback independently; test native adapters separately.
6. Verify Summary/Problems/Changes isolation, contextual primary-action progression, source/screen filters, bulk selection, named run history, expert-result import, revision/project rejection, and active proposal comparison.
7. Verify compact-width panel mutual exclusion, every right-panel tab, every view/tool combination, panel resizing/collapse, menu dismissal, zoom, tree search, and version approval.
8. Verify Problems state, active-version selection, dedicated Compare version pairing/layout, direct-link state normalization, marker/list number parity, per-version resolution, per-device-side placement, distinct user-comment markers, collision-free layout and anchoring after zoom/scroll/resize, single-popover behavior, and collapse back to a marker.
9. Verify the restored rail commands, File and language icon menus, mutually exclusive menu dismissal, middle-button canvas pan, pointer release/cancel, marker click isolation, RU/EN switching, locale persistence, and that product/user content remains untranslated.
10. Reject the shell if understanding the primary controls depends on permanent help copy.
