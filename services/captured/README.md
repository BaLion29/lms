# captured

Capture-ingress daemon. Accepts notes and file uploads via HTTP and dispatches
them to pluggable handler plugins that create documents in TerminusDB.

## Endpoints

- `POST /v1/capture/note` — `{"text": "...", "kind": "note"}`
- `POST /v1/capture/file` — multipart file upload
- `GET /healthz` — health check (no auth)

All capture endpoints require `Authorization: Bearer <CAPTURED_API_TOKEN>`.

## Run tests

```bash
uv run pytest services/captured/
```

## Full documentation

- [captured API reference](../../docs/reference/api/captured.md)
- [Configuration reference](../../docs/reference/configuration.md)
- [Architecture](../../docs/concepts/architecture.md)
