# Troubleshooting

Common failure modes and their resolutions, grounded in actual service code and documented behavior.

## LLM Proxy Unreachable (ingestd)

**Symptom:** ingestd container exits immediately with exit code 2 and log message `missing_llm_settings`.

**Likely cause:** `FIRNLINE_LLM_BASE_URL` is empty or not propagated to `INGESTD_LLM_BASE_URL`. ingestd's startup validates that `INGESTD_LLM_BASE_URL`, `INGESTD_LLM_API_KEY`, and `INGESTD_LLM_MODEL` are non-empty; missing any fails with exit code 2 before the main loop starts.

**Fix:** Set `FIRNLINE_LLM_BASE_URL` in `.env`. The compose file maps this to `INGESTD_LLM_BASE_URL`. If your LLM proxy does not require an API key, set `FIRNLINE_LLM_API_KEY` to a dummy value (e.g., `none`) rather than leaving it empty.

**Symptom:** ingestd runs but cycles fail silently; liveness file goes stale.

**Likely cause:** The LLM proxy is reachable at startup but returns errors during extraction calls. ingestd catches cycle-level exceptions in `run_cycle_safe` — it logs `cycle_failed` and continues. The liveness file is only touched on **successful** cycles, so a persistently failing LLM will cause the Docker healthcheck to mark the container unhealthy.

**Fix:** Check ingestd logs for `cycle_failed` events. Verify the LLM proxy is healthy and the model name in `FIRNLINE_LLM_MODEL` matches a model your proxy serves.

## TerminusDB Connection or Auth Failures

**Symptom:** `/healthz` on captured, queryd, or indexed returns `{"status": "degraded", "terminusdb": "down"}`.

**Likely cause:** The TerminusDB instance is unreachable or authentication failed. The `/healthz` handler probes TDB by calling `db_exists()` — if that raises any exception, `terminusdb` is reported as `"down"` and the overall status becomes `"degraded"` (HTTP 503).

**Fix:**
1. Verify TDB is running: `docker compose ps terminusdb` (bundled) or check your external instance.
2. Verify `TDB_URL` and `TDB_PASSWORD` in `.env` are correct.
3. For the bundled overlay, check that `compose.bundled-tdb.yaml` was included in the `docker compose` command.
4. The bundled TDB healthcheck uses a TCP probe on port 6363 — wait for it to become healthy (up to 30 retries × 5s).

**Symptom:** Bootstrap fails at "Ensure database exists" step.

**Likely cause:** The bootstrap container cannot reach TerminusDB. The bootstrap command runs a Python script that creates the database via `TdbClient.create_db()`. If the TDB URL is wrong or unreachable, this step raises an exception and the container exits.

**Fix:** For external TDB, verify `TDB_URL` is reachable from the Docker network (use `host.docker.internal` or the host's Docker network IP). For bundled TDB, ensure `TDB_URL=http://terminusdb:6363` and the `compose.bundled-tdb.yaml` overlay is active.

## Schema Push Rejection

**Symptom:** `firnline-schema apply` fails with HTTP 400 and body containing `api:SchemaCheckFailure`.

**Likely cause:** TerminusDB validates the **full database** against the new schema at push time. If any existing instance document violates the new schema — e.g., a required field was added without a default, or an enum value was removed that is still in use — the push is rejected atomically. No partial schema is committed.

**Fix:**
1. Read the error body carefully — it includes `instance_not_of_class` or `instance_not_cardinality_one` witnesses that identify the violating documents.
2. Either fix the violating documents (update or delete), or adjust the schema change to be backward-compatible (e.g., add a default value for new required fields).
3. Re-run `apply`.

This is described in detail in [../development/terminusdb-notes.md](../development/terminusdb-notes.md#2-validation-timing-when-existing-data-violates-new-schema).

## Bootstrap Failures

**Symptom:** Bootstrap container exits with non-zero code after "Compose schema" step.

**Likely cause:** Schema composition failed. Possible reasons:
- A schema module's `manifest.json` has invalid semver ranges in `depends_on`.
- An exported class is missing `@documentation.comment` (composer L3 lint violation).
- An exported concrete `Entity` subclass is missing `@metadata.label_field` (composer L4).
- A class implementing `Anchored` is missing `@metadata.anchor_field` (composer L5).
- An extension's entry point for `firnline.schema_modules` resolves to a directory without `manifest.json` or `schema.json`.

**Fix:** Check the bootstrap container logs. Compose errors include specific module names and violation details. Fix the schema module source and re-run bootstrap.

**Symptom:** Bootstrap fails at "Apply schema" step.

**Likely cause:** See [Schema Push Rejection](#schema-push-rejection) above.

## Plugin Load Collisions

**Symptom:** A service container fails to start with a `RuntimeError` mentioning "collision" in the logs.

**Likely cause:** Two active plugins registered the same key — e.g., two capture handlers claiming the same `kind`, two ingest sources with the same `(document_type, ready_status)` pair, two extractor plugins declaring the same proposal `kind`, or two executor plugins with the same executor `kind`. All host services boot through the shared `PluginHost`, which performs collision checks after requirement validation. Collisions are **fatal at startup**.

**Fix:**
1. Identify the colliding plugins from the log message (the `PluginHost` logs the collision key).
2. Remove or rename one of the conflicting extensions from `FIRNLINE_EXTENSIONS`.
3. Re-run bootstrap and restart services.

## Missing Auth Tokens (401 Responses)

**Symptom:** `curl http://localhost:8088/v1/capture/note` returns `401 {"detail": "unauthorized"}`.

**Likely cause:** The request is missing the `Authorization: Bearer <token>` header, or the token does not match `CAPTURED_API_TOKEN`. The `_bearer_auth` dependency in captured (and queryd) checks three conditions:
1. Header is present.
2. Header format is `Bearer <token>` (two space-separated parts).
3. Token matches the configured value via constant-time comparison.

All three failures return identical `401 unauthorized` responses (deliberately — no information leakage about which condition failed).

**Fix:**
1. Ensure `.env` has `CAPTURED_API_TOKEN` set and that `curl` includes `-H "Authorization: Bearer $CAPTURED_API_TOKEN"`.
2. Generate a secure token if unset: `openssl rand -hex 32`.

**Symptom:** queryd endpoints return 401.

**Likely cause:** Same as above, but for `QUERYD_API_TOKEN`. Note that queryd's `/healthz` is **unauthenticated** but all `/v1/*` endpoints require the bearer token.

**Symptom:** Container fails to start with compose error `error: CAPTURED_API_TOKEN must be set`.

**Likely cause:** The compose file uses `${CAPTURED_API_TOKEN:?err ...}` expansion, which causes compose to abort if the variable is unset or empty.

**Fix:** Set the variable in `.env` or export it in the shell before running `docker compose`.

## WebUI First-Boot Compile Delay

**Symptom:** WebUI is unreachable at `http://localhost:3000` for up to 60 seconds after starting.

**Likely cause:** This is **normal**. The Reflex-based WebUI compiles the Next.js frontend at container startup, which takes 30–60 seconds on first boot. The compose healthcheck accounts for this with `start_period: 120s` — Docker won't mark the container as unhealthy during this window.

**Fix:** Wait. Subsequent requests after compilation are fast. If the WebUI is still unreachable after 120 seconds, check the container logs for Reflex compilation errors.

## Extension Install Failures in entrypoint.sh

**Symptom:** Bootstrap fails with `pip` error during "installing: <spec>" log line.

**Likely cause:** The extension specifier cannot be installed:
- A wheel filename does not match any file in `/extensions/` inside the image.
- A PyPI package name is misspelled or unavailable.
- A Git URL is unreachable or the repository is private.

The entrypoint script uses `set -eu`, so any `pip install` failure aborts the bootstrap container immediately.

**Fix:**
1. Verify first-party wheel filenames match exactly what is baked into the image (check extension `pyproject.toml` for the wheel name pattern).
2. For PyPI packages, verify the package exists and the version specifier is valid.
3. For Git URLs, ensure the repository is accessible from the Docker network.

**Symptom:** Service container logs show `WARNING: <spec> not found in overlay — extension may be missing`.

**Likely cause:** Service containers run in verify-only mode (`FIRNLINE_EXTENSIONS_INSTALL=false`). They check for each extension's distribution in `/opt/firnline-ext-venv/lib` and warn if not found. This happens when:
- Bootstrap was not re-run after changing `FIRNLINE_EXTENSIONS`.
- The overlay volume was inadvertently recreated.
- The extension's distribution name derived by the script does not match the actual installed directory name (e.g., hyphens vs underscores).

**Fix:** Re-run the bootstrap profile. If the warning persists, verify the extension's actual installed directory name in the overlay volume:
```bash
docker run --rm -v firnline_ext_venv:/data alpine:3.20 ls /data/lib/
```

## Related Documents

- [deployment.md](deployment.md) — service topology and monitoring
- [installing-extensions.md](installing-extensions.md) — extension installation procedure
- [schema-changes.md](schema-changes.md) — schema workflow diagnostics
- [../development/terminusdb-notes.md](../development/terminusdb-notes.md) — TDB API behavior reference
