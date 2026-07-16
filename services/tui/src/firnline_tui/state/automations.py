"""Automations state — introspection-driven trigger firings & action executions view."""
from __future__ import annotations

from dataclasses import dataclass

from firnline_core.uiclients import TdbBrowser, UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class AutomationsData:
    triggers_available: bool = False
    actions_available: bool = False
    firing_rows: tuple[dict, ...] = ()
    execution_rows: tuple[dict, ...] = ()
    firing_statuses: tuple[str, ...] = ()
    execution_statuses: tuple[str, ...] = ()
    error: str = ""


async def load_automations(ctx: AppContext) -> AutomationsData:
    """Fetch schema, compute automations data."""
    tdb = ctx.make_tdb()
    try:
        data = await _load_automations_data(tdb)
    except UiClientError as exc:
        return AutomationsData(error=f"Failed to load schema: {exc.detail}")
    finally:
        await tdb.aclose()

    return AutomationsData(
        triggers_available=data["triggers_available"],
        actions_available=data["actions_available"],
        firing_rows=tuple(data["firing_rows"]),
        execution_rows=tuple(data["execution_rows"]),
        firing_statuses=tuple(sorted(data["firing_statuses"])),
        execution_statuses=tuple(sorted(data["execution_statuses"])),
    )


# ---------------------------------------------------------------------------
# Schema-level helpers
# ---------------------------------------------------------------------------


def concretes_inheriting(schema: list[dict], abstract_id: str) -> list[str]:
    """Return ``@id`` values of concrete (non-abstract, non-subdocument)
    classes whose ``@inherits`` matches *abstract_id*."""
    result: list[str] = []
    for entry in schema:
        if entry.get("@type") != "Class":
            continue
        if entry.get("@abstract") or entry.get("@subdocument"):
            continue
        inherits = entry.get("@inherits", "")
        if isinstance(inherits, str) and inherits == abstract_id:
            result.append(entry["@id"])
    return result


def _iri_tail(iri: str) -> str:
    """Extract the last path segment from an IRI."""
    if not iri:
        return ""
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _subject_display(subject) -> str:
    """Human-readable string for a subject reference."""
    if subject is None:
        return ""
    if isinstance(subject, str):
        return _iri_tail(subject)
    if isinstance(subject, dict):
        return _iri_tail(subject.get("@id", ""))
    return str(subject)


def _resolve_ref(ref_value, *, default: str = "") -> str:
    """Unwrap a TerminusDB document reference to its ``@id`` string."""
    if ref_value is None:
        return default
    if isinstance(ref_value, dict):
        return str(ref_value.get("@id", default))
    return str(ref_value)


def _lookup_name(name_map: dict[str, str], ref: str) -> str:
    """Resolve a trigger/action reference to a display name.

    Tries an exact match first, then suffix match so that full-IRI refs
    (e.g. ``terminusdb:///data/OneShotTrigger/t1``) match map keys that
    are bare class-relative IRIs (e.g. ``OneShotTrigger/t1``).
    """
    if not ref:
        return ""
    if ref in name_map:
        return name_map[ref]
    # Suffix match: check every key to see if ref ends with "/" + key
    for key, name in name_map.items():
        if ref.endswith("/" + key):
            return name
    return _iri_tail(ref)


def _str_or(val, default: str = "") -> str:
    """Stringify *val*, falling back to *default* on None."""
    if val is None:
        return default
    return str(val)


def _int_or(val, default: int = 0) -> int:
    """Coerce *val* to int, falling back to *default* on None."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


async def _load_automations_data(tdb: TdbBrowser) -> dict:
    """Fetch schema, compute automations data, return display dict.

    Returns a dict with keys: ``triggers_available``, ``actions_available``,
    ``firing_rows``, ``execution_rows``, ``firing_statuses``,
    ``execution_statuses``.  Raises ``UiClientError`` on schema failure.
    """
    schema = await tdb.get_schema()

    schema_class_ids = {e.get("@id", "") for e in schema if e.get("@type") == "Class"}
    triggers_available = "TriggerFiring" in schema_class_ids
    actions_available = "ActionExecution" in schema_class_ids

    result: dict = {
        "triggers_available": triggers_available,
        "actions_available": actions_available,
        "firing_rows": [],
        "execution_rows": [],
        "firing_statuses": set(),
        "execution_statuses": set(),
    }

    if not triggers_available and not actions_available:
        return result

    # ------------------------------------------------------------------
    # Build IRI -> name lookups for Trigger / Action subclasses
    # ------------------------------------------------------------------
    trigger_names: dict[str, str] = {}
    action_names: dict[str, str] = {}

    if triggers_available:
        for sc in concretes_inheriting(schema, "Trigger"):
            try:
                docs = await tdb.get_documents(sc)
            except UiClientError:
                continue
            for doc in docs:
                iri = str(doc.get("@id", ""))
                name = str(doc.get("name", ""))
                trigger_names[iri] = name or _iri_tail(iri)

    if actions_available:
        for sc in concretes_inheriting(schema, "Action"):
            try:
                docs = await tdb.get_documents(sc)
            except UiClientError:
                continue
            for doc in docs:
                iri = str(doc.get("@id", ""))
                name = str(doc.get("name", ""))
                action_names[iri] = name or _iri_tail(iri)

    # ------------------------------------------------------------------
    # TriggerFiring rows
    # ------------------------------------------------------------------
    if triggers_available:
        try:
            firings = await tdb.get_documents("TriggerFiring")
        except UiClientError:
            firings = []

        firing_rows: list[dict] = []
        firing_statuses: set[str] = set()
        for doc in firings:
            iri = str(doc.get("@id", ""))
            trigger_ref = _resolve_ref(doc.get("trigger"))
            status = _str_or(doc.get("status"))
            scheduled_for = _str_or(doc.get("scheduled_for"))
            fired_at = _str_or(doc.get("fired_at"))
            subject = _subject_display(doc.get("subject"))
            notification_count = _int_or(doc.get("notification_count"))

            trigger_name = _lookup_name(trigger_names, trigger_ref)

            firing_rows.append(
                {
                    "id": iri,
                    "trigger_name": trigger_name,
                    "status": status,
                    "scheduled_for": scheduled_for,
                    "fired_at": fired_at,
                    "subject": subject,
                    "notification_count": notification_count,
                }
            )
            if status:
                firing_statuses.add(status)

        firing_rows.sort(key=lambda r: r.get("scheduled_for") or "", reverse=True)
        result["firing_rows"] = firing_rows
        result["firing_statuses"] = firing_statuses

    # ------------------------------------------------------------------
    # ActionExecution rows
    # ------------------------------------------------------------------
    if actions_available:
        try:
            executions = await tdb.get_documents("ActionExecution")
        except UiClientError:
            executions = []

        execution_rows: list[dict] = []
        execution_statuses: set[str] = set()
        for doc in executions:
            iri = str(doc.get("@id", ""))
            action_ref = _resolve_ref(doc.get("action"))
            status = _str_or(doc.get("status"))
            attempt = _int_or(doc.get("attempt"))
            executed_at = _str_or(doc.get("executed_at"))
            next_attempt_at = _str_or(doc.get("next_attempt_at"))
            result_detail = _str_or(doc.get("result_detail"))
            approved_by = _str_or(doc.get("approved_by"))

            action_name = _lookup_name(action_names, action_ref)

            execution_rows.append(
                {
                    "id": iri,
                    "action_name": action_name,
                    "status": status,
                    "attempt": attempt,
                    "executed_at": executed_at,
                    "next_attempt_at": next_attempt_at,
                    "result_detail": result_detail,
                    "approved_by": approved_by,
                }
            )
            if status:
                execution_statuses.add(status)

        def _exec_sort_key(r: dict) -> str:
            return r.get("executed_at") or r.get("next_attempt_at") or ""

        execution_rows.sort(key=_exec_sort_key, reverse=True)
        result["execution_rows"] = execution_rows
        result["execution_statuses"] = execution_statuses

    return result
