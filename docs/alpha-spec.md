# lms alpha — kernel extraction & extension platform: build instructions

You are turning the existing `lms/` uv-workspace monorepo into a **domain-free
kernel** plus a set of **reference extensions**, and releasing it as
`0.1.0-alpha` — the first version on which extensions (first-party and
third-party) can be built without touching kernel code.

Existing material you must read first: the ingestd spec, the queryd spec, the
modularization spec (schema modules / lms-schema / plugins), all existing code,
GOAL.md and ARCHITECTURE.md. This document **supersedes the module cut** in the
modularization spec (§1 there) and **extends its plugin mechanism**; everything
else in that spec (composer/differ/apply/codegen mechanics, semver policy,
migration tracking, VERIFY discipline) remains binding.

There is LIVE DATA in the production TerminusDB. The re-cut in §4 must be
reachable as a registry-level migration (§10) — the composed schema stays
byte-equivalent; only module *grouping* changes.

Read this whole document before writing code.

---

## 1. Why this re-cut (the forcing function)

The current cut treats planning (Task/Event/Reminder) as quasi-core. That is
wrong: **planning is just the first extension.** The kernel must be shaped by
the full space of things that will be bolted on. Requirements below are derived
from this catalog — when in doubt about a kernel decision, test it against
these rows:

| Planned extension | Shape | What it demands from the kernel |
| --- | --- | --- |
| Mail (IMAP/JMAP) | module (`Email` as Source) + intake connector + extractor | pluggable **ingest sources** (not just extractors); attachment/blob convention; ExternalRef (message-id, folder) |
| Documents (Paperless-ngx, NAS) | module (`Document`) + connector | **ExternalRef** convention (system + external id + URL + version/etag); blob convention; read-side tools |
| Finances (accounts, transactions) | module + import connectors (CSV/FinTS) + tools | nothing special — proves modules handle high-volume, non-remindable data; decimal handling in codegen |
| CLI / TUI | client | stable service APIs + **lms-core as the Python SDK**; capture endpoint |
| Custom webhooks (inbound) | capture handlers | generic **capture service** with pluggable handlers |
| Custom webhooks (outbound) / automations | consumer service | **change-feed convention** (poll commit graph / EventTrigger) — define the extension point, do not build |
| Markdown vault (.md files) | intake connector (watched dir → notes) | capture service + file handling |
| Spaced repetition / Anki | module (`Fact`/`Card`) + extractor + exporter | proves extractor plugins for a non-planning domain; outbound export needs no kernel support |
| Inventory | module (`Item`, lent_to → Person, stored_at → Location) | cross-module references (`people`, `places` exports) — Location must NOT be buried inside `people` |
| CalDAV / CardDAV sync | connector service (bidirectional) | ExternalRef with etag/sync-token + conflict-policy convention; per-document provenance of sync writes |
| Reminders / notifications (`reminderd`) | module (`Reminder`, status lifecycle) + service | `Remindable` marker + `Trigger` family available to ALL modules |
| Health / training log (tours, sessions) | module + extractor ("heute 4h Skitour") | nothing new — catalog validation row |
| Journal / mood tracking | module + extractor | same |
| Habits | module (thin layer over routines/triggers) | routines + triggers as ordinary extensions |
| Media / library (books etc.) | the existing example module | already the acceptance test |
| Bookmarks / read-later | module + capture handler (share-sheet URL) | capture handlers again |
| Recipes / meal planning | module + extractor | catalog validation row |
| Time tracking (TimeLog) | module + tools | catalog validation row |
| Semantic search | service + queryd tool plugin | queryd tool slot (already marked) |
| Matrix bot capture | connector (bot → capture endpoint) | capture endpoint with token auth |
| Vikunja import | one-shot connector script | lms-core SDK sufficiency |
| Stats / Grafana | none — scrape | **Prometheus metrics on every service** (alpha requirement, §11) |

Derived kernel requirements (referenced throughout as R-…):

- **R-MOD** — schema modules with dependency/export discipline, discoverable
  from installed packages, not only from the repo tree.
- **R-SRC** — ingestd polls *pluggable sources*, not hardcoded inbox types.
- **R-EXT** — extractor plugins (exists; unchanged).
- **R-TOOL** — queryd tool plugins (exists; unchanged).
- **R-CAP** — a generic capture service with pluggable handlers.
- **R-REF** — a core `ExternalRef` subdocument convention for anything synced
  from/into an external system.
- **R-BLOB** — a managed file-storage convention (path layout, hashing,
  env-configured root) usable by any module with binary payloads.
- **R-FEED** — a documented change-feed extension point (deferred build).
- **R-SDK** — lms-core is the official Python SDK for clients and connectors.
- **R-OPS** — health, metrics, structured logs on every service.
- **R-CONTRIB** — a contributor can go from zero to working extension using
  only shipped docs + template.

## 2. What "alpha" means (definition, not vibes)

`0.1.0-alpha` is released when:

1. The **kernel is domain-free**: no Task, Event, Person, or Inbox class in
   core; ingestd and queryd start (uselessly but cleanly) with zero extensions
   installed.
2. The **reference extensions** (§7) restore today's full behavior — inbox
   capture → extraction → planning documents → conversational query — while
   being packaged *exactly* like a third party would package theirs.
3. A stranger can build a new extension end-to-end using `EXTENDING.md` + the
   module template, without reading kernel source.
4. The live database has been migrated to the new registry layout without data
   loss (§10).

## 3. Kernel vs extension — the cut

**IN the kernel** (mechanics only):

- `packages/lms-schema` — the schema toolchain (compose/diff/plan/apply/
  validate/promote/codegen), per the modularization spec, plus module
  discovery from entry points (§5.1).
- `packages/lms-core` — TerminusDB client, shared settings, plugin protocols,
  conventions (ExternalRef, blob store, time), generated models, capture
  client helpers. **No domain logic, no repositories, no business rules** —
  extensions own their logic inside their plugins.
- `services/ingestd` — a generic poll→extract→insert host (R-SRC + R-EXT).
- `services/queryd` — a generic conversational host (R-TOOL).
- `services/captured` — a minimal generic intake API (R-CAP).
- schema module `core` — abstracts + registry + conventions, nothing else (§4).

**OUT of the kernel** (extensions, even when first-party):

`inbox`, `planning`, `people`, `places`, `triggers`, `reminders`, `routines`,
and everything in the catalog above. First-party extensions live in
`extensions/` in the monorepo but are installable packages with the same
packaging convention as third-party ones — **dogfooding is mandatory**; if a
reference extension needs a kernel hook that the packaging convention doesn't
provide, the convention is wrong and must be fixed, not bypassed.

## 4. Schema module re-cut

New module layout (composed output must remain equivalent to the current
schema — prove with the existing equivalence test, updated):

| Module | Classes | depends_on | Notes |
| --- | --- | --- | --- |
| `core` 2.0.0 | @context · `Source` · `Context` · `Remindable` (all contentless markers) · `SchemaModule` · `SchemaMigration` · `ExternalRef` (@subdocument, NEW) | — | Markers stay in core because they are the cross-module composition glue: any module may make its classes traceable/taggable/remindable without depending on a domain module. |
| `triggers` 1.0.0 | `Trigger` (abstract) + Schedule/Relative/Context/Event/Composite triggers + `CompositeMode`, `EventKind` | core | Content-bearing abstract moves OUT of core. |
| `inbox` 1.0.0 | `InboxNote`, `InboxAudio` + status enums | core | |
| `places` 1.0.0 | `Location` | core | Split out of `people` — inventory, events, geofencing all need Location without needing Person. |
| `people` 1.1.0 | `Person`, `Contact` | places | `Contact.domicile → Location`. |
| `planning` 2.0.0 | `Task`, `TaskSpec`, `Event` + `TaskStatus`, `EventStatus` | places | Loses `Reminder` (→ MAJOR). `Event.location → Location`. |
| `reminders` 1.0.0 | `Reminder` | triggers | `refers_to → Remindable` (core marker), `trigger → Trigger`. Future home of ReminderStatus + nag fields when reminderd lands. |
| `routines` 1.1.0 | `Routine`, `RoutineStep`, `Activity`, `ActivitySpec` | planning, triggers | Uses exported `TaskSpec` and `Trigger`. |

`ExternalRef` (R-REF), new in core:

```json
{
  "@id": "ExternalRef",
  "@type": "Class",
  "@subdocument": [],
  "@key": {"@type": "Random"},
  "system": "xsd:string",
  "external_id": "xsd:string",
  "url": {"@class": "xsd:string", "@type": "Optional"},
  "version": {"@class": "xsd:string", "@type": "Optional"},
  "last_synced_at": {"@class": "xsd:dateTime", "@type": "Optional"}
}
```

(`version` carries etags/sync-tokens/uids as opaque strings. VERIFY the
combination of `@subdocument` + Random key against the instance, as done for
`Contact`.) A document convention, not a base class: any module adds
`external_refs: Set<ExternalRef>` where needed. Document in EXTENDING.md:
`system` values are lowercase namespaced strings (`caldav`, `paperless`,
`vikunja`).

**Design-law amendments** (update ARCHITECTURE.md in the same change):

- L1 (revised): `core` owns the `@context`, the registry classes, and the
  contentless universal markers. Other modules MAY define abstract classes;
  referencing them across modules follows the normal exports rule (L2).
- L7 (new): first-party extensions use only public kernel contracts —
  entry points, protocols, lms-core public API. CI enforces that
  `extensions/**` never imports from service internals.

## 5. Kernel changes in detail

### 5.1 lms-schema: module discovery from packages (R-MOD)

`compose` currently reads `schema/modules/*`. Add a second source: installed
packages exposing entry point group **`lms.schema_modules`**, each resolving
(via `importlib.resources`) to a directory containing `manifest.json` +
`schema.json` (+ `migrations/`). Repo-tree modules and package modules are
merged; a duplicate module name across sources is a hard error. The lock file
records the source (`repo:` / `pkg:<dist-name>==<version>`) per module.
This makes "pip install an extension" sufficient for `compose` to see its
schema — no manual directory drops.

### 5.2 lms-core: what it is and is not

Contents (`src/lms_core/`):

- `tdb.py` — unchanged surface (get/insert/replace/graphql, typed `TdbError`
  preserving raw bodies). This plus `models` **is the SDK** (R-SDK): document
  in the README that connectors and CLIs build on lms-core, never on raw
  HTTP or on service internals.
- `settings.py` — shared `TDB_*` base.
- `plugins.py` — protocols (§6) + `ModuleRequirement` + `check_requirements`.
- `conventions.py` (NEW) — `utc_now()`, ISO serialization helpers, the blob
  store (R-BLOB): `BlobStore(root)` with `put(stream, suggested_name) ->
  BlobRef(path, sha256, size, mime)` writing to
  `{LMS_BLOB_ROOT}/{yyyy}/{mm}/{sha256[:2]}/{sha256}{ext}`, dedup by hash.
  Root from env `LMS_BLOB_ROOT`; services that need it mount the same volume.
- `generated/` — codegen output, now one file per module in the NEW cut.

Explicitly NOT in lms-core: repositories per entity, status-transition
helpers for specific domains, extraction prompts, anything importing a
concrete domain model by name. If a helper mentions `Task`, it belongs in the
planning extension.

### 5.3 ingestd: generic sources (R-SRC) — the main kernel refactor

New protocol in `lms_core.plugins`:

```python
class IngestSourcePlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    document_type: str                  # e.g. "InboxNote"
    ready_status: str                   # e.g. "new" — value of the doc's status enum
    done_status: str                    # e.g. "processed"
    failed_status: str                  # e.g. "failed"
    def text(self, doc: dict) -> str:   # extraction input from the raw document
        ...
    def reference_time(self, doc: dict) -> datetime:
        """Anchor for resolving relative dates (created_at / recorded_at)."""
```

Pipeline changes: the poll set is built from active source plugins instead of
the hardcoded `InboxNote@new + InboxAudio@transcribed` pair; everything
downstream (idempotency guard on `derived_from`, extraction, linking,
one-commit-per-item, error-feedback retries, status flip via the plugin's
`done/failed_status`) is UNCHANGED and stays in the kernel. Entry point group:
**`lms.ingestd.sources`**. The note/audio sources move verbatim into the
`inbox` extension (§7). Startup collision checks: duplicate
`(document_type, ready_status)` pairs are fatal.

Existing pipeline tests must pass with sources injected as fixtures.

### 5.4 queryd: no structural change

R-TOOL already exists. Two additions: (a) the schema briefing already appends
installed modules — also append the active plugin list; (b) `/healthz` gains
`blob_root_writable` when `LMS_BLOB_ROOT` is set. Everything else unchanged.

### 5.5 captured: generic intake (R-CAP)

New minimal FastAPI service (same stack/standards as queryd):

- `POST /v1/capture/note` `{text, captured_at?}` → creates the target document
  via a **capture handler**.
- `POST /v1/capture/file` multipart → BlobStore.put → handler.
- `GET /healthz`.
- Bearer token (`CAPTURED_API_TOKEN`), constant-time compare; per-request
  structured log with resulting document IRI.

Handlers are plugins (group **`lms.captured.handlers`**):

```python
class CaptureHandler(Protocol):
    name: str                     # route discriminator: /v1/capture/{name} for customs
    requires: list[ModuleRequirement]
    kinds: list[str]              # "note", "file", or custom
    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        """Create the appropriate document(s); return the primary IRI.
        ctx provides tdb, blob store, now()."""
```

The `inbox` extension ships the two default handlers (note → `InboxNote@new`,
audio file → blob + `InboxAudio@new`). captured with zero handlers installed
starts, serves `/healthz`, and returns 404 + a helpful body on capture routes.
This one service covers webhooks-inbound, markdown-vault watchers, Matrix
bots, share-sheets, and phone shortcuts — they are all just clients or
handlers of captured. (The existing n8n voice pipeline keeps working
unchanged; migrating it to captured is post-alpha.)

### 5.6 Change feed (R-FEED) — document only

Add `docs/CHANGE_FEED.md`: outbound automations (webhooks-out, cache
invalidation, reminder re-evaluation) will consume the TerminusDB commit
graph (poll `_commits` since a stored cursor; VERIFY the commit-log API shape
before writing the doc) and/or future `EventTrigger` evaluation. Name the
future service (`eventd`), define what it will guarantee (at-least-once,
per-commit granularity, author/message available), and explicitly defer it.
No code in alpha.

## 6. Packaging convention for extensions (R-CONTRIB)

One extension = one installable Python distribution containing any subset of:

```toml
[project.entry-points."lms.schema_modules"]
planning = "lms_ext_planning:schema_module_path"

[project.entry-points."lms.ingestd.sources"]
inbox_note = "lms_ext_inbox.sources:NoteSource"

[project.entry-points."lms.ingestd.extractors"]
planning_people = "lms_ext_planning.extract:PlanningExtractor"

[project.entry-points."lms.queryd.tools"]
planning_write = "lms_ext_planning.tools:PlanningTools"

[project.entry-points."lms.captured.handlers"]
inbox = "lms_ext_inbox.capture:InboxHandlers"
```

Uniform startup behavior in all three services (existing rule, now universal):
discover → `check_requirements` against the registry → skip-with-WARNING on
unmet requirements → `--strict-plugins` makes skips fatal → log the active
set at INFO. Name/kind collisions are fatal at startup.

Deliverables for contributors:

- **`EXTENDING.md`** — the tutorial: anatomy of an extension, the five entry
  point groups, module manifest + semver rules, ExternalRef/BlobStore/status
  conventions, testing recipes (respx + TestModel), release checklist.
- **`templates/lms-extension-template/`** — a copier template generating a
  working skeleton (module + one source or extractor + one tool + passing
  tests). `copier copy templates/lms-extension-template my-ext && uv run
  pytest` must pass out of the box.
- **License + CONTRIBUTING.md** — the kernel is intended for outside
  contributors; add a license file (operator chooses the license — propose
  AGPL-3.0-only for services + Apache-2.0 or MIT for lms-core/lms-schema so
  proprietary extensions remain possible; get explicit confirmation in the
  session before committing a license) and minimal contribution guidelines
  (conventional commits, ruff, tests required, no network in tests).

## 7. Reference extensions (restore current behavior)

Create `extensions/` in the workspace; each is a full package per §6:

1. **`lms-ext-inbox`** — schema module `inbox`; source plugins for
   `InboxNote@new` and `InboxAudio@transcribed` (moved verbatim from ingestd);
   captured handlers for note + audio file.
2. **`lms-ext-places`** — schema module `places` only.
3. **`lms-ext-people`** — schema module `people`; contributes its
   linking-context lines via the existing extractor-plugin hook.
4. **`lms-ext-planning`** — schema module `planning`; the existing
   Task/Event/Person extractor moved verbatim (kind literals unchanged);
   existing write tools moved verbatim.
5. **`lms-ext-reminders`** — schema modules `reminders` + `triggers`
   (two modules, one package is fine); ReminderProposal extraction +
   `create_reminder` tool move here from planning's plugin.
6. **`lms-ext-routines`** — schema module `routines` only (no plugins yet).

Behavior-identity requirement: existing extraction and queryd tests pass with
at most import-path changes after the moves. The `examples/lms-module-library`
package is retained, updated to the new packaging convention, and stays the
end-to-end acceptance test.

## 8. Non-goals for alpha (do NOT build)

- reminderd, eventd, syncd (CalDAV/CardDAV), semantic search, transcriberd.
- Any catalog extension beyond the reference set — the catalog is a test
  fixture for kernel decisions, not a work list.
- Auto-accept, review tooling, multi-user, frontend changes.
- Migrating the n8n capture pipeline onto captured.

## 9. Alpha versioning & release

- Kernel packages (`lms-core`, `lms-schema`) and services: version
  `0.1.0a1`, tagged `v0.1.0-alpha.1`. Kernel API stability promise starts at
  0.2: until then, protocol changes are allowed but must be CHANGELOG'd.
- Schema modules version independently per §4 (semver enforced by the differ,
  as before).
- `CHANGELOG.md` entries per production-touching step; a release section
  listing every public contract (entry point groups, protocols, env vars,
  HTTP endpoints) — this section *is* the alpha API surface.

## 10. Migration path for the live system (ordered, each step shippable)

1. Kernel refactors in dev: lms-schema entry-point discovery; lms-core
   conventions module; ingestd source-plugin refactor; captured skeleton.
   All existing tests green.
2. Module re-cut in dev: new fragments per §4; equivalence test proves
   composed output ≡ current composed schema (grouping-only change);
   codegen regenerates into per-module files; golden tests green.
3. Reference extensions extracted (§7); both services run with extensions
   installed; behavior-identity test suites green; template + EXTENDING.md
   written and template-tested.
4. **Production re-cut**: backup first (existing documented restore path).
   `apply` on a production branch — composed schema is unchanged, so this is
   a **registry-only** migration: SchemaModule docs rewritten to the new
   module names/versions, applied-migration records preserved/re-homed.
   VERIFY that `apply` correctly detects schema no-op and touches only
   registry documents; if the checksum model forces a schema push, confirm
   it validates cleanly against existing data on a branch before promote.
   Explicit operator confirmation required before this step.
5. Deploy captured (new service, additive); reference extensions deployed as
   installed packages; smoke: capture note via captured → ingestd extracts →
   queryd answers.
6. Tag `v0.1.0-alpha.1`.

## 11. Cross-cutting alpha requirements (R-OPS)

- **Metrics**: every service exposes `GET /metrics` (Prometheus,
  `prometheus-client`): per-service basics plus ingestd counters
  (documents processed/failed by source, LLM retries, extraction latency
  histogram), queryd (requests, tool calls by name, iteration-cap hits,
  latency), captured (captures by handler, blob bytes). For ingestd, run a
  tiny aiohttp/uvicorn sidecar thread or serve metrics from the same loop —
  keep it dumb.
- **Health**: `/healthz` on all three services reporting TerminusDB
  reachability, installed modules, active plugins (+ blob root where used).
- **Logging**: structlog; every capture/pipeline transition logs doc IRI +
  from/to status; every skipped plugin logs the unmet requirement.
- **Tests**: workspace `uv run pytest` with no network; new coverage minimum:
  source-plugin dispatch, (document_type, ready_status) collision, captured
  auth + handler routing + blob dedup, entry-point module discovery incl.
  duplicate-name error, registry-only migration dry-run, template generation.
- **CI checks**: ruff, codegen freshness, L7 import boundary
  (extensions/** must not import service internals), template smoke test.

## 12. Definition of done

- [ ] Kernel is domain-free: grep proves no domain class name in
      packages/ or services/ outside generated models and tests' fixtures.
- [ ] Both agent services + captured start cleanly with zero extensions
      installed and report empty plugin sets.
- [ ] With reference extensions installed: full current behavior reproduced;
      pre-existing test suites green with import-path-only changes.
- [ ] Composed schema equivalence (old cut vs new cut) test-proven;
      live DB migrated registry-only per §10 step 4 (after confirmation).
- [ ] `examples/lms-module-library` passes end-to-end under the new
      packaging (install → compose sees it via entry point → apply →
      codegen → ingest book note → query book).
- [ ] A fresh extension generated from the template compiles, tests green,
      and its module is discovered by `compose`.
- [ ] ExternalRef + BlobStore + change-feed conventions documented;
      EXTENDING.md complete; license + CONTRIBUTING.md committed
      (license confirmed by operator).
- [ ] `/metrics` + `/healthz` on all services; Grafana-scrapeable.
- [ ] Tagged `v0.1.0-alpha.1` with the API-surface CHANGELOG section.

Work order: §10 steps 1→6, conventional commit per stage, operator
confirmation gates before step 4 (production) and before committing a license.
