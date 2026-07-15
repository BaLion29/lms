# Quickstart

A 5-minute walkthrough after [installation](installation.md). You'll capture a note, let the AI ingestion pipeline process it, and query the result.

## Capture a note

Call the captured service with your bearer token:

```bash
curl -s -X POST http://localhost:8088/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

Returns `201` with:

```json
{"id": "<captured-id>", "kind": "note"}
```

The captured document is stored in TerminusDB as a `Captured` instance and queued for ingestion.

## Watch ingestd process it

ingestd polls for unprocessed captured items on its next cycle (default: every 60 seconds). It sends the text to the LLM for extraction, then writes structured typed documents (tasks, events, reminders, etc.) to TerminusDB.

To observe the pipeline in action, tail the logs:

```bash
docker compose logs -f ingestd
```

Log messages show extraction results, schema validation, and document creation. After a successful cycle, ingestd touches `/tmp/ingestd-alive` for its healthcheck.

> **Tip:** speed up your first test by setting `INGESTD_POLL_INTERVAL_SECONDS=10` in `.env`, then restart: `docker compose restart ingestd`.

## First query

Once documents are written, query through queryd's GraphQL endpoint:

```bash
curl -s -X POST http://localhost:8087/v1/graphql \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Task { id name done } }"}'
```

Returns a standard GraphQL JSON payload with all Task documents. The query is branch-scoped — queryd queries the `TDB_BRANCH` you configured (default `main`).

## Explore the WebUI

Open <http://localhost:3000> in your browser. The WebUI dashboard shows per-service health and quick-capture. The Inbox page lists `Captured` documents with status badges and detail drawers. Browse documents by schema class, inspect the SchemaModule registry, and monitor per-service health — all driven by runtime introspection.

If you set `WEBUI_PASSWORD` in `.env`, the login gate redirects unauthenticated visitors to `/login`. See the [WebUI guide](../guides/web-ui.md) for full coverage.

## Next steps

- [Querying guide](../guides/querying.md) — GraphQL queries, structured REST endpoints, cursors, write tools
- [WebUI guide](../guides/web-ui.md) — dashboard, inbox, browse, health, modules, auth
- [Vision](../concepts/vision.md) — entity model, design decisions, ADHD principles
- [Architecture](../concepts/architecture.md) — component model and data flow
