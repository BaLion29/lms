# ADR-002: Entry-Point Plugin System

**Status:** Accepted (recorded retroactively)

**Date:** 2026-07-15

## Context

Firnline's extensibility promise states that a third party must be able to add
a complete vertical slice — capture, extraction, storage, query — without
touching kernel code. The system must be modular at every layer: schema,
ingestion, query, capture handling, trigger evaluation, notification delivery,
and action execution.

The extension mechanism must:
- Allow any Python package to contribute capabilities.
- Validate that extensions meet declared requirements (module dependencies,
  class exports) at startup, not at runtime.
- Prevent collisions (two extractors claiming the same proposal kind, two
  handlers claiming the same capture kind).
- Keep the kernel independently verifiable — a kernel-only install must
  compose, codegen, import, and idle gracefully with zero extensions.

## Decision

**Python entry-point groups** (`importlib.metadata.entry_points`) are the
sole extension discovery mechanism. Each extension capability has its own
group:

| Group | Protocol | Host service |
|---|---|---|
| `firnline.schema_modules` | Directory path → manifest + schema | firnline-schema |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd |
| `firnline.queryd.tools` | `ToolPlugin` | queryd |
| `firnline.captured.handlers` | `CaptureHandler` | captured |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd |
| `firnline.indexed.indexers` | `IndexerPlugin` | indexed |
| `firnline.effectd.executors` | `ActionExecutor` | effectd |

All host services boot through the shared `PluginHost` in `firnline-core`:
discover → validate → check_requirements (against `SchemaModule` registry and
`exports`) → collision check → select → log. Each service configures a
`HostPolicy` with per-service stances on failure modes (broken entry points,
zero active plugins, requirement failures, TDB unavailability).

**Kernel purity** is machine-enforced by the **melt test**: a kernel-only
install (no extensions, `--no-entry-points`) must compose the schema, run
codegen, pass `uv run pytest`, and have all modules import cleanly.
Extensions are the seasonal snow — the kernel is what remains when everything
melts.

## Alternatives considered (reconstructed)

| Alternative | Why rejected |
|---|---|
| **Monolith with hardcoded domains** | Violates the extensibility promise. Every new domain requires editing core, which is the bottleneck this project exists to eliminate. Would not pass the melt test conceptually. |
| **Configuration-file plugin registry** | Requires a central registry file that every extension must update. Hard to distribute in pip-installable packages. No natural version/discovery integration with the Python packaging ecosystem. Conflicts harder to detect at install time. |
| **Subprocess plugins (gRPC, sidecar)** | Adds serialization overhead and network hops between plugin and host. Harder to type-check protocol conformance at startup. Would require a separate process lifecycle manager. Overkill for synchronous extraction/tool execution that runs in-process today. |
| **Dynamic classpath scanning** | Implicit discovery (scanning modules for subclasses) is fragile, slow, and makes collisions hard to detect before runtime. Explicit entry-point registration is the Python packaging standard. |

## Consequences

- **Easier:** One `pip install` adds a complete vertical slice. Requirement
  validation catches misconfigured extensions at startup. Collision detection
  prevents silent conflicts. The melt test ensures kernel integrity on every
  release. Third-party extensions follow the same protocols as first-party ones.
- **Harder:** Each new extension capability needs a new entry-point group and
  protocol definition. Plugin authors must understand the entry-point mechanism
  and protocol contracts. Host services must handle degraded behaviour when
  plugins fail requirement checks.
- **Operational:** Extensions are installed via pip into a shared overlay
  volume (Docker) or the host environment. Changing extensions requires a
  service restart. Removing an extension removes its plugins, but existing
  data and schema remain in TerminusDB.

## References

- [Vision](../concepts/vision.md) — Extensibility Promise, melt test
- [Architecture](../concepts/architecture.md) — Plugin Mechanism, HostPolicy table
- [Plugin System](../concepts/plugin-system.md)
- [Extension Development](../development/extension-development.md)
