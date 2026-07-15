# Documentation

How firnline documentation is organized, written, and maintained. Follow these
rules so the docs stay consistent and navigable.

## Taxonomy — where new pages go

The docs tree is split by purpose, not by component:

| Directory | Purpose | Decision rule |
|---|---|---|
| `getting-started/` | Onboarding — install, configure, first run | "I'm new and want to try firnline" |
| `guides/` | Task-oriented how-to pages | "How do I do X?" — step-by-step instructions |
| `concepts/` | Explanations and background — the *why* | "What is this and why does it work this way?" |
| `reference/` | Exhaustive, lookup-oriented reference | "What are all the knobs?" — env vars, CLI commands, API endpoints, entry-point protocols, schema format |
| `development/` | Contributor documentation — build, test, release, architecture of the codebase | "I want to contribute code" |
| `decisions/` | Architecture Decision Records (ADRs) | "Why did we choose this over alternatives?" |
| Root files | High-level navigation (`docs/README.md`), roadmap, FAQ | Cross-cutting |

When adding a new page, pick the directory whose purpose it serves. If a page
serves two purposes equally, put it in the more specific directory and add a
link from the other.

## Standard page template

Every page should follow this structure (skip empty sections):

```
# Title

**Purpose:** One sentence stating what the reader will learn or accomplish.

## Overview
Brief context — what this topic is and why the reader should care.

## Main sections
Task-oriented headings using imperative mood for guides, descriptive for reference.

## Examples
Concrete commands or configurations the reader can copy.

## Common pitfalls
Mistakes, gotchas, anti-patterns.

## Related documents
- relative link to related-doc — one-line description
```

- Headings after `# Title` start at `##`. Use `###` for subsections.
- Code blocks specify their language: ` ```bash `, ` ```python `, ` ```toml `.
- Shell commands use `$ ` prefix only when showing output alongside.
  Prefer clean copy-pasteable blocks.

## Principles

### One concept per page

Each page has a single, clear purpose. If you find yourself writing two
separate "Overview" sections, split the page.

### Link, don't duplicate

Never reproduce content that has a canonical home. Always link to it.

**Canonical homes:**

| Content type | Canonical location |
|---|---|
| Environment variables | `reference/configuration.md` — the one place all env vars are documented |
| API endpoints (paths, methods, responses) | `reference/api/` — one file per service |
| Protocol signatures (entry-point contracts) | `reference/entry-points.md` — complete signatures for every plugin protocol |
| Schema module format (manifest.json, schema.json, validation levels) | `reference/schema-modules.md` |
| CLI commands | `reference/cli.md` |

If you need to mention a specific env var in a guide, link to
`reference/configuration.md` — don't duplicate the table. If you need to
reference a `CaptureHandler` protocol, link to `reference/entry-points.md`.

### Update docs in the same PR as code

Documentation changes go in the same branch and PR as the code they document.
The docs link check in `validate-release.sh` helps catch broken links.

### Service READMEs are thin stubs

Service READMEs (`services/*/README.md`) stay minimal — they point to the
canonical docs pages. No deep architectural explanations; those live in
`concepts/` or `reference/`.

## Architecture Decision Records (ADRs)

For significant design decisions — technology choices, architectural
tradeoffs, rejected alternatives — create an ADR under `decisions/`. See
[../decisions/README.md](../decisions/README.md) for the ADR template and
process.

## Checking links

The release validation script checks that all relative markdown links in
`README.md` and `docs/**/*.md` resolve to existing files:

```bash
bash scripts/validate-release.sh   # includes the docs link check
```

Run this after reorganizing or adding cross-references.

## Style reference

- Use sentence case for headings (`# Local development`, not
  `# Local Development`).
- Wrap shell commands, file paths, and env var names in backticks:
  `` `uv run pytest` ``, `` `CAPTURED_TDB_URL` ``.
- Use **bold** for UI elements and emphasis, not headers.
- Keep lines under 120 characters where practical (matching the Python
  line-length setting).

## Related documents

- [contributing.md](contributing.md) — contributor workflow
- [release-process.md](release-process.md) — validation gates