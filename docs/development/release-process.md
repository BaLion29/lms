# Release Process

How firnline releases are cut. Releases are **manual** — there is no CI/CD
pipeline. The maintainer runs a validation script locally, then tags and
pushes.

## Versioning

Firnline uses **Semantic Versioning** ([semver.org](https://semver.org)).
All workspace packages (16 packages in `packages/`, `services/`, `extensions/`)
are versioned together in their `pyproject.toml` files.

The current version is `0.1.0-alpha`. **Exception:** the
`firnline-ext-time-management` schema module manifest uses `0.2.0` because
it merged planning + routines into a single `time_management` module (a
logically independent version bump for the schema module itself, while the
package `pyproject.toml` stays at `0.1.0`).

### Version bump checklist

When cutting a release, update:

1. All `version` fields in `**/pyproject.toml` (checked by the validation
   script).
2. `CHANGELOG.md` — rename the `[Unreleased]` section to the new version and
   date, add a new empty `[Unreleased]` section at the top.
3. `README.md` — update the version badge.
4. Any references in documentation that hardcode the version string.

## CHANGELOG maintenance

The changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. During development, all changes go under `## [Unreleased]` in the
appropriate category:

- `### Added` — new features
- `### Changed` — changes in existing functionality
- `### Deprecated` — soon-to-be-removed features
- `### Removed` — removed features
- `### Fixed` — bug fixes

At release time, the `[Unreleased]` section is renamed to
`[<version>] - <YYYY-MM-DD>` and a new empty `[Unreleased]` section is
added above it.

## Release gate: `validate-release.sh`

Before tagging, run `scripts/validate-release.sh` from the repo root. It
must exit 0. The script checks:

1. **No leftover `lms` identity** — the project was renamed from "lms" to
   "firnline"; tracked files must not contain the old name (with explicit
   allow list for legitimate uses in docs and comments).
2. **No secrets** — no API keys matching `sk-[A-Za-z0-9]{16,}` in tracked
   files (except opencode configuration). Always review the diff manually
   as well.
3. **No tracked junk** — no `__pycache__`, `.pyc`, `.pytest_cache`, or
   `node_modules` in git.
4. **LICENSE present** — contains "Apache License".
5. **All pyproject.toml versions match** — every workspace package must
   have the same version string.
6. **CHANGELOG has the version section** — e.g. `## [0.1.0-alpha]`.
7. **Lockfile consistent** — `uv lock --check`.
8. **Sync succeeds** — `uv sync --all-packages`.
9. **Unit tests pass** — `pytest -m "not integration"`.
10. **CLI smoke** — `firnline-schema --help` exits 0.
11. **Import smoke** — `firnline_core`, `firnline_schema`, `captured`,
    `ingestd`, `queryd`, `triggerd` import without error.
12. **Schema compose smoke** — `firnline-schema compose` against
    `schema/modules/` into a temp directory (no database needed).
13. **Melt test** — kernel-purity check: compose + codegen with zero
    extensions, verify generated files are clean, kernel imports work.
14. **Docker compose config valid** — `docker compose config -q` for both
    the external and bundled TerminusDB profiles (skipped if Docker is not
    installed).
15. **Docs link check** — all relative markdown links in `README.md` and
    `docs/*.md` resolve to existing files.

## Tagging convention

Tags follow the pattern `v<version>`:

```bash
git tag -a v0.1.0-alpha -m "firnline v0.1.0-alpha"
```

## Full release sequence

1. **Update versions and CHANGELOG** (see version bump checklist above).
2. **Review the diff:**
   ```bash
   git status
   git diff
   ```
3. **Run the validation script:**
   ```bash
   bash scripts/validate-release.sh
   ```
   All checks must pass. Fix any failures before proceeding.
4. **Verify no secrets:** manually review `git diff` for accidental keys,
   tokens, or passwords.
5. **Commit:**
   ```bash
   git add -A
   git commit -m "chore(release): prepare v<version>"
   ```
6. **Tag:**
   ```bash
   git tag -a v<version> -m "firnline v<version>"
   ```
7. **Push:**
   ```bash
   git push origin main --tags
   ```
   (Repository URL: `git@github.com:BaLion29/firnline.git`)

## After the release

- Update the `[Unreleased]` section in CHANGELOG.md if you haven't already.
- Announce on relevant channels.

## Related documents

- [contributing.md](contributing.md) — how to contribute between releases
- [testing.md](testing.md) — details on test execution and conventions
- [documentation.md](documentation.md) — docs link check and style guide
