# Platform component inventory and renderer catalog

The component model has two deliberately separate layers:

- `component-inventory.json` is the complete public visual-component inventory recognized by the source adapters. It groups framework/API names into official concepts for Android, iOS, macOS, Windows, Flutter, and Web.
- `component-catalog.json` contains calibrated HTML renderer recipes. Several official components can share one recipe without being treated as the same source component.

The current inventory contains 178 official concept groups and 593 concrete framework bindings. The renderer has 66 conservative recipes. These counts are different on purpose: copying hundreds of near-identical CSS recipes would make calibration inconsistent and would not improve fidelity.

The authority order is deliberate:

1. official platform documentation defines component identity, semantics, and expected behavior;
2. built-in renderer calibration supplies conservative HTML geometry when source code has no explicit value;
3. project-authored layout, theme, token, style, and accessibility values always override the fallback.

Every family links to its official documentation in JSON. `uidw fidelity capabilities` reports recipe, concept, and binding coverage separately and fails when bindings conflict, an inventory concept references a missing recipe, a family has no source, or a renderer kind is invalid.

“Complete” means the public visual primitives and controls in the linked official component/widget/control catalogs. It intentionally excludes nonvisual controllers, delegates, routes, painters, internal implementation classes, deprecated platform-specific products, and runtime-generated project components. Project wrappers are discovered separately and mapped back to this inventory with source provenance.

The fallback is not a native screenshot and must not be described as pixel-perfect. Official documentation does not encode every runtime measurement, font rasterization detail, OS-version variation, or project theme override. Native captures remain the visual authority where exact evidence is required.

Large-project analysis is secondary. It may discover project wrappers such as `PrimaryButton`, theme indirection, and frequently combined primitives, but it must not redefine official controls or copy proprietary UI code into the global catalog. Project-specific mappings belong to the project cache and must retain source provenance.
