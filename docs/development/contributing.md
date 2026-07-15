# Contributing

How to contribute to firnline. The project is pre-release (v0.1.0-alpha) and
maintained manually — no CI/CD pipeline exists. All checks run locally.

## Where to discuss

Open an issue or start a discussion on the
[GitHub repository](https://github.com/BaLion29/firnline). For
larger feature ideas, open an issue first to align on scope before writing
code.

## Workflow

1. **Fork** the repo and create a feature branch from `main`.
2. **Make your changes**, keeping them focused on one concern.
3. **Update the docs** in the same commit or PR — the docs live alongside
   the code in `docs/`. See [documentation.md](documentation.md) for where
   new content belongs.
4. **Update CHANGELOG.md** — add a bullet under the `## [Unreleased]` section
   (keep-a-changelog format). Use the appropriate category (`### Changed`,
   `### Added`, `### Fixed`, etc.).
5. **Run local checks:**
   ```bash
   uv run pytest                    # all non-integration tests
   uv run ruff check                # lint
   uv run ruff format --check       # format
   bash scripts/validate-release.sh # full release gate (no secrets, lockfile, docs links)
   ```
6. **Open a PR** against `main`. Describe what changed and why.

## What to check

- All tests pass with `uv run pytest`. Integration tests (marker
  `integration`) are excluded by default — they require a running
  TerminusDB instance.
- No secrets in the diff. The release script checks for accidental API
  keys (`sk-...` patterns).
- Relative markdown links resolve to existing files (also checked by
  `validate-release.sh`).
- Generated files under `packages/firnline-core/src/firnline_core/generated/`
  are up-to-date (run `firnline-schema codegen` with all extensions
  installed before committing model changes).

## License

All contributions are under Apache-2.0, matching the project license.
By opening a PR you agree to license your work under those terms.

## Related documents

- [local-development.md](local-development.md) — dev environment setup
- [testing.md](testing.md) — test conventions and commands
- [documentation.md](documentation.md) — docs structure and style guide
- [release-process.md](release-process.md) — how releases are cut
