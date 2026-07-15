# captured

Capture-ingress daemon. Accepts notes and file uploads via HTTP and dispatches
them to pluggable handler plugins that create documents in TerminusDB.

## Endpoints

- `POST /v1/capture/note` — `{"text": "...", "kind": "note"}` — creates
  documents via a capture handler plugin.
- `POST /v1/capture/file` — multipart file upload — stores via BlobStore,
  then calls the handler.
- `GET /healthz` — health check (no auth).

All capture endpoints require `Authorization: Bearer <CAPTURED_API_TOKEN>`.

## Quickstart

From the monorepo root:

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d                           # all services behind apid on port 8080
curl http://localhost:8080/healthz             # captured via apid (standalone: port 8088)
```

First capture:

```bash
curl -s -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

## Configuration, handlers, and tests

See the [project documentation](../../docs/):

- [Configuration](../../docs/configuration.md) — all `CAPTURED_*` and `FIRNLINE_BLOB_ROOT` env vars
- [Architecture](../../docs/architecture.md) — how captured fits into the system
- [Extensions](../../docs/extensions.md) — writing capture handler plugins

Run tests from the monorepo root:

```bash
uv run pytest services/captured/
```
