# Source-fidelity contract

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
