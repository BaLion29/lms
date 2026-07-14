# firnline-ext-webhook

Reference `ActionExecutor` that dispatches `WebhookAction` documents to any
HTTP endpoint. Intended as the canonical example for creating new effectd
executor extensions.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_DEFAULT_TOKEN` | (empty) | Optional bearer token sent as `Authorization: Bearer <token>` |
| `WEBHOOK_TIMEOUT_SECONDS` | `10.0` | HTTP request timeout in seconds |

## Action document fields

- `url` — HTTP endpoint (**required**).
- `http_method` — HTTP method (default `POST`), uppercased.
- `payload_template` — `string.Template` with variables `$firing_id`,
  `$subject_label`, `$action_name`, `$idempotency_key`, etc. When absent,
  the canonical `default_webhook_payload` JSON body is sent.

Every request carries an `X-Firnline-Idempotency-Key` header for downstream
deduplication. The `Location` response header is captured as `external_ref`.

## HTTP result mapping

| Status | Result |
|---|---|
| 2xx | `ok=True`, `external_ref` = `Location` header if present |
| 4xx | `ok=False`, `retryable=False` |
| 5xx, timeout, connection error | `ok=False`, `retryable=True` |
