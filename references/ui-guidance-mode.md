# Optional UI guidance mode

Use this lightweight path only when `ui-context.json` reports `uiMode.enabled: true` and the user requests an ordinary UI-related source change. It prevents platform-inappropriate improvisation without turning every UI task into a design audit.

## Task contract

1. Keep the user's requested behavior and scope authoritative. Do not add a redesign, new dependency, mockup, review bundle, or unrelated cleanup.
2. Resolve the target platform and existing UI stack from cached context and the directly affected source. Read only that platform section of [platform-standards.md](platform-standards.md) and any discovered project UI policy.
3. Prefer existing project components, tokens, assets, typography, spacing, navigation, and state patterns. Platform guidance fills gaps; it does not erase an intentional project design system.
4. Check the affected control or screen for relevant states, adaptive behavior, input method, focus/semantics, accessibility, localization pressure, and platform navigation/action placement. Ignore categories the change cannot affect.
5. Implement in the real source only when the user's request authorizes implementation. Run the smallest relevant repository validation and report any deliberate standards exception or unresolved evidence.

## Platform routing

- Android: existing Compose/Views stack, Material guidance compatible with that stack, system back/navigation, touch targets, state and accessibility semantics.
- iOS: existing SwiftUI/UIKit stack, Apple navigation and presentation patterns, Dynamic Type, safe areas, and semantic controls.
- macOS: existing SwiftUI/AppKit stack, window/menu/toolbar conventions, keyboard commands, compact pointer geometry, and active/inactive state.
- Windows: existing WinUI/WPF/other installed stack, Fluent-compatible command placement, keyboard/focus/high-contrast behavior, resizable-window layout, and pointer/touch differences.
- Flutter: existing Material/Cupertino/adaptive stack, platform-aware navigation and semantics, scalable text, safe areas, and responsive layout.
- Web: existing framework and design system, semantic HTML, WCAG 2.2 AA, keyboard/focus behavior, responsive layout, and established component primitives.

The mode is advisory and scoped. It does not claim that the whole product was reviewed or made compliant.
