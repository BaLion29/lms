# Actions

## Purpose

This page explains the action engine — how trigger firings become external
effects (webhooks, notifications, home-automation calls). It covers the action
model, the trust ladder, the execution lifecycle, and the approval seam. It is
for anyone integrating triggers with external systems or writing action
executor plugins.

## Why actions?

Triggers answer *when*. Actions answer *then what*. A `ScheduleTrigger` fires
at 20:00; a `WebhookAction` tied to it calls Home Assistant to dim the lights.
They are the bridge from "something happened" to "do something about it".

## Action model

`Action` is an abstract `Entity` subclass. Concrete subclasses define
exactly how the effect is produced:

| Class | Purpose |
|---|---|
| **Action** (abstract) | Base carrying `name`, `enabled`, `trigger` IRI, `executor` kind, `mode` (trust ladder), `max_attempts`, `retry_backoff`, `timeout`, and `params` (a generic JSON string bag for logical configuration). |
| **WebhookAction** | Calls an HTTP endpoint. Requires a `url` and carries optional `http_method` (default `POST`) and a `payload_template` for `string.Template` substitution. |
| **NotifyAction** | Delivers a notification through a configured channel. Carries optional `title_template` and `body_template` for `string.Template` substitution. |

For the full field reference — types, defaults, and constraints — see the
[actions reference](../reference/actions.md).

### Secrets rule

**No secrets in the database.** `Action.params` holds logical configuration
(JSON string convention); credentials (`WEBHOOK_DEFAULT_TOKEN`, `GOTIFY_TOKEN`,
etc.) are read from environment variables by the executor plugin at call time.

## Trust ladder

Every action carries an `ActionMode` — the same trust ladder used by ingestd:

| Mode | Behaviour |
|---|---|
| `dry_run` | Execution is recorded as `skipped` — zero side effects. Useful for testing. |
| `approval` | **Default.** Execution is planned as `pending_approval`. A human (or approval tooling) must flip the status to `pending` before effectd will execute it. |
| `auto` | Execution is planned directly as `pending` and picked up on the next cycle. **Opt-in** — because side effects are not revertible. The commit graph reverts documents, not the world. |

## Execution lifecycle

```
                    ┌─ dry_run ─► skipped
                    │
  pending_approval ─┤
                    │              ┌─ retry (backoff) ────┐
                    └─ pending ────┤                       │
                                   ├─ succeeded            │
                                   ├─ failed (non-retryable│
                                   ├─ dead (retries exhausted)
```

- `pending_approval` → `pending` is the **approval seam**. Performed by
  approval tooling or the document API, **never** by effectd itself.
  `approved_at` / `approved_by` fields record who flipped it.
- `pending` → `succeeded` when the executor returns `ok=True`.
- `pending` → `failed` when the executor returns `ok=False, retryable=False`
  (permanent error — bad URL, 4xx, missing config).
- `pending` → `dead` when retries are exhausted (`retryable=True` but
  `attempt >= max_attempts`).
- `dry_run` mode records `skipped` at plan time and the executor is never
  called.

Plan and execute phases run in the same cycle, so auto-mode executions
planned this tick execute immediately — there is no artificial delay
between plan and execute.

### At-least-once semantics + idempotency

Effectd runs as a **single-replica polling daemon**. There is deliberately
no `running` status — with no lease protocol, a running state would strand
executions on crash. Instead each attempt is either recorded succeeded/failed
after the fact or never started (single-replica assumption).

Executions are **at-least-once**. The executor receives an idempotency key
and is expected to pass it downstream so that external systems can dedupe:

- Idempotency key format: `<short-action-iri>#<short-firing-iri>`
  (e.g. `Action/evening-lights#Firing/f47ac10b`)
- Sent as the `X-Firnline-Idempotency-Key` HTTP header for webhook executors;
  available as the `$idempotency_key` template variable.

Retry uses **exponential backoff**: `retry_backoff × 2^attempt`. Default
backoff is 1 minute; doubling yields 1m, 2m, 4m for 3 attempts.

## Template variables

Both `payload_template` (WebhookAction) and `title_template`/`body_template`
(NotifyAction) use `string.Template` substitution. Available variables include:
`$firing_id`, `$firing_status`, `$scheduled_for`, `$trigger_name`,
`$subject_label`, `$subject_id`, `$action_name`, and `$idempotency_key`.
Subject labels follow a fallback chain: `subject.name` → `subject.title` →
`subject["@type"]` → `subject["@id"]`. The full template variable reference
lives in the [actions reference](../reference/actions.md).

## Legacy notification loop

When `EFFECTD_LEGACY_NOTIFICATION_LOOP=true` (the default), effectd runs the
**zero-config default-notify path**: every pending `TriggerFiring` whose
trigger is not referenced by any `Action` document gets delivered via a
default notify executor. The nag policy — renotify/expire/snooze — is
implemented inside this legacy loop.

The legacy loop and the action engine coexist. Consolidating the nag policy on
top of `ActionExecution` documents is a documented future direction.

## Approval seam

When an action uses `mode=approval` (the default), effectd plans an
`ActionExecution` with `status=pending_approval`. The execution stays in
that state until something flips it to `pending`:

- Via the TerminusDB document API (`replace_document` with `status: pending`).
- Via approval tooling (out of scope for this release).

Effectd **never** transitions `pending_approval → pending`. That transition
is the human-in-the-loop gate. The `ActionExecution` schema enforces this
at the database level via metadata transitions.

## Related documents

- [Automations guide](../guides/automations.md) — worked example: Home Assistant lights via WebhookAction
- [Architecture](../concepts/architecture.md) — how triggerd and effectd fit into the system
- [Writing extensions](../guides/writing-extensions.md) — implementing custom action executors
- [Configuration reference](../reference/configuration.md) — `EFFECTD_*` settings
