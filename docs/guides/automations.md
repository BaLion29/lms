# Automations

## Purpose

How to wire firnline triggers to external actions — call a webhook, push a
notification, or trigger a home-automation routine. This guide walks through
creating a `WebhookAction`, understanding the trust ladder, and verifying
delivery.

## Prerequisites

- A running firnline deployment with `triggerd` and `effectd` healthy.
- A reachable HTTP endpoint (e.g. Home Assistant webhook, n8n webhook, Gotify).

For the full action model and execution lifecycle, see
[../concepts/actions.md](../concepts/actions.md). For all effectd settings, see
[../reference/configuration.md](../reference/configuration.md).

## Worked example: Home Assistant lights

A `ScheduleTrigger` fires daily at sunset. A `WebhookAction` calls Home
Assistant's webhook automation API to dim the living room lights.

### 1. Create the receiver (Home Assistant)

In Home Assistant `automations.yaml`:

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

### 2. Create the WebhookAction document

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

Key fields:

- `executor` — must be `"webhook"` for the reference webhook executor
  (`firnline-ext-webhook`). Other executor kinds include `"notify:gotify"`,
  `"hass"`, or any custom executor registered via `firnline.effectd.executors`.
- `url` — **required**. The HTTP endpoint to call.
- `http_method` — optional; defaults to `POST`.
- `payload_template` — optional `string.Template` over the firing/subject/action
  variables. When absent, the canonical `default_webhook_payload` JSON body is
  sent.
- `params` — optional JSON string bag for executor-specific config. **No
  secrets here** — credentials come from executor-local env vars
  (`WEBHOOK_DEFAULT_TOKEN`, etc.).

### 3. Trust ladder in practice

Every action carries an `ActionMode`, the same trust ladder used by ingestd:

| Mode | Behaviour |
|---|---|
| `dry_run` | Execution recorded as `skipped` — zero side effects. Use this first. |
| `approval` | **Default.** Execution planned as `pending_approval`. A human must flip to `pending` before effectd runs it. |
| `auto` | Execution planned directly as `pending` and picked up on the next cycle. **Opt-in** — side effects are not revertible. |

**Recommendation:** Start with `dry_run` to verify the wiring. Then switch to
`approval` for a few cycles. Graduate to `auto` only when you trust the
automation.

### 4. Template variables

When supplying a `payload_template`, `string.Template` variables are available
in addition to the idempotency key (`$idempotency_key`). See the
[actions reference](../reference/actions.md) for the full variable table.

The idempotency key is also sent as the `X-Firnline-Idempotency-Key` HTTP
header, enabling downstream systems to deduplicate.

### 5. The approval seam

When an action uses `mode=approval` (the default), effectd plans an
`ActionExecution` with `status=pending_approval`. The execution stays in
that state until something flips it to `pending`:

- Via the TerminusDB document API (`replace_document` with `status: pending`).
- Via approval tooling (out of scope for this release).

Effectd **never** transitions `pending_approval → pending`. That transition
is the human-in-the-loop gate.

### 6. Runtime flow

1. **triggerd** evaluates the trigger → materialises a `TriggerFiring(status=pending)`.
2. **effectd planner** discovers the `WebhookAction` referencing the same
   trigger → creates `ActionExecution(status=pending_approval)` with
   idempotency key `Action/<action-name>#Firing/<firing-id>`.
3. **Human** approves via document API → flips `status` to `pending`.
4. **effectd executor** picks up the pending execution on the next cycle,
   resolves the `webhook` executor plugin, and POSTs to the target URL with
   the `X-Firnline-Idempotency-Key` header.
5. The endpoint receives the webhook. The `ActionExecution` transitions to
   `succeeded`.

### 7. HTTP result mapping (webhook executor)

The reference webhook executor (`firnline-ext-webhook`) maps HTTP responses as
follows:

| Status | Result |
|---|---|
| 2xx | `ok=True`, `external_ref` = `Location` header if present |
| 4xx | `ok=False`, `retryable=False` |
| 5xx, timeout, connection error | `ok=False`, `retryable=True` |

Retryable failures go through exponential backoff:
`retry_backoff × 2^attempt`. Default backoff is 1 minute; doubling yields
1m, 2m, 4m for 3 attempts. Executions are **at-least-once** — the
idempotency key enables downstream deduplication.

### 8. Verify delivery

Check the effectd liveness:

```bash
docker compose exec effectd find /tmp/effectd-alive -mmin -5
```

Query `ActionExecution` documents to confirm status transitions:

```bash
curl -s -X POST "http://<tdb-host>:6363/api/graphql/admin/firnline" \
  -H "Content-Type: application/json" \
  -u admin:$TDB_PASSWORD \
  -d '{"query": "{ ActionExecution { id status } }"}'
```

## Related documents

- [../concepts/actions.md](../concepts/actions.md) — action model, trust ladder, and execution lifecycle
- [../reference/actions.md](../reference/actions.md) — canonical field reference and template variables table
- [../reference/configuration.md](../reference/configuration.md) — `EFFECTD_*` settings
- [Writing extensions](writing-extensions.md) — building custom action executors
- [../reference/entry-points.md](../reference/entry-points.md) — `ActionExecutor` protocol signature
