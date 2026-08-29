# Releasing UI Design Workbench

## Distribution channels

| Channel | Role |
| --- | --- |
| PyPI wheel + `pipx` | Primary stable installation and upgrades |
| GitHub ZIP archive | Clone-free installation before the first PyPI release |
| GitHub Release | Release notes, wheel, source archive, and SHA-256 checksums |
| Windows `.exe` | Future convenience asset for users without Python |

Stable user installation:

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

The wheel contains the Agent Skill, references, schemas, and runtime fallback scripts. `uidw install-skill` copies that payload into the selected agent's discovery directory, so users do not need a repository checkout.

## One-time PyPI setup

The workflow at `.github/workflows/release.yml` publishes through PyPI Trusted Publishing and does not use a stored API token. Configure a pending publisher in PyPI with:

| Field | Value |
| --- | --- |
| PyPI project | `ui-design-workbench-cli` |
| GitHub owner | `Elgreed` |
| Repository | `ui-design-workbench` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Create the GitHub `pypi` environment if release approval should be required. The workflow requests only `id-token: write` for PyPI and `contents: write` for the GitHub Release job.

## Release workflow

1. Move the target changes from `Unreleased` in `CHANGELOG.md` to a dated `X.Y.Z` section.
2. Set the same version in `pyproject.toml` and `CLI_VERSION` in `scripts/uidw.py`.
3. Run the tests and build checks locally.
4. Commit the release state, create tag `vX.Y.Z`, and push the tag.

```sh
git tag v0.3.5
git push origin v0.3.5
```

The tag starts one GitHub Actions workflow that:

1. verifies the tag, package, CLI, and changelog versions;
2. runs the test suite;
3. builds and validates the wheel and source distribution;
4. publishes the immutable version to PyPI through Trusted Publishing;
5. creates SHA-256 checksums and a GitHub Release with the package artifacts.

PyPI versions cannot be replaced. If a published artifact is wrong, fix it and release a new patch version.

## Local release checks

```sh
python -m unittest discover -s scripts -p "test_*.py"
python -m build
python -m twine check dist/*
python scripts/check_release_version.py v0.3.5
```

Install the built wheel into a clean `pipx` environment and verify:

```sh
pipx install dist/ui_design_workbench_cli-0.3.5-py3-none-any.whl
uidw --version
uidw install-skill codex
uidw doctor
```

## Windows executable policy

An `.exe` may be added later, but it should not replace the PyPI/pipx release:

- PyInstaller must build and test each operating system and architecture separately.
- A one-file executable extracts bundled files at runtime and starts more slowly.
- Code signing and published checksums should be in place before recommending a binary as the easiest Windows path.

The current CLI still needs frozen-safe handling for `smoke_preview.js`, shared schemas/profiles, and the `visual-test` subprocess before `uidw-windows-x64.exe` can be trustworthy. Build and test a PyInstaller `onedir` artifact before adding `onefile` release assets.

## Primary references

- [PyPA: installing standalone command-line tools](https://packaging.python.org/en/latest/guides/installing-stand-alone-command-line-tools/)
- [PyPA: packaging command-line tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)
- [PyPA: Trusted Publishing with GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [PyInstaller platform notes](https://pyinstaller.org/en/stable/usage.html)
