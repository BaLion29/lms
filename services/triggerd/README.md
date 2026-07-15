# triggerd

Polling daemon that evaluates Trigger documents and materializes
TriggerFiring records into TerminusDB. Runs a cycle every
`TRIGGERD_POLL_INTERVAL_SECONDS` (default 60s).

**Per cycle:**

1. Discovers concrete (non-abstract) Trigger subclasses from the live schema.
2. Fetches all Trigger documents, filtering by enabled/validity window.
3. Dispatches each Trigger to an evaluator plugin discovered via the
   `firnline.triggerd.evaluators` entry-point group.
4. Evaluators compute occurrences within a lookback window
   (`TRIGGERD_LOOKBACK_SECONDS`, default 900s).
5. Resolves the parent Triggerable subject (e.g. a Reminder or Routine).
6. Writes idempotent TriggerFiring documents keyed lexically by
   `occurrence_key`.

**Flags:** `--once` (single cycle and exit), `--dry-run` (evaluate,
no writes). Tracks per-branch last-seen commits in a state file so
restarts don't re-scan.

## Further reading

- [Architecture](../../docs/concepts/architecture.md)
- [Configuration](../../docs/reference/configuration.md)
- [Entry Points](../../docs/reference/entry-points.md)
