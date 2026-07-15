# ADR-004: Trust Ladder for Automated Actions

**Status:** Accepted (recorded retroactively)

**Date:** 2026-07-15

## Context

Firnline's AI writes to the database (ingestd extracting structured documents
from captured text), and its action engine (effectd) executes external
effects — calling webhooks, pushing notifications, triggering home-automation
routines. These automated writes and side effects are valuable but carry risk:
an incorrect extraction creates bogus tasks; a misconfigured webhook fires at
the wrong time. The system needs a graduated trust model that lets users
start safe and earn confidence, without requiring a single all-or-nothing
safety switch.

The action engine (effectd) operates on `Action` documents linked to
`TriggerFiring` records. Side effects are not revertible — rolling back a
TerminusDB commit does not un-send a webhook or un-push a notification.

## Decision

A **three-tier trust ladder** applies to every automated action:

| Mode | Behaviour |
|---|---|
| `dry_run` | Execution is recorded as `skipped` — zero side effects. The executor is never called. Useful for testing trigger schedules and action wiring. |
| `approval` | **Default.** The planner creates `ActionExecution` documents with `status=pending_approval`. A human (or approval tooling) must flip the status to `pending` before effectd executes. The `pending_approval → pending` transition is the human-in-the-loop gate — effectd **never** performs it. |
| `auto` | The planner creates `ActionExecution` documents with `status=pending` and they are executed on the next poll cycle. **Opt-in** — because side effects cannot be reverted. |

The same ladder is used by ingestd but through environment-level gates:
`INGESTD_DRY_RUN=true` for reads-but-no-writes, `TDB_BRANCH` pointing at a
staging branch for review-before-promote, and direct-to-main for earned trust.

**At-least-once semantics with idempotency keys:** Effectd runs as a
single-replica polling daemon with no lease protocol. Each execution carries
an idempotency key (`<short-action-iri>#<short-firing-iri>`), sent as the
`X-Firnline-Idempotency-Key` HTTP header for webhook executors. External
systems use this key to deduplicate. Retry uses exponential backoff
(`retry_backoff × 2^attempt`).

Provenance applies at every level: AI commits carry `author=<service>`,
every `Entity` carries a required `Provenance` (birth certificate), and
the `derived_from` link doubles as ingestd's idempotency guard (before
processing a captured item, ingestd checks `derived_from` for duplicates).

## Alternatives considered (reconstructed)

| Alternative | Why rejected |
|---|---|
| **Global kill-switch (single on/off)** | Too coarse. A user who trusts task extraction but not webhook automation cannot distinguish. Forces all-or-nothing trust. |
| **Always-manual (no automation at all)** | Defeats the purpose of an ADHD system: the bottleneck is human attention. Automation is the value proposition. |
| **Full-auto with rollback** | TerminusDB commits are revertible, but external side effects (webhooks, notifications) are not. A revert-only safety net leaves half the risk surface unaddressed. |
| **Per-service binary switch** | Same coarseness problem as global kill-switch, just split by service. Doesn't let individual actions within a service have different trust levels. |

## Consequences

- **Easier:** Users can start with `dry_run`, graduate to `approval`, and
  eventually opt specific actions into `auto` as trust builds. The approval
  seam is explicit and database-enforced. Idempotency keys prevent duplicate
  side effects even on retry.
- **Harder:** The approval step requires a human to monitor and act on
  `pending_approval` executions. Approval tooling is out of scope for v0.1.0.
  The implicit assumption is that the user interacts with TerminusDB directly
  (or via queryd's write tools) to approve.
- **Operational:** `EFFECTD_DRY_RUN=true` is a global override that forces
  all actions to `skipped` regardless of per-action mode — useful for
  deployment testing.

## References

- [Actions and Trust](../concepts/actions-and-trust.md) — Action model, trust ladder, execution lifecycle
- [Vision](../concepts/vision.md) — AI writes with provenance, branches are the review boundary
- [Architecture](../concepts/architecture.md) — Principle 3: AI writes with provenance
