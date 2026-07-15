# FAQ

## 1. Do I need my own LLM API key? How does the LiteLLM proxy work?

You need access to an OpenAI-compatible LLM endpoint, but firnline does not
ship one. The recommended setup is a [LiteLLM](https://github.com/BerriAI/litellm)
proxy that you run separately — it sits between firnline and your chosen
model provider (OpenAI, Anthropic, local Ollama, etc.). Set
`FIRNLINE_LLM_BASE_URL` to your proxy's address and optionally
`FIRNLINE_LLM_API_KEY` if it requires authentication. See
[Installation](getting-started/installation.md) and
[Architecture](concepts/architecture.md) for the full picture.

## 2. Can I use Postgres instead of TerminusDB?

No. TerminusDB v12.0.6 is the single source of truth and the sole
integration point between all services. The system relies on TerminusDB's
graph/document model, schema-enforced writes, commit-graph audit trail,
and branching for schema changes — none of which Postgres provides. See
[ADR-001](decisions/ADR-001-terminusdb-as-source-of-truth.md) for the
rationale and alternatives considered.

## 3. Is this multi-user?

Not currently. The WebUI has an optional single shared password gate — no
per-user accounts, roles, or data isolation. The agent naming grammar
reserves `user:<name>` for future attribution, but the v0.1.0-alpha system
is single-user by design. Multi-user support is a
[long-term idea](roadmap.md).

## 4. Why is the WebUI slow on first boot?

The WebUI is built with [Reflex](https://reflex.dev/), which compiles a
Next.js frontend at container startup. This takes 30–60 seconds on first
boot. The healthcheck uses a generous `start_period: 120s` to accommodate
this. Subsequent requests are fast — only the initial compile is slow. See
[WebUI](guides/web-ui.md).

## 5. How do I add my own document types?

Write an **extension**: one pip-installable Python package containing a
schema module (class/enum definitions), optionally an extractor plugin
(LLM extraction logic), and optionally a queryd tool plugin (write
endpoints). Register entry points in `pyproject.toml` and add the package
to `FIRNLINE_EXTENSIONS`. After re-bootstrap and restart, your new types
appear in the schema, ingestd extracts them, and the WebUI auto-discovers
them. See [Installing Extensions](guides/installing-extensions.md) and
[Extension Development](development/extension-development.md).

## 6. Does my data leave my machine?

It depends on your setup. Captured text is sent to the LiteLLM proxy (for
LLM extraction by ingestd) and to the embedding model (for indexed's
search index). If your proxy routes to a cloud provider (OpenAI, Anthropic),
that provider sees the captured content. If your proxy routes to a local
model (Ollama), data stays on your machine. Action webhooks (via effectd)
send template-rendered payloads to external URLs you configure. Firnline
itself stores everything in TerminusDB — that data stays in your Docker
volume.

## 7. What happens if the LLM proxy is down?

Ingestd and indexed will log errors and skip their poll cycles. Captured
documents remain in `status=new` or `status=transcribed` until the proxy
comes back — no data is lost. The default poll interval is 60 seconds, so
a transient outage causes a delay, not a failure. Other services (captured,
queryd, triggerd, effectd's non-LLM path) are unaffected.

## 8. How do I back up?

Stop the TerminusDB container, tar the storage volume, restart. The full
procedure — including restore and post-restore verification — is documented
in [Backup and Restore](guides/backup-and-restore.md). Always back up
before running schema changes.

## 9. What's the difference between triggerd and effectd?

**triggerd** evaluates `Trigger` documents (schedules, one-shot, relative
offsets) against the current time and materializes `TriggerFiring` records.
It answers "should something happen now?" **effectd** picks up those
`TriggerFiring` records, plans `ActionExecution` documents, and runs the
actual side effects (notifications, webhooks) through executor plugins.
Think of triggerd as the alarm clock and effectd as the person who acts
on it. See [Architecture](concepts/architecture.md).

## 10. What's the melt test?

The melt test is a machine-enforced kernel-purity check: it runs a
kernel-only compose (zero extensions, `--no-entry-points`), generates
code, verifies that kernel modules import cleanly, and runs the test
suite. If the kernel can't stand alone, extensions have leaked into it.
It's wired into the release validation script. See
[ADR-002](decisions/ADR-002-entry-point-plugin-system.md) and the
[Vision](concepts/vision.md) extensibility promise.

## 11. Why are datetimes stored in UTC but displayed in Europe/Zurich?

UTC is the unambiguous storage format — no DST surprises, no offset
ambiguity, and consistent comparison across services. Display in
`Europe/Zurich` is the author's local timezone and is configurable:
timezone is injected at runtime, never hardcoded. See
[Architecture](concepts/architecture.md) conventions.

## 12. Can I run firnline without Docker?

Yes, for local development. Install Python ≥ 3.12 and uv, run `uv sync`,
then start each service with its environment variables pointing at an
external TerminusDB instance. The [Quickstart](getting-started/quickstart.md)
includes local-development commands. Production deployment uses Docker
Compose.

## 13. How do I use firnline with an external AI agent (Claude, ChatGPT)?

Run **mcpd** — it exposes firnline as an MCP (Model Context Protocol)
server on port 8090. Your AI agent connects to it and gets tools for
GraphQL queries, document lookup, entity/class/field search, schema
introspection, and note capture. mcpd is a stateless HTTP facade over
queryd and captured — no direct database access. See
[mcpd API](reference/api/mcpd.md).

## 14. What happens if I remove an extension?

Removing an extension from `FIRNLINE_EXTENSIONS` stops its plugins from
loading after restart. However, its **schema module and any documents
already written to TerminusDB remain**. Removing a schema module is a
breaking (`MAJOR`) change that requires an explicit `firnline-schema`
operation and may fail if existing documents reference the removed classes.
See [Installing Extensions](guides/installing-extensions.md) and
[Schema Changes](guides/schema-changes.md).

## 15. How do I approve a pending action?

Actions with `mode=approval` (the default) are planned as
`ActionExecution` with `status=pending_approval`. You approve by flipping
the status to `pending` via the TerminusDB document API, queryd's write
tools (if enabled), or directly. Effectd never performs this transition —
it's the explicit human-in-the-loop gate. See
[Actions and Trust](concepts/actions-and-trust.md) for the full lifecycle.
