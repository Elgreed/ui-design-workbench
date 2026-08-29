# Repository Instructions

## Changelog and versions

- Add every user-visible feature, fix, or behavior change to `CHANGELOG.md` under `Unreleased` in the same commit.
- A commit that changes the project or CLI version must update `CHANGELOG.md` in the same commit: move the relevant entries from `Unreleased` into a dated `## [X.Y.Z] - YYYY-MM-DD` section.
- Keep the version in `pyproject.toml`, `CLI_VERSION` in `scripts/uidw.py`, both README files, and the changelog release heading identical.
- Do not create or push a release tag until the dated changelog section exists.
