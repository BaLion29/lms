# Security

The authentication model, trust boundaries, and what is (and isn't) covered.

## Overview

Firnline is a **single-tenant, LAN-oriented** system. Its security model is
service-to-service bearer tokens (for internal APIs) plus an optional password
gate (for the WebUI). There is no multi-user model, no TLS termination, and no
OAuth. The assumption is that firnline runs behind your firewall or on a
trusted network.

## Authentication Model

### Service-to-Service: Bearer Tokens

The following services authenticate requests with per-service bearer tokens,
configured via environment variables:

| Service | Env Variable | Auth behaviour |
|---|---|---|
| **captured** | `CAPTURED_API_TOKEN` | **Required.** All `/v1/capture/*` endpoints require `Authorization: Bearer <token>`. |
| **queryd** | `QUERYD_API_TOKEN` | **Required.** All API endpoints (`/v1/schema`, `/v1/graphql`, `/v1/documents/*`, `/v1/modules`, `/v1/find/*`, `/v1/tools`) require `Authorization: Bearer <token>`. `/healthz` is **unauthenticated**. |
| **indexed** | `INDEXED_API_TOKEN` | **Optional.** When set, all `/v1/find_*` endpoints require `Authorization: Bearer <token>`. When empty, endpoints are open to any caller. |
| **webui** | `WEBUI_CAPTURED_API_TOKEN`, `WEBUI_QUERYD_API_TOKEN`, `WEBUI_INDEXED_API_TOKEN` | **Server-side only.** Tokens for calling upstream services; never exposed to the browser. |
| **mcpd** | `MCPD_QUERYD_TOKEN`, `MCPD_CAPTURED_TOKEN` | **Server-side only.** Tokens for calling queryd and captured; passed via HTTP headers to upstream services. |

**Token generation:** Use `openssl rand -hex 32`. All tokens use
constant-time comparison (`secrets.compare_digest`).

### WebUI Password Gate

The Reflex WebUI in `services/webui/` implements an optional password gate
via `WEBUI_PASSWORD`:

- When empty (default): all pages are open.
- When set: all pages redirect to `/login`. The user enters the shared
  password; on success, an HMAC-SHA256 session cookie (`firnline_webui_session`,
  30-day max age) is set. The cookie is deterministic from the password —
  changing `WEBUI_PASSWORD` invalidates all sessions.

This is a **single shared password** model. Good enough for a LAN gate, not
designed for multi-user environments.

### Services With No Authentication

These services have **no built-in auth** and must remain network-internal:

| Service | Reason |
|---|---|
| **TerminusDB** | Protected by basic auth (`TDB_USER` / `TDB_PASSWORD`), not firnline-specific. HTTP basic auth over the network. |
| **LiteLLM proxy** | External dependency; its auth is configured independently. |
| **ingestd** | Polling worker — no listening port. |
| **triggerd** | Polling worker — no listening port. |
| **effectd** | Polling worker — no listening port. |
| **mcpd** | No inbound auth. Exposes firnline to external AI agents via MCP streamable HTTP. **This is an open door to your data** — see trust boundaries below. |

## Trust Boundaries

### External AI Agents via mcpd

**mcpd has no inbound authentication.** Anyone who can reach `mcpd:8090` can
query your firnline database, read documents, and (if `QUERYD_ENABLE_WRITES=true`)
write via `create_document`. mcpd is designed to be consumed by external AI
agents (Claude Desktop, Continue, etc.). **Do not expose mcpd to untrusted
networks.** Keep it behind a firewall, on `localhost`, or gated by a reverse
proxy with auth.

Writes made through mcpd are attributed with `X-Firnline-Agent: ext:mcp` so
they are distinguishable in the provenance chain from internal service writes
(`service:ingestd`, `service:queryd`).

### LLM Proxy (LiteLLM)

**All captured content flows through the LLM.** Text from `Captured`
documents is sent to the configured LLM model via LiteLLM for extraction,
entity linking, and embedding. If you use a cloud provider (OpenAI, Anthropic,
etc.), the content of your captures leaves your network. Use a local model
(via Ollama, vLLM, etc.) if this is a concern.

### Database Layer

TerminusDB access is controlled by HTTP basic auth (`TDB_USER` /
`TDB_PASSWORD`). All services share the same credentials. There is no
per-service or per-module database-level access control.

## What Is NOT Covered

This is an honest assessment of the current system's security scope:

- **No TLS termination.** All HTTP traffic is plaintext. Use a reverse proxy
  (nginx, Caddy) with TLS for production exposure.
- **No multi-user model.** One shared password for the WebUI. One set of
  database credentials for all services. No concept of users, roles, or
  per-user data ownership.
- **Single-tenant assumption.** The system is designed for one person's life
  data. There is no isolation between "tenants" because there is no concept of
  tenancy.
- **No audit logging beyond the commit graph.** The TerminusDB commit graph
  records who changed what and when (author + message), but there is no
  dedicated access-log or intrusion-detection system.
- **No network-layer encryption for service-to-service communication.**
  Services communicate over plain HTTP within the compose network.
- **mcpd has no inbound auth.** See trust boundaries above.
- **No secret rotation mechanism.** Tokens are static environment variables.
  Changing them requires restarting services.

## Secret Handling Guidance

- Store secrets in `.env` (at the repo root). **`.env` is in `.gitignore` —
  do not commit it.**
- Use `.env.example` as a template — it documents every variable with
  placeholder values.
- Generate unique tokens per deployment with `openssl rand -hex 32`.
- The compose stack injects environment variables from `.env` automatically.
  Service images never embed secrets.
- `Action.params` in the database holds logical parameters only — credentials
  always come from environment variables read at call time by executor plugins.

## Related documents

- [Configuration reference](../reference/configuration.md) — all env variables
- [Architecture](architecture.md) — service topology and data flow
- [Deployment guide](../guides/deployment.md) — running behind a reverse proxy
