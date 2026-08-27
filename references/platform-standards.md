# Platform standards profile

Last verified: 2026-08-27. Use official sources when a decision depends on newer OS behavior, an experimental component, or a library version. Never upgrade project dependencies merely because newer guidance exists.

The executable profile catalog is [platform-profiles.json](platform-profiles.json). Keep profile IDs, standard-reference prefixes, target sizes, and framework adapters there; prose in this file explains judgment and never overrides a stricter machine gate. Validate every final IR with `scripts/validate_platform_profiles.py` or the combined coverage gate described in [quality-automation.md](quality-automation.md).

## Selection order

1. Explicit product requirements and user-approved brand constraints.
2. The repository's installed UI framework, design system, tokens, and established interaction patterns.
3. The target platform's official components and navigation conventions.
4. Accessibility and adaptive-layout requirements.
5. A custom solution only when the previous layers cannot satisfy the task; record a `design.decisions` entry explaining why.

Reconstruction preserves current behavior and reports standards gaps instead of silently redesigning. Generation and redesign use the platform baseline unless the existing project system intentionally overrides it.

## Android mobile and tablet

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

## Android TV

Default profile ID: `android-tv`.

- Treat TV as a distinct D-pad-first platform, not as a stretched Android phone or tablet. Prefer Compose for TV and TV Material components when they are already compatible with the project; preserve Leanback or existing Views stacks instead of silently migrating dependencies.
- A single, unmistakable focused element is mandatory. Model `default`, `focused`, `pressed`, `selected`, and `disabled` separately; focus must remain visible on every background and must not rely on color alone.
- Every actionable element must be reachable with Up, Down, Left, Right, Select, and Back. Test initial focus, directional order, focus restoration after dialogs/navigation, focus-driven scrolling, repeated D-pad presses, and Back until the app root without loops.
- Design for ten-foot viewing, a 16:9 surface, short readable text, uncluttered hierarchy, and clear spatial grouping. Do not hide essential actions behind hover, touch gestures, long-press, or pointer-only interactions.
- Use a 960×540 mdpi reference canvas for layout reasoning. Keep primary content inside the documented overscan-safe region (normally 48 dp left/right and 27 dp top/bottom); backgrounds may extend edge to edge.
- Keep the Android 48 dp accessibility baseline for custom actionable surfaces, while treating directional reachability and visible focus as the primary TV interaction gate. Large cards and playback controls normally need more space for viewing distance.
- Prefer standard Compose Foundation lazy layouts when the installed Compose version provides TV focus-driven scrolling. Do not mix mobile Material and TV Material themes without an explicit, tested project decision.

Official sources:

- [Android TV focus system](https://developer.android.com/design/ui/tv/guides/styles/focus-system)
- [Android TV layout guidance](https://developer.android.com/design/ui/tv/guides/styles/layouts)
- [Android TV navigation](https://developer.android.com/training/tv/get-started/navigation)
- [Compose for TV](https://developer.android.com/training/tv/playback/compose)
- [Scrollable TV layouts](https://developer.android.com/training/tv/playback/compose/lists)

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

## macOS

Default profile ID: `macos-hig`.

- Prefer native SwiftUI/AppKit windows, split views, sidebars, inspectors, tables, toolbars, menus, sheets, popovers, search fields, system typography, semantic colors, and standard command placement.
- Treat the menu bar and keyboard shortcuts as first-class command surfaces. Important commands remain discoverable in menus even when a toolbar or contextual shortcut also exposes them.
- Support resizable, movable, minimizable, full-screen, multiwindow, active, and inactive window states where the product architecture permits them. Do not freeze a desktop workflow into a phone-sized fixed canvas.
- Design for precise pointer input, keyboard-only workflows, Full Keyboard Access, VoiceOver, drag and drop, contextual menus, and focus rings. Hover may supplement meaning but cannot be the only way to expose a required action.
- Use 28×28 pt as the default control target for generated and redesigned macOS UI. The documented 20×20 pt minimum requires a recorded exception, adequate spacing, low error consequence, and verification with the actual control/input context.
- Preserve platform conventions for destructive commands, default/cancel actions, document state, app/window lifecycle, and active/inactive emphasis. Do not copy iOS tab bars, oversized touch geometry, or mobile-only sheets into a desktop Mac workflow without an explicit reason.
- Respect Reduce Motion, Increase Contrast, Differentiate Without Color, text enlargement, localization expansion, RTL where applicable, and multiple display scales.

Official sources:

- [Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/)
- [Apple accessibility guidance and macOS control sizes](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [Apple focus and selection guidance](https://developer.apple.com/design/human-interface-guidelines/focus-and-selection/)
- [Apple menu guidance](https://developer.apple.com/design/human-interface-guidelines/menus)
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

## Windows

Default profile ID: `windows-fluent`.

- Prefer the UI stack already installed by the repository: normally WinUI 3 with Windows App SDK for a new native app, or the existing WPF/Win32 stack for an established product. Do not migrate frameworks merely to satisfy the profile.
- Use Fluent/Windows control and navigation conventions, system typography, theme resources, standard title-bar/window behavior, dialogs, teaching tips, command bars, menus, and NavigationView patterns when they match the task.
- Support mouse, touch, pen, keyboard, gamepad/remote where relevant, Narrator, UI Automation, access keys, keyboard accelerators, visible focus, high contrast, text scaling, display scaling, and reduced motion.
- Use 40×40 effective pixels as the default touch target for generated and redesigned interactive elements. Pointer-dense UI may use a smaller visible control only when the hit target, spacing, frequency, and error consequence remain safe and the exception is recorded.
- Treat window resizing, snap layouts, multiple displays, DPI changes, compact/expanded layouts, activation/deactivation, and title-bar insets as normal states. Recompute custom title-bar interactive regions after size, scale, or presenter changes.
- Keep command placement and shortcuts consistent with Windows expectations. Do not import macOS traffic-light controls, iOS navigation stacks, or Android FAB/ripple behavior without an intentional cross-platform-system decision.
- Prefer standard WinUI text and controls so Windows text-size and accessibility settings work without custom reimplementation. Validate wrapping, clipping, contrast, and geometry at supported display and text scales.

Official sources:

- [Windows app design guidance](https://learn.microsoft.com/windows/apps/design/)
- [Windows touch target guidance](https://learn.microsoft.com/windows/apps/develop/input/guidelines-for-targeting)
- [Windows keyboard interactions](https://learn.microsoft.com/windows/apps/develop/input/keyboard-interactions)
- [Windows focus navigation](https://learn.microsoft.com/windows/apps/develop/input/focus-navigation)
- [Windows accessibility guidance](https://learn.microsoft.com/windows/apps/design/accessibility/)
- [Windows text scaling](https://learn.microsoft.com/windows/apps/develop/input/text-scaling)
- [Windows title bar guidance](https://learn.microsoft.com/windows/apps/develop/title-bar)

## Cross-platform frameworks

React Native, Flutter, .NET MAUI, Kotlin Multiplatform, and shared web/native products need platform adapters. Share brand tokens, content hierarchy, domain state, and task flow; vary navigation containers, control geometry, gestures, system surfaces, typography behavior, input modality, window behavior, and accessibility semantics by target platform. Android TV must not inherit a touch-only Android rendering, and Windows/macOS desktop targets must not inherit phone navigation merely because business code is shared. A single identical rendering is acceptable only when the repository clearly implements an intentional custom system and the deviation is recorded.

## IR evidence

For generated or redesigned interactive nodes, use:

- `standardRef`: one reference such as `material3.Button`, `androidtv.Card`, `apple.Button`, `macos.Toolbar`, `windows.NavigationView`, `html.button`, or `aria.dialog`;
- `standardRefs`: per-platform references for shared nodes;
- `decisionId`: an ID from `design.decisions` when a custom component is necessary;
- `semantics.role`, `semantics.label`, and `semantics.targetSize`.

Project-system references use `project.ComponentName` and require a valid project standard profile. A custom decision is not permission to ignore accessibility or expected platform behavior.
