# Architecture Decision Records

Architecture Decision Records (ADRs) capture significant architectural and
design choices made in the firnline project. They are the permanent record of
*why* the system is built the way it is.

## When to write an ADR

Write an ADR whenever you make a decision that:

- Affects the system's architecture, core abstractions, or technology stack.
- Involves a trade-off between multiple viable alternatives.
- Establishes a design principle that future contributors must follow.
- Would be difficult or expensive to reverse later.

You do **not** need an ADR for routine implementation details, bug fixes, or
decisions that are fully reversible with low effort.

## Numbering and status

ADRs are numbered sequentially (`ADR-001`, `ADR-002`, …) and use one of three
statuses:

| Status | Meaning |
|---|---|
| **Proposed** | Under discussion; not yet adopted. |
| **Accepted** | Adopted and in effect. |
| **Superseded** | Replaced by a later ADR (reference the successor in the text). |

Once accepted, an ADR is never deleted — it is superseded if the decision is
overturned.

## ADR index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-terminusdb-as-source-of-truth.md) | TerminusDB as Source of Truth | Accepted |
| [ADR-002](ADR-002-entry-point-plugin-system.md) | Entry-Point Plugin System | Accepted |
| [ADR-003](ADR-003-unified-capture-pipeline.md) | Unified Capture Pipeline | Accepted |
| [ADR-004](ADR-004-trust-ladder-for-actions.md) | Trust Ladder for Automated Actions | Accepted |
| [ADR-005](ADR-005-llm-via-litellm-proxy.md) | LLM Access via LiteLLM Proxy | Accepted |

## Writing a new ADR

Use [template.md](template.md) as a starting point. Fill in the context
(what problem are we solving?), the decision (what did we choose and why?),
the alternatives considered (what else was on the table and why was it
rejected?), and the consequences (what becomes easier or harder because of
this choice?).
