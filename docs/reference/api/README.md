# API Overview

Firnline's services expose HTTP APIs for capture, query, grounding, and
external-agent access. This page catalogs all service APIs.

## Service summary

| Service | Port | Auth | Role |
|---|---|---|---|
| [captured](captured.md) | 8088 | Bearer (`CAPTURED_API_TOKEN`) | Ingestion API — note capture, file upload, dispatch to handler plugins |
| [queryd](queryd.md) | 8087 | Bearer (`QUERYD_API_TOKEN`) | GraphQL read proxy, document lookup, semantic search, schema introspection, write-tool endpoints |
| [indexed](indexed.md) | 8089 | Bearer (`INDEXED_API_TOKEN`, optional) | Precision grounding — semantic entity/class/field search via hybrid vector+lexical index |
| [mcpd](mcpd.md) | 8090 | MCP (streamable HTTP), proxies tokens downstream | MCP server wrapping queryd + captured for external AI agents |
| webui | 3000 | Password gate (`WEBUI_PASSWORD`) | Browser UI (Reflex-based) |

## Internal-only services

The following services have no HTTP API. They are polling workers that
operate exclusively through the TerminusDB database:

| Service | Role |
|---|---|
| **ingestd** | Polls captured documents, runs LLM extractors, writes typed documents |
| **triggerd** | Evaluates Trigger documents, materializes TriggerFiring records |
| **effectd** | Delivers effects via channel/executor plugins; legacy notification loop |

## Auth model

All service APIs (except `webui` and `mcpd`'s MCP transport) use **bearer
token** authentication. Tokens are configured via environment variables
(`CAPTURED_API_TOKEN`, `QUERYD_API_TOKEN`, `INDEXED_API_TOKEN`).

`mcpd` uses MCP's native streamable HTTP transport and forwards tokens to
backend services.

`/healthz` endpoints on all services are **unauthenticated**.

## Base paths

All versioned API endpoints live under `/v1/`. The `/healthz` endpoint and
any root-level MCP mounts are unversioned.

## Related documents

- [Configuration reference](../configuration.md)
- [captured API](captured.md)
- [queryd API](queryd.md)
- [indexed API](indexed.md)
- [mcpd API](mcpd.md)
