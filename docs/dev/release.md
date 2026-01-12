# Release Flow

BrkRaw Viewer uses a PR-based release flow that mirrors the brkraw core:

1. Run the release prep task to create a PR.
2. Review the PR, ensure CI passes, and apply the `release` label.
3. On merge, a tag is created from the merge commit.
4. The tag triggers GitHub Release creation.
5. When the Release is published, PyPI publish and docs deploy run.

## VSCode tasks

- `Standard: Release Prep PR (2-step)`
  - Creates or updates a release prep PR.
  - Bumps version, updates contributors, and generates release notes.
- `Optional: Release Prep (bump + notes)`
  - Updates contributors + runs release prep without PR automation.

## Release labels

- `release`: required for tagging on merge.

## Notes

- Pre-release tags (`a`, `b`, `rc`) create GitHub pre-releases and skip PyPI.
- Tag must match `pyproject.toml` version.
