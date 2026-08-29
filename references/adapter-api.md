# Fidelity adapter API

Fidelity adapters are deterministic, read-only translators from repository source to UI IR. They do not run the application, a browser dev server, an emulator, or a build.

`SourceContext` contains the repository root, relative source path, text, detected platforms, and scanner role. An adapter exposes a stable `id`, `supports(context)`, and `translate(context) -> AdapterResult`. Results contain screens, nodes, tokens, themes, component mappings, and an explicit unsupported-expression list. Register additional adapters with `register_adapter`; the scanner consumes the registry rather than importing provider-specific agents.

Every reconstructed visual or behavioral property must have a same-path entry in `node.provenance`, for example `style.background` or `layout.padding`. Evidence records have a stable hash ID, source file and line, original expression, adapter ID, and one of `exact`, `high`, `approximate`, or `unsupported`. Unsupported syntax is reported rather than guessed.

The built-in v0.3 adapters are:

- `web`: static HTML plus deterministic simple CSS selectors, CSS custom properties, inline styles, semantic controls, lists, images, and text;
- `react-jsx`, `vue`, `svelte`: source markup projected through the Web contract; dynamic expressions and unmapped project components remain unsupported;
- `react-native`: supported core JSX elements without executing JavaScript; generic projects still require an explicit Android/iOS target family;
- `compose`: `@Composable` screens, common Material/Compose primitives, literal text, basic modifiers, tokens, and Android TV family/focus specialization;
- `android-xml`: Android navigation destinations/actions, Activity/Fragment/Dialog-to-layout evidence (including inherited base layouts), Data Binding wrapper stripping, static `<include>` expansion, common Views/Material controls, string/color/dimension resources, color selectors, qualifier variants, and `values-night` token overrides. Cells/items/partials are component inventory rather than screens. The adapter does not execute bindings, custom views, constraint equations, styles/theme attributes, or runtime-injected content, so these remain explicit unsupported evidence and visual parity stays unverified;
- `swiftui`: `View` bodies, common containers and controls, literal content, basic modifiers, and source tokens for iOS or macOS;
- `apple-interface-xml`: Storyboard/XIB controllers and common UIKit/AppKit views with authored frames; it does not solve Auto Layout;
- `xaml`: WinUI/WPF pages, common controls, resources, and basic layout/style attributes without evaluating bindings or templates;
- `flutter`: common Material widget trees and basic dimensions without executing Dart; the target OS family is not guessed.

Golden source/expected fixtures live under `fixtures/golden`. Changing adapter output requires an intentional fixture update and the fidelity test suite. `uidw fidelity capabilities` returns the same installed matrix in machine-readable JSON.
