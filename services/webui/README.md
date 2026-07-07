# firnline-webui

Reflex-based web UI for the Firnline personal data system.

Browses TerminusDB schemas and documents, inspects capture/indexed/queryd
services, and provides a lightweight password gate.

## Packaging layout

The package lives under `src/firnline_webui/` (hatchling src layout).
`uv run` installs the package in dev mode, making `import firnline_webui`
work from the project root (`services/webui/`). Reflex discovers the app
via the `app_name` in `rxconfig.py` which maps to
`firnline_webui.firnline_webui:app`.

## Backend health endpoint

A `GET /healthz` endpoint is added via the `api_transformer` parameter
of `rx.App`. It returns `{"status": "ok", "version": "<pkg version>"}`.
Reflex also serves its built-in `/ping` for basic liveness checks.

## Run locally

```bash
cd services/webui
uv run reflex run
```

## Pages

| Route       | Page      | Status      |
|-------------|-----------|-------------|
| `/`         | Dashboard | Active      |
| `/capture`  | Capture   | Placeholder |
| `/inbox`    | Inbox     | Placeholder |
| `/browse`   | Browse    | Placeholder |
| `/health`   | Health    | Active      |
| `/modules`  | Modules   | Active      |
