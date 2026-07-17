# Quickstart

## Purpose

Your first 10 minutes with firnline — capture a note, see the ingestion
pipeline at work, query your data through GraphQL, browse the WebUI inbox
(experimental), and list available tools. Completing this walkthrough confirms a
working installation.

## Prerequisites

- A running firnline stack per the [Installation guide](installation.md).
- Your `.env` tokens exported as shell variables:

  ```bash
  set -a && source .env && set +a
  ```

## Step 1: capture a note

The capture endpoint accepts both plain text and structured JSON:

**text/plain** (frictionless — shell pipes, quick notes):

```bash
curl -s -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: text/plain" \
  --data-binary "Buy milk on the way home"
```

**application/json** (with kind and optional metadata):

```bash
curl -s -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note", "metadata": {}}'
```

You should get a `201` response with the new document ID:

```json
{"id": "Captured/abc123", "kind": "note"}
```

## Step 2: ingestion (behind the scenes)

`ingestd` polls for new `Captured` documents every 60 seconds (configurable via
`INGESTD_POLL_INTERVAL_SECONDS`). On the next cycle it sends the text to your
LLM with extraction schemas, materializes typed entities (`Task`, `Reminder`,
etc.) in TerminusDB, and flips the Captured status to `processed`. Every
AI-authored entity carries full provenance — see the [Vision](../concepts/vision.md)
for how this works.

Wait 60–90 seconds for the poll cycle, then proceed.

## Step 3: query your data

```bash
curl -s -X POST http://localhost:8080/v1/graphql \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Task { id name done } }"}'
```

The response is a standard GraphQL JSON payload with any `Task` entities
extracted from your note. For the full query surface (document lookup,
entity/class/field search, schema introspection), see the
[API reference](../reference/api.md).

## Step 4: browse the WebUI (experimental)

Open <http://localhost:3000/inbox> in your browser (the WebUI is experimental
in 0.1.0 — bind to loopback, do not expose to untrusted networks). The inbox
shows all `Captured` documents — your note should be visible with its status,
kind, and timestamp.

Other WebUI pages: the dashboard homepage at `/` shows health and module status;
the generic browser at `/browse` lets you explore any document class. For a
full tour, see the [WebUI guide](../guides/webui.md).

## Step 5: list available tools

```bash
curl -s http://localhost:8080/v1/tools \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"
```

This returns the currently registered write tools (empty unless
`QUERYD_ENABLE_WRITES=true`). These tools are surfaced to external AI agents
through the [MCP server](../reference/mcp.md).

## Where to go next

- [Vision](../concepts/vision.md) — why firnline exists and the ADHD-first design
- [Architecture](../concepts/architecture.md) — service topology and data flow
- [WebUI guide](../guides/webui.md) — dashboard features in depth
- [Automations guide](../guides/automations.md) — triggers, effects, and actions

## Related documents

- [Installation](installation.md) — set up the stack
- [API reference](../reference/api.md) — all REST and GraphQL endpoints
- [Configuration reference](../reference/configuration.md) — env var reference
- [Deployment guide](../guides/deployment.md) — production deployment
