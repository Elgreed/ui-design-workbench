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
- `ui-ir.json`: starter semantic map used as cached discovery context, not a finished review deliverable.
- `ui-context.json`: bounded model-facing summary with changed files and priority reads.
- `ui-context-<screen>.json`: one screen subtree and its directly referenced sources.
- `sync-report.json`: last invalidation reason, changed files, and affected screen IDs.
- `config.json`: cache preferences, the opt-in `uiMode.enabled` flag, and `mockData.mode` (`none`, `representative`, or `exhaustive`). UI-mode and mock-data changes refresh model context but are excluded from the source-scan fingerprint.

## Commands

```text
uidw --repo <repo> init
uidw --repo <repo> status --json
uidw --repo <repo> sync
uidw --repo <repo> context --screen <screen-id> --json
uidw --repo <repo> map --output <docs-or-artifact-dir>/ui-graph.json
uidw --repo <repo> doctor --json
uidw --repo <repo> ui-mode --enable
```

`context` performs lazy synchronization when `autoSync` is enabled. Use `sync --force` after scanner/schema upgrades or known discovery errors. Use `--verify-content` when timestamps may be unreliable, such as restored archives or unusual network filesystems.

## Invalidation

Candidate files use size, nanosecond mtime, and SHA-256. Unchanged metadata reuses the existing digest; changed metadata is rehashed. Only added or content-modified files are analyzed again. Removed files drop their cached record. A theme or navigation change invalidates all screens; a screen/component change invalidates mapped dependents; scanner/config/cache-version changes force full reconstruction.

Metadata-only changes update the manifest without rescanning. `--verify-content` rehashes every candidate when correctness is more important than I/O cost.

Do not run a watcher, bridge server, emulator, or target application. Lazy command-boundary synchronization is deterministic, portable, and inexpensive for agent workflows.

Interactive `init` explains UI guidance and asks whether to enable it with `[y/N]`; the default and every non-interactive invocation are off. `init --ui-mode` and `init --no-ui-mode` make automation deterministic. Later use `ui-mode --enable`, `ui-mode --disable`, or bare `ui-mode` for status. Enabling guidance changes agent behavior only for UI-related tasks and does not imply review, redesign, preview generation, or source-edit permission.

Interactive `init` separately offers mock data; the default is `none`, and automation uses `init --mock-data none|representative|exhaustive`. The cached setting instructs agents how much scenario data to author, but never causes another repository scan by itself. Preserve existing `scenarioFixtures` and `screen.scenarios` for unaffected screen IDs during incremental sync; regenerate only fixtures whose source dependencies changed.
