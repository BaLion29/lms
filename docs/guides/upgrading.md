# Upgrading

General procedure for upgrading a firnline deployment to a new version, plus a catalog of breaking changes by version.

## Prerequisites

- A current backup of the TerminusDB volume (see [backup-and-restore.md](backup-and-restore.md)).
- Access to the Docker host and the `.env` file.
- The target version's release notes from [CHANGELOG.md](../../CHANGELOG.md).

## General Upgrade Procedure

1. **Back up the database.**
   ```bash
   # Follow the volume snapshot procedure in backup-and-restore.md
   ```

2. **Pull new images and update code.**
   ```bash
   git pull
   docker compose pull
   ```

   For the bundled-TDB overlay:
   ```bash
   docker compose -f compose.yaml -f compose.bundled-tdb.yaml pull
   ```

3. **Re-run bootstrap.** This applies any new or changed schema modules, runs pending data migrations, and reinstalls extensions:
   ```bash
   docker compose --profile bootstrap up bootstrap --abort-on-container-exit
   ```

   For bundled TDB:
   ```bash
   docker compose -f compose.yaml -f compose.bundled-tdb.yaml \
     --profile bootstrap up bootstrap --abort-on-container-exit
   ```

4. **Run schema workflow if schema changed.** If the release notes indicate schema module changes (new modules, version bumps, breaking changes), follow the full schema workflow on a branch:
   ```bash
   firnline-schema diff ...    # classify changes
   firnline-schema plan ...    # dry-run
   firnline-schema apply --branch schema-bootstrap ...
   firnline-schema validate --branch schema-bootstrap ...
   firnline-schema promote --branch schema-bootstrap ...
   ```
   See [schema-changes.md](schema-changes.md) for the full workflow.

5. **Restart services.**
   ```bash
   docker compose up -d
   ```

6. **Verify.** Check `/healthz` endpoints and liveness files:
   ```bash
   curl http://localhost:8087/healthz
   curl http://localhost:8088/healthz
   curl http://localhost:8089/healthz
   docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
   docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
   docker compose exec effectd find /tmp/effectd-alive -mmin -5
   ```

## Breaking Changes by Version

### Unreleased (post-0.1.0)

#### notifyd → effectd Rename

- **What changed:** The `notifyd` service has been renamed to `effectd`. The environment variable prefix changed from `NOTIFYD_` to `EFFECTD_`. The liveness file changed to `/tmp/effectd-alive`. The compose service block, image name, and all references use the new name.
- **What you must do:** Update any custom `NOTIFYD_*` environment variables in `.env` to `EFFECTD_*`. If you use the provided `.env.example` as a base, re-copy and re-populate secrets. The old prefix is fully removed — settings with the old prefix will be silently ignored.

#### `firnline.notifyd.channels` Entry-Point Deprecation

- **What changed:** The `firnline.notifyd.channels` entry-point group (used by notification channel plugins like Gotify) is deprecated in favor of `firnline.effectd.executors`. Legacy channels are auto-adapted at effectd startup via `ChannelExecutorAdapter` with executor kind `notify:<name>`, so existing channel plugins continue to work.
- **What you must do:** No immediate action required — legacy channels still function. However, the legacy group will be removed after one release cycle. Migrate channel plugins to the new `firnline.effectd.executors` entry-point group. For the Gotify extension, a native executor (kind `notify:gotify`) is now provided alongside the legacy channel.
- **EFFECTD_LEGACY_NOTIFICATION_LOOP** still defaults to `true` for backward compatibility with the nag policy (renotify/expire/snooze).

#### Remindable Removal

- **What changed:** The `Remindable` marker class has been removed from the core schema. Extensions that previously relied on `Remindable` must use `Triggerable` (from the triggers module) for trigger-owning semantics, or define their own markers.
- **What you must do:** If you have data in TerminusDB that references `Remindable`, update extensions to use `Triggerable` or custom markers. There is no automated migration for existing documents referencing `Remindable` — see CHANGELOG.

#### Provenance Restructure

- **What changed:** `Entity.provenance` is now **required** (exactly one — the birth certificate with fields `agent`, `at`, `method`, `confidence`). The `Provenance.source` field is removed. Multi-source derivation now lives in `Entity.derived_from: Set<Source>` (n-ary). The agent naming grammar is reserved: `service:<name>`, `user:<name>`, `ext:<name>`.
- **What you must do:** Any documents created before this change that used the old `Provenance.source` field will need manual review. The schema push will fail if existing documents violate the new cardinality (one required `provenance`, no `source` field). No automated migration is documented — see CHANGELOG for details.

#### Capture Module Replacing Inbox

- **What changed:** The old `InboxNote`/`InboxAudio` classes are replaced by a single `Captured(Entity, Source)` class with fields: `content_type`, `content`, `blob_sha256`, `file_name`, `captured_at`, `transcription`, `status` (new/transcribed/processed/failed/archived). Capture is now a kernel schema module (`schema/modules/capture/`). The webui inbox page is backed by `Captured`.
- **What you must do:** Old `InboxNote`/`InboxAudio` documents remain in TerminusDB but are no longer part of the active schema. No automated migration is documented — see CHANGELOG.

#### `firnline-ext-time-management` Merges Planning + Routines

- **What changed:** The `firnline-ext-planning` and `firnline-ext-routines` extensions are combined into a single `time_management` schema module. The old extensions are removed. `firnline-schema` now supports extension migration discovery.
- **What you must do:** Replace references to the old extensions in `FIRNLINE_EXTENSIONS` with the new `firnline_ext_time_management` specifier. The module now exports 9 classes (Task, TaskSpec, Event, TaskStatus, EventStatus, Routine, RoutineStep, Activity, ActivitySpec) with three entry points (schema_modules, ingestd.extractors, queryd.tools).

#### Anchor Field Metadata

- **What changed:** `Anchored` is now a pure role marker — it no longer carries the `anchor_at` field. Concrete classes implementing `Anchored` must declare `@metadata.anchor_field` naming an `xsd:dateTime` field at the class level. The composer validates this at L5. If the anchor field is unset on a document, relative triggers are dormant (evaluators skip them).
- **What you must do:** Update any extension schema modules that implement `Anchored` to include `@metadata.anchor_field`. Re-compose and re-apply the schema.

### 0.1.0 → Unreleased Additional Notes

- **`@metadata.label_field`** is now required on every exported concrete `Entity` subclass (composer L4 validation). Extensions must add this metadata to their schema modules.
- **`@documentation.comment`** is required on every exported class/enum (composer L3 validation) — "the schema is a prompt."
- The **SchemaModule registry** now carries an `exports` field (class @ids written at install). Plugins may declare `requires_classes` in addition to `requires`, checked against registry exports at startup.
- All services now boot through the shared **PluginHost** with declarative `HostPolicy` — per-service collision and requirement checks may surface previously hidden plugin incompatibilities.

## Related Documents

- [backup-and-restore.md](backup-and-restore.md) — pre-upgrade backup procedure
- [schema-changes.md](schema-changes.md) — the compose → promote workflow
- [deployment.md](deployment.md) — service topology and monitoring
- [../../CHANGELOG.md](../../CHANGELOG.md) — full changelog
