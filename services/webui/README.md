# firnline-webui

Reflex-based web dashboard for firnline. Introspection-driven UI that
auto-discovers schema classes, modules, and service health — any current
or future extension automatically appears without code changes.

Pages: Dashboard, Capture (note + file), Inbox (Captured documents with
status badges and detail drawers), Browse (generic class browser grouped
by SchemaModule), Health (per-service healthz + plugin lists), Modules
(schema module registry + active plugins), Calendar, Automations
(TriggerFiring + ActionExecution listing with status filters), and Login
(optional password gate).

## Run locally

```bash
cd services/webui
uv run reflex run
```

## Full documentation

[Web UI guide](../../docs/guides/web-ui.md)
