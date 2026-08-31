# Native rendering contract

Source analysis and deterministic HTML projection are the default Workbench reconstruction path. They remain buildless and runtime-free. Native-render discovery is optional and read-only during reconstruction, but matching native evidence is required before visual or pixel parity can be claimed. External screenshots, geometry, or semantic trees remain isolated in `native-render-state.json` and never modify the base UI IR.

The default projection resolves source resources and supported layout semantics through the shared deterministic solver. Adapter capability `deterministic-projection` describes source-to-HTML transfer; the workbench reports native targets as `structural-projection` until matching native evidence exists.

## Fidelity levels

1. `discovered`: source entry points, routes, resources, previews, and provider configuration were found.
2. `structural`: a source adapter translated a supported subset into the HTML workbench. This is useful for hierarchy and review workflow, but is not visual proof.
3. `native-preview`: Layoutlib, Xcode, or a configured snapshot-test target produced an image for the exact screen, state, variant, viewport, locale, theme, source fingerprint, and provider version.
4. `device-verified`: an emulator or simulator produced the image and runtime geometry/semantics for the same capture key.

Never promote a result because a provider is merely installed. A capture record with matching source fingerprint and artifacts is required. Any source-fingerprint mismatch makes the capture `stale`.

## Discovery

Use either interface:

```sh
uidw --repo <repo> native status
uidw --repo <repo> native status --platform android
uidw --repo <repo> native status --platform apple
```

MCP clients call `ui_native_status`. Discovery is read-only: it never executes Gradle, Xcode, an emulator, or a simulator, and never edits the target repository.

Android discovery recognizes Gradle modules, Android manifests, Compose `@Preview` entry points, layout XML, the official Compose Screenshot plugin, Paparazzi, Roborazzi, and emulator prerequisites. Apple discovery recognizes Xcode projects/workspaces, SwiftUI `#Preview` and `PreviewProvider`, Storyboard/XIB, snapshot-test markers, and simulator prerequisites.

## Host boundary

Android providers can be orchestrated on a configured Android host. Apple rendering requires a macOS worker with Xcode. Windows and Linux may index SwiftUI, Storyboard, and XIB, but must return `host-required`; HTML reconstruction is not a substitute for Xcode rendering.

## Capture safety

- Native execution is explicit-only. Status, initialization, reconstruction, review, and HTML rendering never start it.
- Do not add screenshot plugins or tests to a user's project automatically. Prefer an existing provider; otherwise produce a setup recommendation.
- Store generated artifacts under the UIDW cache, never beside source unless explicitly requested.
- Artifact references in native state are bundle-relative and cannot escape with absolute paths or `..`.
- Keep baseline IR immutable. Native state may map a capture to a screen/state but must not rewrite source-derived nodes.
