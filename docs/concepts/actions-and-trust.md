# Actions and Trust

How firnline moves from "something happened" to "do something about it" — and
why you can trust the system not to act without your consent.

## Overview

Triggers answer *when*. Actions answer *then what*. A `ScheduleTrigger` fires
at 20:00; a `WebhookAction` tied to it calls Home Assistant to dim the lights.
The action engine lives in **effectd**; the schema lives in the `actions`
kernel schema module.

## Action Model

`Action` is an abstract `Entity` subclass. Concrete subclasses define exactly
how the effect is produced:

| Class | Key Fields | Description |
|---|---|---|
| **Action** (abstract) | `name` | Human-readable label |
| | `enabled` | Boolean gate; disabled actions are skipped by the planner |
| | `trigger` | `Trigger` IRI — which trigger causes this action to fire |
| | `executor` | Executor-kind string matched against executor plugin `kinds` (e.g. `"webhook"`, `"notify:gotify"`) |
| | `mode` | `ActionMode` — trust-ladder value (see below) |
| | `max_attempts` | Override for `EFFECTD_DEFAULT_MAX_ATTEMPTS` (optional) |
| | `retry_backoff` | ISO-8601 duration, doubled per attempt (optional) |
| | `timeout` | ISO-8601 duration cap per attempt (optional) |
| | `params` | Generic `xsd:string` bag — executors may JSON-parse it for extra config. **Secrets never live here** — the database holds logical parameters; credentials come from executor-local env vars. |
| **WebhookAction** | `url` | HTTP endpoint (**required**) |
| | `http_method` | HTTP method; default `POST` (optional) |
| | `payload_template` | `string.Template` over firing/subject/action variables (optional). If absent, `default_webhook_payload` is sent as a canonical JSON body. |
| **NotifyAction** | `title_template` | `string.Template` for the notification title (optional) |
| | `body_template` | `string.Template` for the notification body (optional) |

### Secrets Rule

**No secrets in the database.** `Action.params` holds logical configuration
(JSON string convention); credentials (`WEBHOOK_DEFAULT_TOKEN`, `GOTIFY_TOKEN`,
etc.) are read from environment variables by the executor plugin at call time.

## Trust Ladder

Every action carries an `ActionMode` — the same trust ladder used by ingestd
for AI writes:

| Mode | Behaviour |
|---|---|
| `dry_run` | Execution is recorded as `skipped` — zero side effects. Useful for testing. |
| `approval` | **Default.** Execution is planned as `pending_approval`. A human (or approval tooling) must flip the status to `pending` before effectd will execute it. |
| `auto` | Execution is planned directly as `pending` and picked up on the next cycle. **Opt-in** — because side effects are not revertible. The commit graph reverts documents, not the world. |

## Execution Lifecycle

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

- `pending_approval → pending` is the **approval seam**. Performed by
  approval tooling or the document API, **never** by effectd itself.
  `approved_at` / `approved_by` fields record who flipped it.
- `pending → succeeded` when the executor returns `ok=True`.
- `pending → failed` when the executor returns `ok=False, retryable=False`
  (permanent error — bad URL, 4xx, missing config).
- `pending → dead` when retries are exhausted (`retryable=True` but
  `attempt >= max_attempts`).
- `dry_run` mode records `skipped` at plan time and the executor is never
  called.

Plan and execute phases run in the same cycle, so auto-mode executions
planned this tick execute immediately — there is no artificial delay
between plan and execute.

### At-Least-Once Semantics and Idempotency

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

## Template Variables

Both `payload_template` (WebhookAction) and `title_template`/`body_template`
(NotifyAction) use `string.Template` substitution. Available variables:

| Variable | Source | Example |
|---|---|---|
| `$firing_id` | `firing["@id"]` | `Firing/f47ac10b-...` |
| `$firing_status` | `firing["status"]` | `pending` |
| `$scheduled_for` | `firing["scheduled_for"]` | `2026-07-07T20:00:00Z` |
| `$trigger_name` | Last segment of `firing["trigger"]` IRI | `evening-routine` |
| `$subject_label` | Fallback chain: `subject.name` → `subject.title` → `subject["@type"]` → `subject["@id"]` | `Living Room` |
| `$subject_id` | `subject["@id"]` | `Location/living-room` |
| `$action_name` | `action["name"]` | `evening-lights` |
| `$idempotency_key` | Stable per (action, firing) pair | `Action/evening-lights#Firing/f1` |

## Legacy Notification Loop

When `EFFECTD_LEGACY_NOTIFICATION_LOOP=true` (the default), effectd runs the
**zero-config default-notify path**: every pending `TriggerFiring` whose
trigger is not referenced by any `Action` document gets delivered via a
default notify executor (typically Gotify). The nag policy —
renotify/expire/snooze — is implemented inside this legacy loop.

**Consolidation follow-up**: reimplementing the nag policy
(renotify/expire/snooze) on top of `ActionExecution` documents is a
documented future item. Today, the legacy loop and the action engine
coexist.

## Approval Seam

When an action uses `mode=approval` (the default), effectd plans an
`ActionExecution` with `status=pending_approval`. The execution stays in
that state until something flips it to `pending`:

- Via the TerminusDB document API (`replace_document` with `status: pending`).
- Via approval tooling (out of scope for this release).

Effectd **never** transitions `pending_approval → pending`. That transition
is the human-in-the-loop gate. The `ActionExecution` schema enforces this
at the database level via metadata transitions.

## Worked Example: Home Assistant Lights

A `ScheduleTrigger` fires daily at sunset. A `WebhookAction` calls Home
Assistant's webhook automation API to dim the living room lights.

### 1. Home Assistant automation

In `automations.yaml`:

```yaml
- id: "firnline-lights"
  alias: "Firnline evening lights"
  trigger:
    - platform: webhook
      webhook_id: firnline-lights
  action:
    - service: light.turn_on
      target:
        entity_id: light.living_room
      data:
        brightness_pct: 30
```

### 2. WebhookAction document

```json
{
  "@type": "WebhookAction",
  "name": "evening-lights",
  "enabled": true,
  "trigger": "ScheduleTrigger/evening-routine",
  "executor": "webhook",
  "mode": "approval",
  "url": "https://hass.local/api/webhook/firnline-lights"
}
```

### 3. Runtime flow

1. **triggerd** evaluates `ScheduleTrigger/evening-routine` → materialises a
   `TriggerFiring(status=pending)`.
2. **effectd planner** discovers the `WebhookAction` referencing the same
   trigger → creates `ActionExecution(status=pending_approval)` with
   idempotency key `Action/evening-lights#Firing/<firing-id>`.
3. **Human** approves via document API → flips `status` to `pending`.
4. **effectd executor** picks up the pending execution on the next cycle,
   resolves the `webhook` executor plugin, and POSTs to Home Assistant with
   the `X-Firnline-Idempotency-Key` header.
5. Home Assistant receives the webhook, dims the lights. The
   `ActionExecution` transitions to `succeeded`.

## Related documents

- [Architecture](architecture.md) — effectd's role in the data flow
- [Entity model](entity-model.md) — `Action` and `ActionExecution` as Entity subclasses
- [Configuration reference](../reference/configuration.md) — all `EFFECTD_*` settings
- [Entry points reference](../reference/entry-points.md) — `ActionExecutor` protocol
