# Platform discovery rules

Read only the section matching platforms reported by `scan_ui.py`.

## Web and React

Prioritize route declarations, page/layout files, exported PascalCase components, JSX/TSX, CSS modules, global styles, theme providers, design-token JSON, and public assets. Preserve imported project components instead of flattening them into generic HTML controls. Extract visible strings, prop defaults, variants, and navigation calls. Distinguish React Native through `react-native` imports and `StyleSheet.create`.

## Android Compose

Prioritize `@Composable` functions, `NavHost`/`composable` routes, `MaterialTheme`, `Modifier` chains, preview fixtures, `Row`, `Column`, `Box`, lazy containers, text, images, icons, and project design-system components. Read `res/values`, vector drawables, fonts, and raster resources. Treat custom `Canvas`, subcomposition, and runtime measurement as unsupported until mapped.

## Android Views

Prioritize `res/layout`, navigation XML, styles/themes, drawables, Activities, Fragments, adapters, and view binding. Translate XML constraints into IR layout relationships; do not render Android widgets with browser defaults. Record custom Views as project-specific components.

## SwiftUI and UIKit

For SwiftUI, prioritize types conforming to `View`, `body`, stacks, grids, modifiers, `NavigationStack`, `NavigationLink`, previews, assets, and environment-driven themes. For UIKit, prioritize Storyboard/XIB, view controllers, Auto Layout constraints, appearance configuration, and asset catalogs. Mark custom drawing and implicit system metrics approximate unless a renderer mapping exists.

## Flutter

Prioritize `Widget` subclasses, `build`, `MaterialApp`/`CupertinoApp`, `ThemeData`, `Navigator`/`GoRouter`, rows, columns, stacks, flex, lists, assets, and `pubspec.yaml`. Use explicit fixture values for builders. Mark custom painters and runtime layout delegates unsupported until mapped.

## Shared rules

- Search navigation and theme definitions before individual leaf components.
- Reuse literal strings and local assets; do not invent product copy.
- Trace design-system wrappers to their defaults before choosing a renderer variant.
- Keep alternate themes and responsive variants as explicit preview states.
- If a platform uses generated code, prefer authored source and configuration over generated output.
