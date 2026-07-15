# firnline-webui

Reflex-based web dashboard for the Firnline personal data system. Provides a
browser UI for capturing thoughts, browsing TerminusDB documents by class,
inspecting service health, viewing pipeline history, and managing automations.

Pages all use real Reflex state classes that call the TerminusDB API via
`CapturedClient` and `TdbBrowser`:

| Route               | Page        |
|---------------------|-------------|
| `/`                 | Dashboard   |
| `/capture`          | Capture     |
| `/inbox`            | Inbox       |
| `/browse`           | Browse      |
| `/browse/[class]`   | Class View  |
| `/health`           | Health      |
| `/modules`          | Modules     |
| `/history`          | History     |
| `/calendar`         | Calendar    |
| `/automations`      | Automations |
| `/login`            | Sign In     |

## Run locally

```bash
cd services/webui
uv run reflex run
```

## Further reading

- [WebUI guide](../../docs/guides/webui.md) — full walkthrough
- [Configuration](../../docs/reference/configuration.md) — env vars
