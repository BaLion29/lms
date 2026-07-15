# ADR-005: LLM Access via LiteLLM Proxy

**Status:** Accepted (recorded retroactively)

**Date:** 2026-07-15

## Context

Firnline's AI layer — ingestd (entity extraction from captured text),
indexed (embedding generation for hybrid search), and any future
LLM-consuming service — needs a model-access strategy. The project must
avoid vendor lock-in, support swapping models without code changes, and
keep the operational surface small. The LLM access layer must be
OpenAI-compatible to leverage the broadest ecosystem of models and
providers.

## Decision

**All LLM and embedding calls go through an external LiteLLM proxy.**
The proxy is NOT part of the firnline Docker Compose stack — it runs as a
separate, operator-managed service. Every firnline service that needs
LLM access points at the proxy via two environment variables:

- `FIRNLINE_LLM_BASE_URL` — the proxy's base URL (default
  `http://host.docker.internal:4000`).
- `FIRNLINE_LLM_API_KEY` — optional API key if the proxy requires one.
- `FIRNLINE_LLM_MODEL` — the model name to request (default `gpt-4.1-mini`).

The proxy presents an OpenAI-compatible `/v1/chat/completions` and
`/v1/embeddings` interface. Firnline code only knows about this interface —
it never imports provider-specific SDKs or handles provider-specific
authentication flows.

Model selection is configuration, not code: change `FIRNLINE_LLM_MODEL`
(and ensure the proxy routes it) to swap from GPT-4.1-mini to Claude,
Mistral, or a local model.

## Alternatives considered (reconstructed)

| Alternative | Why rejected |
|---|---|
| **Direct provider SDKs (OpenAI, Anthropic, …)** | Each provider requires its own SDK dependency, authentication flow, and error handling. Adding or switching providers requires code changes. Vendor lock-in path of least resistance. |
| **Embedded local models (llama.cpp, Ollama served locally)** | Lower quality for extraction and linking tasks at current local-model capability levels. Resource-intensive (GPU RAM, inference latency). Would need to be packaged in the compose stack. However, the LiteLLM proxy can front a local Ollama instance — so this alternative is *reachable* through the proxy without being *mandated* by firnline. |
| **Multiple direct API clients with a common abstraction layer** | Reimplements what LiteLLM already provides: unified interface, model routing, cost tracking, rate limiting, fallback chains. Maintaining a homegrown abstraction would be a distraction from the core system. |

## Consequences

- **Easier:** Model-agnostic — swap providers by reconfiguring the proxy.
  Single code path for all LLM calls. The proxy handles rate limiting,
  retries, and fallback routing if configured. Local models are reachable
  by pointing the proxy at Ollama or vLLM.
- **Harder:** The proxy is an external dependency — if it's down, all LLM
  features (ingestion, indexing) stall. The operator must deploy and maintain
  an additional service. Content sent to the proxy is visible to the
  configured backend provider (e.g., OpenAI) unless the proxy routes to a
  local model.
- **Operational:** The `FIRNLINE_LLM_BASE_URL` default points at
  `host.docker.internal`, which works on Docker Desktop but requires
  explicit configuration on Linux hosts. All services that consume LLM
  (ingestd, indexed) respect a 60-second poll cycle, so a transient proxy
  outage causes a delay, not data loss.

## References

- [Vision](../concepts/vision.md) — Technology Foundation table
- [Architecture](../concepts/architecture.md) — System Overview (external LiteLLM proxy note)
- [Configuration](../reference/configuration.md) — LLM settings
