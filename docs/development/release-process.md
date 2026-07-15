# Release process

## Purpose

This page documents the release checklist for firnline maintainers — versioning
conventions, validation steps, and how to tag and push a release.

## Prerequisites

- `uv` installed and all packages synced (`uv sync --all-packages`).
- Docker installed (optional — skipped if unavailable).
- A clean working tree with all intended changes committed.

## Versioning

Firnline follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Tags use the format `v0.1.0-alpha` (pre-release) or `v0.1.0` (stable).

The workspace root `pyproject.toml` declares `version = "0.1.0"`. All
non-extension packages and services under `packages/` and `services/` must
carry the same version. Extensions under `extensions/` may version
independently.

## Changelog

`CHANGELOG.md` at the repo root follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/) with sections `Added`,
`Changed`, `Deprecated`, `Removed`, `Fixed`, and `Security`. Each release has
a `## [version] - YYYY-MM-DD` heading.

## Release checklist

Run `scripts/validate-release.sh` before each step marked with [✓].

### 1. Rotate leaked API keys [✓]

If a key matching `sk-[A-Za-z0-9]{16,}` exists in git history, revoke it,
generate a new one, and `export LITELLM_API_KEY=sk-...`. The leak check is
part of `validate-release.sh`.

### 2. Review the diff

```bash
git status && git diff
```

### 3. Validate [✓]

```bash
bash scripts/validate-release.sh
```

This script runs 15 checks covering:

| Check | What it validates |
|---|---|
| No old project-name residuals | Git-tracked files and contents must not contain "lms" (former working name) |
| No secrets in tracked files | No API key patterns (`sk-...`) outside allowed config files |
| No tracked junk | No `__pycache__`, `.pyc`, `.pytest_cache`, `node_modules` in git |
| License present | `LICENSE` exists and contains "Apache License" |
| Version consistency | All non-extension `pyproject.toml` files have `version = "0.1.0"` |
| Changelog entry | `CHANGELOG.md` contains a `## [0.1.0-alpha]` section |
| Lockfile consistency | `uv lock --check` passes |
| Sync | `uv sync --all-packages` succeeds |
| Unit tests | `pytest -m 'not integration'` passes (integration tests are opt-in) |
| CLI smoke | `firnline-schema --help` exits 0 |
| Import smoke | Core packages and services import successfully |
| Schema compose | `firnline-schema compose` against `schema/modules/` succeeds |
| Melt test | Kernel-purity check: compose, codegen, import, and pytest with zero extensions |
| Docker compose | `docker compose config -q` is valid (skipped if Docker unavailable) |
| Doc links | All relative Markdown links in `README.md` and `docs/*.md` resolve to existing files |

Exit code must be 0. Any failure must be fixed before proceeding.

### 4. Commit

```bash
git add -A
git commit -m "chore(release): v0.1.0-alpha prep"
```

### 5. Tag

```bash
git tag -a v0.1.0-alpha -m "firnline v0.1.0-alpha"
```

### 6. Push (optional)

If pushing to a new remote:

```bash
git remote remove origin
git remote add origin git@github.com:BaLion29/firnline.git
git push origin main --tags
```

### 7. Post-release: deep-clean leaked keys

Rotated keys from step 1 remain in git history. Rotation is mandatory;
history rewrite (e.g. `git filter-branch`) is optional but recommended for
public repositories.

## What the melt test validates

`scripts/melt-test.sh` is the machine-enforced kernel-purity check
(invoked by `validate-release.sh`). It proves that the kernel — core,
capture, and triggers schema modules with zero extensions — is self-contained
and functional:

1. **Kernel-only compose**: `firnline-schema compose --no-entry-points` with
   only `schema/modules/` (no extension packages).
2. **Codegen**: generates Pydantic models from the kernel-only composed
   schema.
3. **Diff check (checksum-tolerant)**: compares generated files against
   committed versions. Checksum-only changes in the source-lock header are
   tolerated; content differences are flagged.
4. **Untracked file check**: kernel-only codegen must not create new
   untracked files under `packages/` or `extensions/`.
5. **Kernel import melt**: verifies `firnline_core`, `firnline_core.models`,
   `firnline_core.tooling`, `firnline_core.plugins`, and `firnline_core.tdb`
   all import successfully.
6. **Kernel pytest**: runs the dedicated melt test suite at
   `scripts/melt_test/` — must pass.

## Common pitfalls

- **`uv lock --check` fails** — run `uv lock` to regenerate the lockfile,
  then commit the updated `uv.lock`.
- **Melt test diff check fails** — the generated files in
  `packages/firnline-core/src/firnline_core/generated/` have drifted from the
  full-compose codegen output. Run `uv run --package firnline-schema
  firnline-schema codegen` from a full sync and commit the result.
- **Docker compose check skipped** — this is not a failure. Install Docker
  if you want compose validation in the release check.
- **Pytest failures after sync** — ensure `uv sync --all-packages` completed
  without errors. Workspace inter-package imports require the full sync.

## Related documents

- [Local development](local-development.md)
- [Project structure](project-structure.md)
- [Documentation guidelines](documentation-guidelines.md)
