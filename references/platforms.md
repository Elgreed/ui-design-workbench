# Platform discovery rules

Read only the section matching platforms reported by `scan_ui.py`.

## Web and React

Prioritize route declarations, page/layout files, exported PascalCase components, JSX/TSX, CSS modules, global styles, theme providers, design-token JSON, and public assets. Preserve imported project components instead of flattening them into generic HTML controls. Extract visible strings, prop defaults, variants, and navigation calls. Distinguish React Native through `react-native` imports and `StyleSheet.create`.

## Android Compose

Prioritize `@Composable` functions, `NavHost`/`composable` routes, `MaterialTheme`, `Modifier` chains, preview fixtures, `Row`, `Column`, `Box`, lazy containers, text, images, icons, and project design-system components. Read `res/values`, vector drawables, fonts, and raster resources. Treat custom `Canvas`, subcomposition, and runtime measurement as unsupported until mapped.

## Android TV

Detect TV modules from `android.software.leanback`, `LEANBACK_LAUNCHER`, `androidx.tv.*`, Compose for TV/TV Material dependencies, Leanback fragments, and TV-specific source sets. Prioritize D-pad focus graphs, `FocusRequester`/`focusRestorer`, focus groups, initial focus, selected/focused states, standard Compose Foundation lazy layouts, playback controls, Back behavior, and overscan-safe layout constants. Treat mobile Compose/Material controls inside a TV module as suspect until their focus and remote behavior are mapped. Preserve an existing Leanback or Views implementation; do not silently migrate it to Compose for TV.

## Android Views

Prioritize `res/layout`, navigation XML, styles/themes, drawables, Activities, Fragments, adapters, and view binding. Translate XML constraints into IR layout relationships; do not render Android widgets with browser defaults. Record custom Views as project-specific components.

## SwiftUI and UIKit

For SwiftUI, prioritize types conforming to `View`, `body`, stacks, grids, modifiers, `NavigationStack`, `NavigationLink`, previews, assets, and environment-driven themes. For UIKit, prioritize Storyboard/XIB, view controllers, Auto Layout constraints, appearance configuration, and asset catalogs. Mark custom drawing and implicit system metrics approximate unless a renderer mapping exists.

## macOS SwiftUI and AppKit

Detect macOS targets from `Package.swift` platform declarations, Xcode target metadata, `import AppKit`, `#if os(macOS)`, `NSApplication`, `NSWindow`, `NSViewController`, `WindowGroup`, `Settings`, `Commands`, and `MenuBarExtra`. For SwiftUI, prioritize scenes, windows, commands, split views, tables, toolbars, inspectors, focus, and environment-driven active/inactive states. For AppKit, prioritize NSWindow/NSWindowController, NSViewController, NSToolbar, NSMenu, NSSplitView, NSTableView, Auto Layout, bindings, and asset catalogs. Do not classify a macOS Storyboard/XIB as UIKit or reuse iOS navigation assumptions.

## Windows

Detect WinUI 3 and Windows App SDK through `.csproj`, `Microsoft.WindowsAppSDK`, `Microsoft.UI.Xaml`, `AppWindow`, XAML pages/windows, NavigationView, CommandBar, and resource dictionaries. Detect WPF through `UseWPF`, `System.Windows`, Window/Page/UserControl XAML, routed commands, styles, templates, and VisualStateManager. Read theme dictionaries, control templates, title-bar integration, window-size handlers, keyboard accelerators/access keys, UI Automation properties, high-contrast resources, and scale-aware assets. Keep WinUI, WPF, Win32, and hybrid web content distinct; do not translate XAML controls as browser-default HTML.

## Flutter

Prioritize `Widget` subclasses, `build`, `MaterialApp`/`CupertinoApp`, `ThemeData`, `Navigator`/`GoRouter`, rows, columns, stacks, flex, lists, assets, and `pubspec.yaml`. Use explicit fixture values for builders. Mark custom painters and runtime layout delegates unsupported until mapped.

## Shared rules

- Search navigation and theme definitions before individual leaf components.
- Reuse literal strings and local assets; do not invent product copy.
- Trace design-system wrappers to their defaults before choosing a renderer variant.
- Keep alternate themes and responsive variants as explicit preview states.
- For desktop targets, inventory window sizes, activation, menus, commands, keyboard shortcuts, pointer/keyboard focus, and multiwindow behavior as first-class states.
- For TV targets, inventory D-pad reachability, initial/restored focus, directional order, remote Select/Back, focus-driven scrolling, and 16:9 safe content as first-class behavior.
- If a platform uses generated code, prefer authored source and configuration over generated output.
