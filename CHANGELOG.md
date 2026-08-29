# Changelog

All notable changes are recorded here. The project follows [Semantic Versioning](https://semver.org/) and the structure from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Not every historical version was published as a GitHub Release or package artifact. A version is considered released only after its `vX.Y.Z` tag and release artifacts are published.

## [Unreleased]

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
