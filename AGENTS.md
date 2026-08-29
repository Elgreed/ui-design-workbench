# Repository Instructions

## Changelog and versions

- Add every user-visible feature, fix, or behavior change to `CHANGELOG.md` under `Unreleased` in the same commit.
- A commit that changes the project or CLI version must update `CHANGELOG.md` in the same commit: move the relevant entries from `Unreleased` into a dated `## [X.Y.Z] - YYYY-MM-DD` section.
- Keep the version in `pyproject.toml`, `CLI_VERSION` in `scripts/uidw.py`, both README files, and the changelog release heading identical.
- Do not create or push a release tag until the dated changelog section exists.

## Mandatory release completion

- A request to create, publish, or finish a release is not complete after changing the version, committing, or pushing `main`.
- Complete every release in this order: update the dated changelog and all version fields; run the release checks; commit and push the release commit; create an annotated `vX.Y.Z` tag on that exact commit; push the tag to `origin`; verify that the tag created a `Release` GitHub Actions run; wait for all release jobs to pass; verify the matching PyPI version and GitHub Release assets.
- The tag push is mandatory because `.github/workflows/release.yml` is tag-driven. A version bump, a push to `main`, or a manually created GitHub Release does not substitute for pushing the tag.
- Do not report a release as complete while its tag is only local, no matching Actions run exists, the run is still pending, or any release job failed.
- Never move or reuse a published version tag. Fix the issue and publish a new patch version instead.
