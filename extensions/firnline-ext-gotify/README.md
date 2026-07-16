# firnline-ext-gotify

`ActionExecutor` that dispatches `NotifyAction` documents to a Gotify push
notification server.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GOTIFY_URL` | (empty) | Gotify server base URL (**required**) |
| `GOTIFY_TOKEN` | (empty) | Gotify app token, sent as `X-Gotify-Key` header (**required**) |
| `GOTIFY_PRIORITY` | `5` | Message priority (0–10) |
| `GOTIFY_TIMEOUT_SECONDS` | `10.0` | HTTP request timeout in seconds |

## Action document fields

- `title_template` — `string.Template` with variables `$subject_label`,
  `$firing_id`, `$action_name`, `$idempotency_key`, etc. When absent, the
  title is derived from the subject (`name` → `title` → `@type` → `@id`
  → `"Firnline reminder"`).
- `body_template` — `string.Template` with the same variables. When absent,
  the body is derived from the firing (`scheduled_for`, `occurrence_key`).

Every request carries an `X-Gotify-Key` header for authentication and an
`X-Firnline-Idempotency-Key` header for downstream deduplication. The
response JSON `id` field is captured as `external_ref`.

## HTTP result mapping

| Status | Result |
|---|---|
| 2xx | `ok=True`, `external_ref` = response JSON `id` if present |
| 4xx | `ok=False`, `retryable=False` |
| 5xx, timeout, connect error | `ok=False`, `retryable=True` |
