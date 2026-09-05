# Changelog

All notable changes are recorded here. The project follows [Semantic Versioning](https://semver.org/) and the structure from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Not every historical version was published as a GitHub Release or package artifact. A version is considered released only after its `vX.Y.Z` tag and release artifacts are published.

## [Unreleased]

## [0.6.8] - 2026-09-05

### Fixed

- Flutter and SwiftUI isolate each widget's arguments from nested children, ignore quoted/commented calls, preserve alpha colors and report bounded expansion or runtime-control-flow gaps. Local SwiftUI views expand with literal arguments; Flutter constructor defaults no longer rewrite string literals.
- Flutter preserves directional insets, text height factors, named image constructors and children constrained by SizedBox. SwiftUI preserves repeated padding and the order of frame, padding and background modifiers on both Apple targets.
- XAML projections preserve LTRB thickness, ARGB colors, grid tracks and cell spans, child stretching, visibility and checked/disabled states without adding generic card padding to Border.
- Web CSS respects selector specificity, declaration order, important declarations and linked stylesheet order. Unlinked stylesheets and unresolved media rules no longer silently change the projection; Vue/Svelte styles and React CSS imports remain connected.
- Added cross-platform source fixtures and regression coverage; native visual evidence remains specific to the platform, fixture and viewport compared.
- Compose screens with callback parameters are translated without merging their declarations into later previews; nested arguments, rectangular sizes, bounded dimensions, and Box alignments retain their source semantics.
- Compose projections resolve literal project spacing, typography, theme colors, and local font families; overlay geometry carries source provenance so diagnostic CLI previews can render.
- Text-dependent previews use browser font measurement and wrapping instead of fixing element geometry from average character-width estimates. Workbench screenshot baselines now reflect browser-measured text layout.
- Local Compose components expand with literal defaults and preview arguments, including bounded imported enum entries; recursive expansion reports a limit instead of running indefinitely.
- Compose Surface padding, passive radio sizing and selection, button content colors, and captured system insets retain their platform semantics in browser projections.
- Headless device captures preserve the requested theme, wait for embedded fonts, exclude workbench panels, and export text geometry for native screenshot comparisons.

## [0.6.7] - 2026-09-02

### Fixed

- Android layout qualifier variants no longer create duplicate screen-tree entries, and translated layouts retain their Android Navigation group hierarchy.
- Unresolved Android resources remain explicit source references instead of invalid UIDW token links; drawable-derived styles and cache-migrated provenance now satisfy the strict evidence contract.

## [0.6.6] - 2026-08-31

### Fixed

- Headless Chromium startup now retries transient Windows locks on `DevToolsActivePort` and allows slower CI runners up to 30 seconds to publish the port.
- This release includes the changes prepared for `v0.6.4` and `v0.6.5`, whose pipelines stopped before package and GitHub Release publication.

## [0.6.5] - 2026-08-31

### Fixed

- Release validation now runs Windows-authored workbench screenshot goldens on a Windows runner while keeping package tests and builds on Linux; PyPI publishing waits for both jobs.
- This release includes the changes prepared for `v0.6.4`, whose pipeline stopped before package and GitHub Release publication.

## [0.6.4] - 2026-08-31

### Added

- A buildless deterministic layout model that computes render-only geometry for parent constraints, padding and gaps, intrinsic text sizes, fill, and weighted growth across screen, theme, scenario, and review-version contexts.
- Internal projection-geometry invariants and regression coverage; geometry validation is not exposed as a user calibration workflow.

### Changed

- HTML previews now consume solver-produced node rectangles when a layout context is fully known and use an explicit CSS fallback for unsupported or dynamic contexts instead of treating browser flow as source geometry.
- Source adapters advertise runtime-free deterministic projection for the supported subset while still requiring native platform evidence before visual or pixel parity can be claimed; Compose preserves `Arrangement.spacedBy(...)` plus numeric `weight` values for the shared solver.

### Fixed

- Flutter projects now use `pubspec.yaml` as the application boundary, excluding documentation prototypes and generated Android/iOS shells from the screen catalog.
- Flutter reconstruction now resolves nested GoRouter paths, Riverpod and Hook widget bases, state-class build methods, recursively referenced project widgets, constructor bindings, ARB localization, common layout/style properties, and navigation actions.
- Route references are no longer counted as missing screen declarations, helper widgets are no longer promoted to screens merely because they share a page file, and unresolved Dart model/style constructors no longer flood fidelity gaps.
- MCP preview builds no longer silently enable draft mode for the cached IR, and compact results expose both the running CLI version and bounded check failures so stale MCP installations are diagnosable.
- Native source adapters and HTML audits now distinguish a deterministic structural projection from native visual verification; native evidence remains explicit-only and is never launched during reconstruction.
- Preview assets now accept only allowlisted base64 image and font data URLs, escape resolved asset attributes, and reject attribute-injection payloads.
- Complete expert-review imports now preserve immutable baseline screens and nodes while merging only new nodes, findings, and proposal versions.
- Partial projection contexts now remain explicit fidelity gaps that require supported geometry instead of being reported as fully deterministic coverage.
- Cache locks now distinguish live and abandoned owners, honor timeouts for stale files, and avoid deleting a replacement owner's lock.
- Scoped context rejects cyclic node hierarchies, scanners ignore file symlinks outside the repository, and bundle extraction validates the complete manifest before writing into an empty destination.
- Release validation now checks both README version markers and runs the four committed workbench golden states before publishing.

## [0.6.3] - 2026-08-29

### Added

- Stable `scopeHash` values and `if-none-match` support for reusing unchanged agent context without returning it again.

### Changed

- Repository release instructions now require pushing an annotated version tag, verifying creation and successful completion of the tag-triggered GitHub Actions run, and checking both PyPI and GitHub Release artifacts before a release may be reported complete.
- Model-facing screen scopes now summarize provenance by property and fetch full source expressions only through explicit fidelity requests.
- CLI fallback routing now starts with bounded `scope` discovery instead of the larger project context.

### Fixed

- Token budgets now return a compact `over-budget` result instead of an oversized payload or a partial node tree.
- Legacy screen context now includes only referenced tokens and relevant theme overrides.
- Default scoped output no longer exposes absolute project or IR paths.

## [0.6.1] - 2026-08-29

### Added

- An official-documentation-first component inventory for Android, iOS, macOS, Windows, Flutter, and Web, covering 178 concepts and 593 framework bindings.
- Calibrated HTML renderer recipes for recognized platform controls, with catalog validation and coverage reported by `uidw fidelity capabilities`.

### Changed

- HTML projection now uses platform catalog geometry only as a fallback; explicit project layout, theme, token, style, and accessibility evidence continues to take precedence.
- Python distributions now include the component catalog, inventory, and their runtime resolver.

### Fixed

- GitHub Release creation now receives the repository identity explicitly in tag-triggered jobs.

## [0.5.0] - 2026-08-29

### Added

- Bounded agent context with `uidw scope`.
- Sparse, guarded review-artifact updates with `uidw patch`.
- Optional local stdio MCP server through `uidw-mcp` and `uidw mcp`.
- Android XML screen/component classification, static include expansion, resources, qualifier variants, and explicit unsupported evidence.
- Android and Apple resource projection for layouts, assets, localization, tokens, and supported source modifiers.
- Read-only native render discovery for Android and Apple through `uidw native status` and `ui_native_status`.
- Clone-free Agent Skill installation with `uidw install-skill`.
- Tag-driven GitHub Actions releases with tests, package builds, PyPI Trusted Publishing, checksums, and GitHub Release assets.

### Changed

- Screen coverage now distinguishes translated screens from explicit exclusions.
- Coverage reports separate source-projection checks from visual-parity evidence.
- Agent guidance now routes through compact CLI or MCP context instead of loading the complete IR.
- README files were rewritten around installation, quick start, safety boundaries, and release channels.
- Wheels now contain the complete Agent Skill payload and runtime fallback resources.
- Native capture state is isolated from baseline IR and invalidated when matching source changes.

## [0.3.4] - 2026-08-28

### Fixed

- Preserved nested logical views and source navigation hierarchy during UI scans.
- Added regression coverage for nested screen groups and cached scans.

## [0.3.3] - 2026-08-28

### Changed

- Simplified the review workflow and runtime diagnostics.
- Added deterministic review-shell golden images and geometry checks.
- Strengthened review-state compatibility and diagnostic replacement rules.

## [0.3.2] - 2026-08-28

### Added

- Fidelity Core with property-level source provenance and explainable evidence.
- Built-in adapters for Web, React, Vue, Svelte, Compose, Android XML, SwiftUI, Apple interface XML, XAML, Flutter, and React Native.
- Golden adapter fixtures and stricter reconstruction gates.

### Changed

- Expanded the CLI, cache, workbench, and validation contracts around deterministic reconstruction.

## [0.2.0] - 2026-08-28

### Added

- Cross-platform project profiles and a stricter review/apply boundary.
- Portable review jobs, state handling, runtime checks, and cache diagnostics.

### Changed

- Hardened the workbench workflow for platform-aware review and multi-step proposals.

## [0.1.0] - 2026-08-27

### Added

- Initial `uidw` CLI for UI indexing, cached context, HTML workbench generation, and review.
- Agent Skill installers for Codex, Claude Code, Cursor, Gemini CLI, Copilot CLI, OpenCode, and generic agents.
- English and Russian documentation.
