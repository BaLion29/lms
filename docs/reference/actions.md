# Actions reference

## Purpose

This page is the canonical field reference for `Action`, `WebhookAction`, and
`NotifyAction` — types, defaults, constraints, and the secrets rule. For the
action model, trust ladder, and execution lifecycle, see
[concepts/actions.md](../concepts/actions.md).

## Action field reference

`Action` is an abstract `Entity` subclass. Concrete subclasses define exactly
how the effect is produced.

| Class | Field | Type | Required | Default | Description |
|---|---|---|---|---|---|
| **Action** (abstract) | `name` | `xsd:string` | yes | — | Human-readable label |
| | `enabled` | `xsd:boolean` | yes | — | Boolean gate; disabled actions are skipped by the planner |
| | `trigger` | `Trigger` | yes | — | Trigger IRI — which trigger causes this action to fire |
| | `executor` | `xsd:string` | yes | — | Executor-kind string matched against executor plugin `kinds` (e.g. `"webhook"`, `"notify:gotify"`) |
| | `mode` | `ActionMode` | yes | — | Trust-ladder value (`dry_run`, `approval`, `auto`) |
| | `max_attempts` | `xsd:integer` | no | `EFFECTD_DEFAULT_MAX_ATTEMPTS` (3) | Override for `EFFECTD_DEFAULT_MAX_ATTEMPTS` |
| | `retry_backoff` | `xsd:duration` | no | `PT1M` | ISO-8601 duration, doubled per attempt |
| | `timeout` | `xsd:duration` | no | `PT30S` | ISO-8601 duration cap per attempt |
| | `params` | `xsd:string` | no | — | Generic JSON string bag for logical configuration. **Secrets never live here** — the database holds logical parameters; credentials come from executor-local env vars. |
| **WebhookAction** | `url` | `xsd:string` | yes | — | HTTP endpoint |
| | `http_method` | `xsd:string` | no | `POST` | HTTP method |
| | `payload_template` | `xsd:string` | no | — | `string.Template` over firing/subject/action variables. If absent, `default_webhook_payload` is sent as a canonical JSON body. |
| **NotifyAction** | `title_template` | `xsd:string` | no | — | `string.Template` for the notification title |
| | `body_template` | `xsd:string` | no | — | `string.Template` for the notification body |

### Secrets rule

**No secrets in the database.** `Action.params` holds logical configuration
(JSON string convention); credentials (`WEBHOOK_DEFAULT_TOKEN`, `GOTIFY_TOKEN`,
etc.) are read from environment variables by the executor plugin at call time.

## Template variables

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

## Related documents

- [Actions concept](../concepts/actions.md) — action model, trust ladder, execution lifecycle
- [Automations guide](../guides/automations.md) — worked example: Home Assistant lights via WebhookAction
- [Configuration reference](./configuration.md) — `EFFECTD_*` settings
