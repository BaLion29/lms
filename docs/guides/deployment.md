# Deployment

Production deployment guide for the firnline Docker Compose stack.

## Prerequisites

- Docker and Docker Compose v2 (≥2.24 for `!override` tag support in the bundled-TDB overlay).
- An **external LiteLLM proxy** (or any OpenAI-compatible endpoint) at a URL reachable from the Docker host — the stack does **not** run an LLM server.
- For the external-TDB mode: a running **TerminusDB v12.0.6** instance.
- `.env` file populated from `.env.example`.

## Compose Modes

### External TerminusDB (default)

The base `compose.yaml` expects an **existing** TerminusDB instance reachable at `TDB_URL`:

```bash
# Set TDB_URL to your instance in .env
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d
```

### Bundled TerminusDB (self-contained)

Layering `compose.bundled-tdb.yaml` adds a `terminusdb` container (`terminusdb/terminusdb-server:v12.0.6`), a `terminusdb_data` volume, healthcheck dependency wiring, and a hardcoded `TDB_URL=http://terminusdb:6363` in the bootstrap command:

```bash
# Set TDB_URL=http://terminusdb:6363 and TDB_PASSWORD in .env
docker compose -f compose.yaml -f compose.bundled-tdb.yaml \
  --profile bootstrap up bootstrap --abort-on-container-exit

docker compose -f compose.yaml -f compose.bundled-tdb.yaml up -d
```

## Docker Volumes

| Volume | Mount | Purpose |
|---|---|---|
| `firnline_ext_venv` | RW (bootstrap), RO (services) | Extension overlay — wheels installed by `docker/entrypoint.sh` |
| `blobs` | RW (captured) | Content-addressed blob storage for file uploads |
| `firnline_index` | RW (indexed) | SQLite hybrid vector+lexical index (`/var/lib/firnline/index`) |
| `terminusdb_data` | RW (terminusdb) | TerminusDB storage (only with bundled-TDB overlay) |

## Bootstrap One-Shot Profile

The `bootstrap` service (profile `bootstrap`) is a **one-shot** container that:

1. Creates the TerminusDB database if it does not exist (via `TdbClient.create_db()`).
2. Runs `firnline-schema compose` — assembles all schema modules (core + installed extensions) into `build/composed.schema.json` and `build/modules.lock.json`.
3. Runs `firnline-schema apply` — pushes the composed schema to TerminusDB (idempotent).
4. Runs `firnline-schema validate` — runs GraphQL smoke tests and verifies the registry matches the lock file.
5. The `docker/entrypoint.sh` script installs extensions (from `FIRNLINE_EXTENSIONS`) into the `firnline_ext_venv` overlay volume.

Re-run bootstrap whenever extensions change or the schema needs updating. It is **idempotent**: running it multiple times is safe.

## Service Topology & Ports

| Service | Port | Exposed to host | Auth model |
|---|---|---|---|
| `terminusdb` (bundled) | 6363 | `TDB_HOST_PORT` (default 6363) | Basic auth (`TDB_PASSWORD`) |
| `captured` | 8088 | `CAPTURED_HOST_PORT` (default 8088) | Bearer token (`CAPTURED_API_TOKEN`) |
| `queryd` | 8087 | `QUERYD_HOST_PORT` (default 8087) | Bearer token (`QUERYD_API_TOKEN`) |
| `indexed` | 8089 | `INDEXED_HOST_PORT` (default 8089) | Optional bearer (`INDEXED_API_TOKEN`) |
| `mcpd` | 8090 | `MCPD_HOST_PORT` (default 8090) | Proxies tokens to queryd/captured |
| `webui` | 3000 | `WEBUI_HOST_PORT` (default 3000) | Optional password gate (`WEBUI_PASSWORD`) |
| `ingestd` | — | none | Internal only |
| `triggerd` | — | none | Internal only |
| `effectd` | — | none | Internal only |

## Reverse-Proxy Considerations

The following ports carry authentication and should **never** be exposed publicly without a reverse proxy that enforces TLS:

- **TerminusDB (6363)** — basic auth over plain HTTP. Always keep internal unless behind a TLS-terminating proxy.
- **captured (8088)** — bearer token auth. Expose only if you need external capture clients.
- **queryd (8087)** — bearer token auth. Expose if external AI agents need direct access.

Services intended **only for internal traffic** and never exposed:

- **ingestd, triggerd, effectd** — polling workers with no listening ports. They communicate only with TerminusDB.
- **indexed (8089)** — consumed by ingestd/queryd internally; no need to expose.

The **webui (3000)** is the intended public surface. It proxies tokens server-side (tokens are never sent to the browser) and offers an optional password gate via `WEBUI_PASSWORD`. For LAN deployments, set `WEBUI_PASSWORD` to empty (default) and control access at the network layer.

`mcpd` (8090) should only be exposed to trusted AI agent clients since it holds bearer tokens for both queryd and captured.

## Monitoring

### `/healthz` endpoints (HTTP services)

| Service | Endpoint | Returns |
|---|---|---|
| `captured` | `GET http://localhost:8088/healthz` | `200` (ok) or `503` (degraded). Fields: `status`, `terminusdb`, `version`, `modules`, `handlers`, `blob_root_writable` |
| `queryd` | `GET http://localhost:8087/healthz` | `200` with status, version, TDB connectivity, active plugins |
| `indexed` | `GET http://localhost:8089/healthz` | `200` with status, version, store/poller health |
| `webui` | `GET http://localhost:3000/healthz` | `200` |
| `mcpd` | `GET http://localhost:8090/healthz` | `200` |

All `/healthz` endpoints are **unauthenticated**.

### Liveness files (polling workers)

Polling workers have no HTTP ports; they touch a liveness file on each successful cycle:

| Service | Liveness file | Check |
|---|---|---|
| `ingestd` | `/tmp/ingestd-alive` | `find /tmp/ingestd-alive -mmin -5` |
| `triggerd` | `/tmp/triggerd-alive` | `find /tmp/triggerd-alive -mmin -5` |
| `effectd` | `/tmp/effectd-alive` | `find /tmp/effectd-alive -mmin -5` |

If the file is missing or older than 5 minutes, the service is unhealthy. The liveness file is **only** touched on successful cycles — a failing daemon eventually becomes unhealthy.

The compose file configures Docker healthchecks that use exactly these commands (with `grep -q .` to ensure an actual match). For example:

```bash
docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
docker compose exec effectd find /tmp/effectd-alive -mmin -5
```

### Post-change verification

After schema changes:

```bash
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
curl http://localhost:8089/healthz   # indexed
```

Then confirm polling workers are alive via their liveness files.

## Related Documents

- [backup-and-restore.md](backup-and-restore.md) — volume snapshot and restore procedures
- [upgrading.md](upgrading.md) — upgrade workflow and breaking changes
- [../concepts/security.md](../concepts/security.md) — auth model and token management
