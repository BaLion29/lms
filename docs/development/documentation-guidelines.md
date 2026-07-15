# Documentation guidelines

## Purpose

This page describes how documentation is maintained in the firnline repo. It is
for anyone who writes, reviews, or reorganises docs — contributors and
maintainers alike.

## The four-tier system

Every page belongs to exactly one tier. Before writing, decide which tier your
page serves.

| Tier | Question | Home |
|---|---|---|
| **Getting started** | First contact — what is this and how do I try it? | `getting-started/` |
| **Concepts** | *Why* does it work this way? | `concepts/` |
| **Guides** | *How* do I accomplish a specific task? | `guides/` |
| **Reference** | *What* are the exact facts (env vars, endpoints, schemas)? | `reference/` |

### What belongs where

- **Getting started** — installation, quickstart, prerequisite lists. Short,
  linear, and assumes no prior knowledge.
- **Concepts** — design rationale, architecture decisions, data-model
  explanations. Use these when you need the reader to understand the mental
  model.
- **Guides** — step-by-step instructions for a concrete outcome. Each guide
  answers exactly one "how do I…" question. Link to reference pages for
  details; never inline large tables.
- **Reference** — the single source of truth for all tables: environment
  variables, API endpoints, CLI flags, tool lists, plugin protocols. Other
  pages must link here instead of copying tables.

## Rules

### One question per page

A page should answer one clear question. If you find yourself explaining two
unrelated things, split the page.

### Link, don't duplicate

Reference pages own the canonical tables. Concepts and guides may summarise a
few fields for context but must link to reference for the full list. There
should never be two copies of the same table.

### Relative links only

All cross-references use relative Markdown links — `[label](../reference/api.md)`.
No absolute paths, no `https://` links to the same repo.

### Docs are code

- Update docs in the same PR as the code change they describe.
- Docs are reviewed alongside code changes.
- A PR that adds a feature without doc updates is incomplete.

## Page template

Every page follows this structure:

```markdown
# Title (sentence case)

## Purpose

One or two sentences describing what this page covers and who should read it.

## Prerequisites

- What the reader must already have running or understand (optional; omit if
  none).

## Main content sections

Named with sentence-case headings. Use the structure that best serves the content.

## Common pitfalls

Errors, gotchas, and debugging tips (optional).

## Related documents

- [First link](../some/page.md) — short description
- [Second link](../another/page.md) — short description
```

The first heading must be `# Title`. The last section must be `## Related
documents` with a bullet list of relative links and one-line descriptions.

`docs/README.md` (the documentation hub landing page) and
`docs/decisions/template.md` (the ADR template) are exempt from this template;
neither carries Purpose nor Related documents sections.

## When to write an ADR

An Architecture Decision Record (ADR) captures a significant, hard-to-reverse
design choice — technology selection, protocol design, schema architecture,
extension model. Use the [ADR template](../decisions/template.md) and file it
under `docs/decisions/`.

Not every decision needs an ADR. If the choice is local, easily changed, or
obvious from context, document it inline. When in doubt, ask in the PR.
