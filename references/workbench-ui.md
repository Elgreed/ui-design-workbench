# Production workbench UI

Use this reference when generating the review workbench shell itself. It governs the editor chrome around reconstructed screens; it must never leak into the product UI being reviewed.

## Canvas-first information architecture

Give each persistent region one job:

- a narrow left rail switches workbench areas and remains available when panels collapse;
- the left panel contains project/screen navigation, hierarchy, search, and low-priority coverage metadata;
- one compact document bar contains product identity, application menus, current screen path, active version, and current mode status;
- the canvas owns screen previews and comparisons;
- a floating canvas palette switches view and interaction tools;
- one compact canvas strip independently toggles `Problems`, then uses one stable `Before / Compare / After` segmented group for version visibility; comparison-layout controls keep their space and become enabled only in Compare so the strip never jumps;
- a small bottom-right cluster owns zoom only;
- the right panel is contextual and tabbed into `Properties`, `Review`, and `Comments` rather than stacking all three workflows.

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
- Put one compact `Запустить ревью` launcher at the top of the Review tab. It is the primary entry point for reviewing already assembled mockups; local diagnostic implementation details stay below it.
- After the run, show the issue count and a secondary `Подготовить AI-ревью` handoff. It copies or downloads a provider-neutral job; an optional adapter may open a prepared native agent task, but it never submits the prompt. Keep a compact JSON-download action as the portable fallback, not a competing primary path.
- Keep finding observation and actions visible; place impact, recommendation, and evidence in an expandable detail region.
- Use the same stable number for each finding in the Problems list and on the canvas. Canvas markers remain circles until clicked, open one compact anchored card at a time, and expose an unambiguous top-right collapse control that restores the circle.
- Use short empty states that name the next direct action. Do not add tutorial paragraphs to compensate for ambiguous controls.
- Split the Review tab into `Сводка`, `Проблемы`, and `Изменения`. Summary owns scope, coverage, history, and diagnostics; Problems owns audit evidence and selection; Changes owns the correction queue, imported proposals, and design approval. Do not vertically stack all three workflows.
- Keep one sticky contextual primary action whose label advances with the state: run review, choose problems, create proposal, approve proposal, or prepare implementation. Secondary export/reject controls may remain adjacent but must not compete visually.

## Controls and visual system

- Use one coherent inline SVG icon family with equal view boxes, stroke behavior, optical size, and alignment. Do not use mixed Unicode glyphs as workbench icons.
- Keep icon-only controls for conventional actions such as panel collapse, zoom, and export. Give every icon-only control an accessible name and concise tooltip.
- Retain visible labels for modes whose meaning is not safely conveyed by an icon alone. Labels may collapse at narrow widths.
- Use restrained neutral surfaces, one primary accent, semantic success/warning/error colors, subtle borders, and elevation only for floating or transient surfaces.
- Base dense desktop controls on a 28–32 px visual box while preserving at least a 24×24 CSS px WCAG target and larger targets where space permits.
- Use stable typography roles: 13 px panel/page title, 10–11 px primary control/body text, 8–9 px metadata. Never shrink essential task text merely to fit a panel.
- Equivalent segmented controls must share height, padding, baseline, icon box, and selected-state geometry.
- Localize workbench chrome at runtime with native-language choices (`Русский`, `English`) and persist the locale in local storage plus `?lang=`. Never translate the reconstructed product, screen names, findings, comments, or evidence.

## Adaptive behavior

- Wide layout: left navigation and contextual right panel may coexist.
- Compact desktop/tablet layout: panels become overlays. Opening one closes the other so the canvas retains a useful working width.
- Narrow layout: rail remains; panel labels and nonessential document-bar items collapse before controls disappear.
- Panel width, active tab, selected node, review filter, scroll, and collapse state persist by review revision.
- A panel opened from a finding, comment, inspection tool, diagnostic, or application menu must select the relevant tab automatically.

## Interaction contract

- `All screens`, `Prototype`, `Single screen`, and `Compare` are view modes and stay in one group.
- `Interact`, `Inspect`, and `Comment` are canvas tools and stay in a separate group.
- Prototype is the only mode in which declared navigation changes screens.
- Selecting a node synchronizes canvas highlight, layer/screen context, and the Properties or Comments panel without losing canvas scroll.
- Menus and popovers are mutually exclusive and close on action, outside click, `Escape`, or view change.
- The current screen and hovered navigation destination use distinct colors.
- Design approval and source implementation are separate phases with separate actions.
- Compare mode allows any two retained review versions, not only baseline versus latest, while preserving the immutable baseline.
- `Before / Compare / After` is a three-state segmented visibility control: Before and After show one version without changing the surrounding tool geometry; Compare shows both and enables Split/Overlay. The active proposal is chosen in the Changes workflow; the canvas strip controls visibility only.
- `Problems` is a visibility layer, not a separate review mode. Its marker set follows the current severity/source/screen/focused-block filters and never invents an anchor for a finding whose screen cannot be located.
- Clicking a finding marker opens its description on the canvas without navigating away. Opening a second marker closes the first; hiding Problems, changing screen/version, or collapsing the card leaves list state and numbering synchronized.
- Finding markers use the scrollable canvas as their containing block, resolve collisions independently for each rendered device, and are remeasured after zoom, canvas/device scroll, resize, version change, and panel layout change. A marker's relative offset from its anchor must remain stable.
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
8. Verify Problems state plus the Before/Compare/After group, stable strip geometry, direct-link state normalization, marker/list number parity, collision-free marker layout and anchoring after zoom/scroll/resize, single-popover behavior, and collapse back to a marker.
9. Verify middle-button canvas pan, pointer release/cancel, marker click isolation, RU/EN switching, locale persistence, and that product/user content remains untranslated.
10. Reject the shell if understanding the primary controls depends on permanent help copy.
