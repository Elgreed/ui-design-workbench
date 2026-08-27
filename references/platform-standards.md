# Platform standards profile

Last verified: 2026-08-24. Use official sources when a decision depends on newer OS behavior, an experimental component, or a library version. Never upgrade project dependencies merely because newer guidance exists.

The executable profile catalog is [platform-profiles.json](platform-profiles.json). Keep profile IDs, standard-reference prefixes, target sizes, and framework adapters there; prose in this file explains judgment and never overrides a stricter machine gate. Validate every final IR with `scripts/validate_platform_profiles.py` or the combined coverage gate described in [quality-automation.md](quality-automation.md).

## Selection order

1. Explicit product requirements and user-approved brand constraints.
2. The repository's installed UI framework, design system, tokens, and established interaction patterns.
3. The target platform's official components and navigation conventions.
4. Accessibility and adaptive-layout requirements.
5. A custom solution only when the previous layers cannot satisfy the task; record a `design.decisions` entry explaining why.

Reconstruction preserves current behavior and reports standards gaps instead of silently redesigning. Generation and redesign use the platform baseline unless the existing project system intentionally overrides it.

## Android

Default profile ID: `material3`.

- For new Android UI, default to Material 3 components and theming. In Compose, derive color, typography, and shape from `MaterialTheme`; in Views, stay with the project's installed Material Components stack rather than introducing Compose without permission.
- Prefer the installed stable APIs. Use Material 3 Expressive or experimental APIs only when already enabled or explicitly approved.
- Map top-level and hierarchical navigation to Material/Android patterns already used by the project. Do not import iOS tab, sheet, or toolbar behavior merely for visual novelty.
- Use adaptive layouts based on window size, not a hard-coded phone model. Consider navigation bar/rail and list-detail/supporting-pane patterns where the information architecture warrants them.
- Interactive touch targets should be at least 48×48 dp, even if the visible icon is smaller.
- Support font scaling, screen readers, keyboard, mouse, stylus, RTL, dark theme, system insets, loading/error/empty states, and back behavior.

Official sources:

- [Material Design 3 in Compose](https://developer.android.com/develop/ui/compose/designsystems/material3)
- [Adaptive Android guidance](https://developer.android.com/develop/adaptive-apps/guides/adaptive-dos-and-donts)
- [Android accessibility and 48 dp targets](https://developer.android.com/design/ui/mobile/guides/foundations/accessibility)

## iOS and iPadOS

Default profile ID: `apple-hig`.

- Prefer native SwiftUI/UIKit controls, navigation, sheets, alerts, menus, pickers, toolbars, tab bars, system typography, semantic colors, materials, and standard gestures.
- A tab bar navigates between top-level areas; actions belong in a toolbar or content. Preserve navigation state within tabs.
- Respect safe areas, system margins, Dynamic Type, localization expansion, RTL, orientation, multitasking, resizable iPad windows, and input methods beyond touch.
- Use a 44×44 pt default control target for iOS/iPadOS. Do not shrink to the documented minimum merely to make a dense layout fit.
- Do not simulate Material ripples, FABs, Android back behavior, or Android component geometry unless the product explicitly chooses a cross-platform custom system.
- Use current system materials, including newer visual treatments, only when the deployment target and existing implementation support them. Do not draw a speculative imitation in HTML.

Official sources:

- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines)
- [Apple layout and safe-area guidance](https://developer.apple.com/design/human-interface-guidelines/layout)
- [Apple accessibility guidance and control sizes](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [Apple tab bar guidance](https://developer.apple.com/design/human-interface-guidelines/tab-bars)
- [Apple toolbar guidance](https://developer.apple.com/design/human-interface-guidelines/toolbars)

## Web

Default profile ID: `web-platform`.

- Start with semantic HTML and native elements. Use ARIA only when native semantics cannot express the required widget.
- Target WCAG 2.2 AA unless the repository or user requires a stronger level. Preserve visible focus, logical tab order, keyboard operation, names/roles/values, contrast, zoom/reflow, error identification, and reduced motion.
- Custom widgets follow the corresponding WAI-ARIA Authoring Practices pattern, including its keyboard model and focus management. APG is informative guidance, while WCAG and ARIA are normative standards.
- Pointer targets must meet WCAG 2.2 AA target sizing or a documented exception. The baseline audit uses 24×24 CSS px; prefer larger targets for primary touch interfaces when product density permits.
- Use responsive content-driven breakpoints and appropriate maximum content widths. Do not imitate an Android or iOS screen when the target is a desktop web application.
- Preserve browser expectations for links, forms, history, selection, copy/paste, autofill, and keyboard shortcuts.

Official sources:

- [WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/)
- [WCAG 2.2 target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [APG keyboard-interface guidance](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)

## Cross-platform frameworks

React Native, Flutter, Kotlin Multiplatform, and shared web/native products need platform adapters. Share brand tokens, content hierarchy, domain state, and task flow; vary navigation containers, control geometry, gestures, system surfaces, typography behavior, and accessibility semantics by target platform. A single identical rendering is acceptable only when the repository clearly implements an intentional custom system and the deviation is recorded.

## IR evidence

For generated or redesigned interactive nodes, use:

- `standardRef`: one reference such as `material3.Button`, `apple.Button`, `html.button`, or `aria.dialog`;
- `standardRefs`: per-platform references for shared nodes;
- `decisionId`: an ID from `design.decisions` when a custom component is necessary;
- `semantics.role`, `semantics.label`, and `semantics.targetSize`.

Project-system references use `project.ComponentName` and require a valid project standard profile. A custom decision is not permission to ignore accessibility or expected platform behavior.
