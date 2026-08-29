# Project context and cache protocol

The cache accelerates discovery; it is never authoritative application data and never replaces source evidence.

## Storage model

The default is a user-level, project-keyed operating-system cache:

- Windows: `%LOCALAPPDATA%\UI Design Workbench\Cache\projects\<project-key>`
- macOS: `~/Library/Caches/ui-design-workbench/projects/<project-key>`
- Linux: `$XDG_CACHE_HOME/ui-design-workbench/projects/<project-key>` or `~/.cache/ui-design-workbench/projects/<project-key>`

Set `UIDW_CACHE_HOME` for an isolated runner. The per-project `config.json` lives in this user cache by default. `init --project-cache` is an explicit opt-in that instead creates `.ui-design-workbench/config.json` and an ignore-all `.gitignore` inside the repository. Commit only a deliberately shared config or exported semantic UI map; never commit fingerprints, per-file records, timestamps, diagnostics, screenshots, or agent-local paths.

The project key is derived from the normalized absolute repository path. The installed skill contains only reusable code and reference data; it must not contain project caches.

## State files

- `cache-state.json`: scanner/config versions, candidate manifest, content fingerprints, and reusable per-file analysis.
- `ui-scan.json`: aggregated UI inventory from current per-file records.
- `ui-ir.json`: synchronized projection combining the generated source index with preserved authored detail; still not a finished review deliverable.
- `design-model.json`: durable authored screen/node/scenario detail preserved across source-index refreshes.
- `review-state.json`: findings, annotations, decisions, and proposal metadata preserved separately from discovery.
- `ui-context.json`: bounded model-facing summary with changed files and priority reads.
- `ui-context-<screen>.json`: one screen subtree and its directly referenced sources.
- `sync-report.json`: last invalidation reason, changed files, and affected screen IDs.
- `config.json`: cache preferences, the opt-in `uiMode.enabled` flag, and derived `mockData.mode`. Mock data is always enabled and follows detail level: `minimal`, `representative`, or `exhaustive`; it is not a separate preference.

## Commands

```text
uidw --repo <repo> init
uidw --repo <repo> status --json
uidw --repo <repo> sync
uidw --repo <repo> context --screen <screen-id> --json
uidw --repo <repo> context --screen <screen-id> --budget 4000 --format markdown
uidw --repo <repo> scope --budget 4000
uidw --repo <repo> scope --screen <screen-id> --budget 4000
uidw --repo <repo> map --output <docs-or-artifact-dir>/ui-graph.json
uidw --repo <repo> diff
uidw --repo <repo> workbench --output-dir <artifact-dir>
uidw --repo <repo> check --ir <artifact-dir>/ui-ir.json --level full
uidw --repo <repo> doctor --json
uidw --repo <repo> ui-mode --enable
```

`init`, `sync`, `context`, `map`, and cache-backed workbench/review entry points share one internal `ensure_initialized` bootstrap. The first ordinary `context` or `review` request creates the default user-cache configuration, UI index, graph, and starter IR automatically; manual `init` is not required. Each result exposes `initialization.status` as `created`, `updated`, `reused`, or `stale`. Later calls reuse the existing cache and do not analyze unchanged source files. Use `sync --force` after scanner/schema upgrades or known discovery errors. Use `--verify-content` when timestamps may be unreliable, such as restored archives or unusual network filesystems.

## Invalidation

Candidate files use size, nanosecond mtime, and SHA-256. Unchanged metadata reuses the existing digest; changed metadata is rehashed. The manifest watches broad source candidates so that newly added UI files can be discovered, but `changedUiFiles` contains only records classified as UI or paths already referenced by the UI inventory. Non-UI source changes refresh manifest metadata without invalidating the UI cache. Only added or content-modified UI files are analyzed again. Removed UI files drop their cached record. A theme or navigation change invalidates all screens; a screen/component change invalidates mapped dependents; scanner/config/cache-version changes force full reconstruction.

Metadata-only changes update the manifest without rescanning. `--verify-content` rehashes every candidate when correctness is more important than I/O cost.

Every JSON write uses a same-directory temporary file plus atomic replacement. A short-lived project state lock serializes concurrent writers. Configuration schema upgrades keep `config.v<old>.backup.json`; disposable scanner/cache versions rebuild automatically. Source changes never discard authored scenarios, proposals, findings, or annotations: bindings for impacted screens and nodes are retained with `sourceState: stale` until an agent reconciles them.

Do not run a watcher, bridge server, emulator, or target application. Lazy command-boundary synchronization is deterministic, portable, and inexpensive for agent workflows.

Interactive `init` asks only for detail level and does not recommend or preselect a value. Automatic non-interactive initialization writes only the neutral technical config and never guesses a detail level: compact context reports `configuration.setupRequired` and one concise `questionsForUser` item until the user answers it. Use `config setup`, `config show`, or `config set detail <low|medium|high>` without rescanning unchanged UI files. `help config` describes the levels and `about` explains the tool boundary.

UI guidance is not asked during setup and remains off unless explicitly enabled. `init --ui-mode` and `init --no-ui-mode` make automation deterministic. Later use `ui-mode --enable`, `ui-mode --disable`, or `config set ui-mode on|off`. Enabling guidance changes agent behavior only for UI-related tasks and does not imply review, redesign, preview generation, or source-edit permission.

Mock data follows detail level automatically: `low` uses `minimal`, `medium` uses `representative`, and `high` uses `exhaustive`. This derived change refreshes model context but never causes another repository source scan by itself. Preserve existing `scenarioFixtures` and `screen.scenarios` for unaffected screen IDs during incremental sync; regenerate only fixtures whose source dependencies changed.

Use `scope` rather than JSON `context --screen` for agent prompts. It includes only referenced tokens and theme overrides, summarizes property provenance, enforces the requested budget without returning a partial tree, and supports `scopeHash` reuse. The older `context` command remains a human-readable cache summary and compatibility surface.
