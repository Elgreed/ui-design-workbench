# Fidelity adapter API

Fidelity adapters are deterministic, read-only translators from repository source to UI IR. They do not run the application, a browser dev server, an emulator, or a build.

`SourceContext` contains the repository root, relative source path, text, detected platforms, and scanner role. An adapter exposes a stable `id`, `supports(context)`, and `translate(context) -> AdapterResult`. Results contain screens, nodes, tokens, themes, component mappings, and an explicit unsupported-expression list. Register additional adapters with `register_adapter`; the scanner consumes the registry rather than importing provider-specific agents.

Every reconstructed visual or behavioral property must have a same-path entry in `node.provenance`, for example `style.background` or `layout.padding`. Evidence records have a stable hash ID, source file and line, original expression, adapter ID, and one of `exact`, `high`, `approximate`, or `unsupported`. Unsupported syntax is reported rather than guessed.

The built-in adapters are:

- `web`: static HTML plus deterministic simple CSS selectors, CSS custom properties, inline styles, semantic controls, lists, images, and text;
- `react-jsx`, `vue`, `svelte`: source markup projected through the Web contract; dynamic expressions and unmapped project components remain unsupported;
- `compose`: Android `@Composable` screens, common Material/Compose primitives, resources, modifiers, and tokens;
- `android-xml`: Android layout/resources XML, common Views/Material controls, dimensions/colors, and `values-night` token overrides;
- `swiftui`: iOS/macOS `View` bodies, common containers and controls, Asset Catalog resources, localization, SF Symbol fallbacks, modifiers, and source tokens;
- `apple-interface-xml`: Storyboard/XIB controllers and common UIKit/AppKit views with assets, authored frames, and a conservative Auto Layout subset;
- `xaml`: WinUI/WPF pages, common controls, resources, and basic layout/style attributes without evaluating bindings or templates;
- `flutter`: common Material/Cupertino widget trees and basic dimensions without executing Dart.

Golden source/expected fixtures live under `fixtures/golden`. Changing adapter output requires an intentional fixture update and the fidelity test suite. `uidw fidelity capabilities` returns the same installed matrix in machine-readable JSON.
