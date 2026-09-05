# Source-fidelity contract

## Fidelity Core v0.3 with deterministic projection

The scanner uses the provider-neutral adapter registry described in [adapter-api.md](adapter-api.md). Built-in Web, React/Vue/Svelte, Compose, Android XML, SwiftUI, Storyboard/XIB, XAML, Flutter, and React Native adapters translate only deterministic supported subsets and record the rest in `fidelity.unsupported`. A strict artifact declares `fidelity.schemaVersion: "0.3"`.

Each translated property carries stable property-level provenance. Token aliases are resolved for rendering while their original references and source records remain in IR. The baseline is sealed with `review.baselineHash`; proposal versions remain sparse `nodeOverrides`. Editing baseline screens, nodes, tokens, themes, or fixtures without an explicit rescan invalidates the strict gate.

Use `uidw fidelity capabilities` for the installed support matrix, `uidw fidelity report` for the compact gate, and `uidw fidelity explain` for one node or evidence ID. Capabilities distinguish `structuralTier` and `visualTier`; source adapters report `deterministic-projection`, require native evidence for native-platform visual verification, and never start that evidence collection automatically. Per-adapter fixtures prevent silent translation drift.

The HTML projection resolves recognized controls through the official-doc-first [platform component catalog](component-catalog.md). Catalog geometry is a render-only fallback: explicit source layout, theme, token, and style evidence always wins, and the source IR is not mutated.

Compose translation follows unique local composable declarations, literal parameter defaults and constructor preview fixtures. Simple imported enum `entries.forEach` loops and literal resource getters can supply repeated content. Expansion is limited to six nested components and 2,000 calls per translated source; ambiguity, recursion and exhausted budgets remain explicit gaps. Runtime Kotlin, arbitrary collection transformations, slot forwarding, custom drawing and arbitrary theme providers are not evaluated.

Literal project theme values and local font assets are resolved from source. The box model marks automatic text measurement as partial and lets the browser wrap and measure the loaded font, rather than treating average character widths as solved geometry. Browser line boxes and shadows can still differ from native rendering. A partial context does not establish native visual parity.

For a user-requested native comparison, use the same authored preview state, locale, font scale and logical viewport. Capture metadata can provide `viewport.safeAreaInsets` in logical pixels for Compose system-bar padding. `smoke_preview.js --capture-device --capture-screen ID --capture-theme light --screenshot screen.png --geometry-output geometry.json` captures the device content after fonts load, excluding workbench chrome. Keep the native screenshot, device density, source revision and comparison results with the diagnostic artifact; system-bar icons themselves are outside the source projection.

Flutter and SwiftUI use the same balanced source delimiter and literal masking utilities as Compose. Visual parameters are scoped to the current call, excluding child widgets and event handlers. SwiftUI expands unique local View declarations with literal member arguments and represents order-dependent frame/padding/background operations as separate source-backed nodes. Flutter resolves literal constructor defaults, distinguishes TextStyle height factors from widget heights, and propagates SizedBox tight constraints to its child. Expansion is capped at six component levels and 2,000 widget calls. Arbitrary control flow, unavailable SF Symbols and recursive expansion remain gaps.

XAML translates four-value Thickness in left/top/right/bottom order, alpha-first colors, explicit grid tracks/cell spans and literal states. WPF Border and TextBlock defaults are distinct from generic card recipes. Resource bindings, control templates, nonliteral grid tracks and more complex platform layout behavior still require separate handling. Web handles the supported simple selectors in CSS cascade order, including importance and linked stylesheet order; unsupported at-rules are reported rather than applied unconditionally.

The source fixtures in `fixtures/golden/platform-fidelity` exercise these shared failure patterns. A Flutter engine golden, a WPF RenderTargetBitmap and an original Web page can provide independent runtime evidence for their respective fixture. WPF evidence does not verify WinUI, and Flutter test-engine evidence does not verify every device configuration. SwiftUI iOS/macOS fixture assertions are source-only unless matching Apple runtime captures are supplied. Successful source tests or a small native comparison must never promote unrelated screens or platforms to verified visual parity.

Use this contract before creating reviewable IR. The goal is not a visually pleasant approximation; it is a traceable projection of the authored UI.

## Evidence bundle per screen

Collect these inputs before translation:

1. Every discovered screen entry point, route, hash-linked section, independently selectable panel/tab, and its target viewport or breakpoint.
2. Recursively referenced local components, including their default props and selected variant.
3. Theme, color, spacing, radius, elevation, and typography definitions actually reached by that screen.
4. Local fonts, icons, images, vector drawables, and content fixtures or preview/sample data.
5. Navigation and visible interaction states represented by source.

If a required runtime value has no source fixture, mark it unresolved. Ask for a representative value only when it materially changes layout; do not invent product content.

## Translation rules

- Preserve the component hierarchy and record the original component on each node, even when HTML uses a neutral `div`, `button`, or `input` for interaction semantics.
- Trace design-system wrappers to the primitives and tokens that determine their appearance. A name such as `PrimaryButton` is not sufficient evidence for color, height, padding, radius, or font.
- Resolve token aliases to their active theme values while retaining the original token reference in provenance or metadata.
- Translate every independent edge inset, constraint, flex weight, alignment, minimum/maximum size, line height, letter spacing, border, shadow, clipping rule, object fit, and z-order that affects the chosen viewport.
- Embed project assets and fonts. Never replace a missing icon with Unicode or a generic icon in a reviewable preview.
- Do not apply platform folklore such as assumed Material, Cupertino, or browser dimensions unless the project explicitly uses that unmodified platform component. Mark implicit system metrics `approximate`.
- Represent scroll containers, overlays, safe areas, disabled/selected states, and navigation declared by source. Use fixed fixture rows for runtime lists.

## Fidelity gate

Before presenting the HTML:

- Remove every `UntranslatedSource` and inventory placeholder.
- Ensure at least 80% of meaningful nodes map to a source file and at least 90% of visual nodes have explicit source-derived appearance and geometry; aim for 100% for visible leaf nodes.
- For intentionally inherited leaf styling set `inheritsAppearance: true`, or `inheritsTypography: true` when only typography is inherited. Do not use these flags to bypass missing component analysis.
- Use `exact` only for literal source values, embedded assets/fonts, or verified component mappings.
- Use `high` for complete declarative translations.
- List unresolved tokens, runtime values, custom drawing, and implicit system metrics.
- Render one representative screen first. Expand to the rest only after the user confirms that its visual language matches the project.

Preserve `discoveredScreens` and `discoveredRoutes` from the starter IR. Every candidate must be translated or listed in `fidelity.excludedScreens` / `fidelity.excludedRoutes` as an object with a stable key and a non-empty reason. Do not silently discard duplicate-looking screens; they may represent distinct states or routes.

Preserve `discoveredNavigationTargets`. Each target must map to a screen's `fragment` and be reachable through a `navigate` action. Exclusions belong in `fidelity.excludedNavigationTargets` as `{"target":"#legacy","reason":"unreachable legacy panel"}`.

The renderer enforces the minimum gate. `--allow-draft` is diagnostic and must not be used to solicit design approval.

For Android, Apple, Windows, and Flutter, the HTML workbench uses the same runtime-free layout model as every other source adapter. A partial context remains an explicit projection gap; it must not trigger a build, emulator, simulator, or native-capture calibration step.
