# Installing Extensions

How to install and manage firnline extensions in a Docker Compose deployment. This page is for operators deploying extensions — not for developing new ones (see [../development/extension-development.md](../development/extension-development.md)).

## Prerequisites

- A working firnline Docker Compose deployment with the `firnline_ext_venv` volume.
- Extension specifiers ready (wheel filenames, PyPI names, or Git URLs).

## Configuration

Extensions are controlled by two environment variables in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `FIRNLINE_EXTENSIONS` | (empty) | Comma-separated list of extension specifiers |
| `FIRNLINE_EXTENSIONS_PURGE` | `false` | Set `true` to wipe the overlay before reinstalling |

### Specifier Formats

| Format | Example | Notes |
|---|---|---|
| PyPI name | `firnline_ext_people>=0.1.0` | Version specifiers optional |
| Git URL | `git+https://github.com/user/firnline-ext-foo.git` | Cloned and installed from source |
| Wheel filename | `firnline_ext_people-0.1.0-py3-none-any.whl` | Resolved against `/extensions/` inside the image |

First-party extension wheels are **baked into service images at build time** — no host-side `dist/` directory is needed. Third-party extensions must be available at their specified source (PyPI, Git, or a wheel reachable in the image).

## How It Works

The `docker/entrypoint.sh` script manages extensions via a shared Docker volume (`firnline_ext_venv`):

1. The **bootstrap** container mounts the volume **read-write** and runs `pip install --target /opt/firnline-ext-venv/lib` for each specifier in `FIRNLINE_EXTENSIONS`. The `--no-deps` flag is used because extension dependencies (firnline-core, structlog, etc.) are already present in the main `/app/.venv`, and `firnline-core` is a workspace-local package not available on PyPI.
2. Service containers mount the same volume **read-only** and verify extension presence at startup. They set `PYTHONPATH=/opt/firnline-ext-venv/lib` so `importlib.metadata` discovers entry points from the installed distributions.

## Adding or Changing Extensions

1. Edit `FIRNLINE_EXTENSIONS` in `.env`:
   ```
   FIRNLINE_EXTENSIONS=firnline_ext_time_management-0.1.0a1-py3-none-any.whl,firnline_ext_gotify-0.1.0a1-py3-none-any.whl
   ```

2. Re-run the bootstrap profile. This reinstalls extensions into the overlay volume and applies any new schema modules:
   ```bash
   docker compose --profile bootstrap up bootstrap --abort-on-container-exit
   ```

3. Restart services that consume extensions:
   ```bash
   docker compose restart captured ingestd queryd triggerd effectd indexed
   ```

### Removing Extensions

1. Remove the specifier from `FIRNLINE_EXTENSIONS`.
2. Set `FIRNLINE_EXTENSIONS_PURGE=true` in `.env`.
3. Run bootstrap to wipe and reinstall:
   ```bash
   docker compose --profile bootstrap up bootstrap --abort-on-container-exit
   ```
4. Set `FIRNLINE_EXTENSIONS_PURGE=false` again.
5. Restart services.

> **Important:** Removing an extension from `FIRNLINE_EXTENSIONS` stops its plugins from loading, but its **schema module and any documents already written remain in TerminusDB**. Removing schema is a breaking change — it requires an explicit `firnline-schema` operation.

## Verifying Extensions Loaded

### Via the Web UI

Visit the **Modules** page at `/modules` in the web UI. It lists all `SchemaModule` registry documents (name, version, description, exports, dependencies) plus active plugins per service fetched from each service's `/healthz` endpoint.

### Via the API

```bash
# List installed schema modules
curl -s -H "Authorization: Bearer $QUERYD_TOKEN" \
  http://localhost:8087/v1/modules
```

Returns an array of `SchemaModule` documents. Each entry shows the module `name`, `version`, `exports` (class @ids), and `depends_on`.

### Via healthz

Each service's `/healthz` endpoint reports active plugins. For example, `captured` reports capture handlers, `queryd` reports query tools:

```bash
curl -s http://localhost:8088/healthz | python3 -m json.tool
# Look for "handlers" and "modules" fields
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bootstrap fails with `pip` error | Wheel not found in `/extensions/` | Verify the wheel filename matches exactly; first-party wheels are baked into the image at build time |
| Extension not listed in `/v1/modules` | Schema module was not composed | Check that the extension registered `firnline.schema_modules` correctly in its entry points |
| Extension listed but plugins missing | Plugin requirement check failed | Check service logs for `plugin_requirement_failed` events — the module version or `requires_classes` may not match the registry |
| Duplicate extension after purge | `FIRNLINE_EXTENSIONS_PURGE` not set back to `false` | Set it to `false` after the purge bootstrap run |

## Related Documents

- [../development/extension-development.md](../development/extension-development.md) — how to author new extensions (developer-focused)
- [schema-changes.md](schema-changes.md) — applying schema changes from extensions
- [deployment.md](deployment.md) — volume layout and service topology
- [troubleshooting.md](troubleshooting.md) — common failure modes
