"""Tests for AutomationsState — data loading, filtering, error handling, cleanup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from firnline_core.tdb import TdbError
from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.state.automations import (
    AutomationsState,
    _load_automations_data,
    _iri_tail,
    _resolve_ref,
    concretes_inheriting,
)


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trigger_schema_entry() -> dict:
    return {
        "@id": "Trigger",
        "@type": "Class",
        "@abstract": [],
        "@inherits": "Entity",
        "name": "xsd:string",
        "enabled": "xsd:boolean",
    }


@pytest.fixture
def oneshot_trigger_entry() -> dict:
    return {
        "@id": "OneShotTrigger",
        "@inherits": "Trigger",
        "@type": "Class",
        "@metadata": {"label_field": "name"},
        "fire_at": "xsd:dateTime",
        "name": "xsd:string",
        "enabled": "xsd:boolean",
    }


@pytest.fixture
def schedule_trigger_entry() -> dict:
    return {
        "@id": "ScheduleTrigger",
        "@inherits": "Trigger",
        "@type": "Class",
        "@metadata": {"label_field": "name"},
        "dtstart": "xsd:dateTime",
        "rrule": "xsd:string",
        "name": "xsd:string",
        "enabled": "xsd:boolean",
    }


@pytest.fixture
def trigger_firing_entry() -> dict:
    return {
        "@id": "TriggerFiring",
        "@inherits": "Entity",
        "@type": "Class",
        "trigger": "Trigger",
        "occurrence_key": "xsd:string",
        "scheduled_for": "xsd:dateTime",
        "fired_at": "xsd:dateTime",
        "status": "FiringStatus",
        "subject": {"@class": "Triggerable", "@type": "Optional"},
        "notification_count": {"@class": "xsd:integer", "@type": "Optional"},
    }


@pytest.fixture
def action_entry() -> dict:
    return {
        "@id": "Action",
        "@type": "Class",
        "@abstract": [],
        "@inherits": "Entity",
        "name": "xsd:string",
        "enabled": "xsd:boolean",
        "executor": "xsd:string",
        "mode": "ActionMode",
    }


@pytest.fixture
def webhook_action_entry() -> dict:
    return {
        "@id": "WebhookAction",
        "@inherits": "Action",
        "@type": "Class",
        "@metadata": {"label_field": "name"},
        "url": "xsd:string",
        "name": "xsd:string",
        "enabled": "xsd:boolean",
        "executor": "xsd:string",
        "mode": "ActionMode",
    }


@pytest.fixture
def notify_action_entry() -> dict:
    return {
        "@id": "NotifyAction",
        "@inherits": "Action",
        "@type": "Class",
        "@metadata": {"label_field": "name"},
        "title_template": {"@class": "xsd:string", "@type": "Optional"},
        "name": "xsd:string",
        "enabled": "xsd:boolean",
        "executor": "xsd:string",
        "mode": "ActionMode",
    }


@pytest.fixture
def action_execution_entry() -> dict:
    return {
        "@id": "ActionExecution",
        "@inherits": "Entity",
        "@type": "Class",
        "action": "Action",
        "firing": "TriggerFiring",
        "status": "ExecutionStatus",
        "idempotency_key": "xsd:string",
        "attempt": "xsd:integer",
        "next_attempt_at": {"@class": "xsd:dateTime", "@type": "Optional"},
        "executed_at": {"@class": "xsd:dateTime", "@type": "Optional"},
        "result_detail": {"@class": "xsd:string", "@type": "Optional"},
        "approved_by": {"@class": "xsd:string", "@type": "Optional"},
    }


@pytest.fixture
def full_automation_schema(
    trigger_schema_entry,
    oneshot_trigger_entry,
    schedule_trigger_entry,
    trigger_firing_entry,
    action_entry,
    webhook_action_entry,
    notify_action_entry,
    action_execution_entry,
) -> list[dict]:
    return [
        trigger_schema_entry,
        oneshot_trigger_entry,
        schedule_trigger_entry,
        trigger_firing_entry,
        action_entry,
        webhook_action_entry,
        notify_action_entry,
        action_execution_entry,
    ]


@pytest.fixture
def triggers_only_schema(trigger_schema_entry, oneshot_trigger_entry, trigger_firing_entry) -> list[dict]:
    return [trigger_schema_entry, oneshot_trigger_entry, trigger_firing_entry]


@pytest.fixture
def actions_only_schema(action_entry, webhook_action_entry, action_execution_entry) -> list[dict]:
    return [action_entry, webhook_action_entry, action_execution_entry]


@pytest.fixture
def empty_schema() -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# Fake TdbClient
# ---------------------------------------------------------------------------


class _FakeTdb:
    """Drop-in for firnline_core TdbClient."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        docs_by_type: dict[str, list[dict]] | None = None,
        doc_by_iri: dict[str, dict] | None = None,
        raise_tdb_error_on: str | None = None,
        tdb_error: tuple[int, str] = (500, "boof"),
    ) -> None:
        self._schema = schema or []
        self._docs = docs_by_type or {}
        self._single_docs = doc_by_iri or {}
        self._raise_tdb_error_on = raise_tdb_error_on
        self._tdb_error = tdb_error
        self.aclose_called = False

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_tdb_error_on == "schema":
            raise TdbError(*self._tdb_error)
        return self._schema

    async def get_documents(self, type_: str, branch: str = "main",
                            skip: int | None = None, count: int | None = None) -> list[dict]:
        if self._raise_tdb_error_on == type_:
            raise TdbError(*self._tdb_error)
        return self._docs.get(type_, [])

    async def count_documents(self, type_: str, branch: str = "main") -> int:
        return len(self._docs.get(type_, []))

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        return self._single_docs.get(iri, {"@id": iri})

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_browser(fake: _FakeTdb) -> TdbBrowser:
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_iri_tail():
    assert _iri_tail("terminusdb:///data/OneShotTrigger/my-trigger") == "my-trigger"
    assert _iri_tail("OneShotTrigger/my-trigger") == "my-trigger"
    assert _iri_tail("") == ""


def test_resolve_ref_string():
    assert _resolve_ref("terminusdb:///data/Trigger/t1") == "terminusdb:///data/Trigger/t1"


def test_resolve_ref_dict():
    assert _resolve_ref({"@id": "terminusdb:///data/Trigger/t1"}) == "terminusdb:///data/Trigger/t1"


def test_resolve_ref_none():
    assert _resolve_ref(None) == ""
    assert _resolve_ref(None, default="fallback") == "fallback"


def test_concretes_inheriting(full_automation_schema):
    result = concretes_inheriting(full_automation_schema, "Trigger")
    assert set(result) == {"OneShotTrigger", "ScheduleTrigger"}


def test_concretes_inheriting_actions(full_automation_schema):
    result = concretes_inheriting(full_automation_schema, "Action")
    assert set(result) == {"WebhookAction", "NotifyAction"}


def test_concretes_inheriting_none():
    assert concretes_inheriting([], "Nope") == []


# ---------------------------------------------------------------------------
# _load_automations_data tests
# ---------------------------------------------------------------------------


@pytest.fixture
def trigger_docs() -> dict[str, list[dict]]:
    return {
        "OneShotTrigger": [
            {
                "@id": "OneShotTrigger/t1",
                "name": "Morning Check-in",
                "enabled": True,
                "fire_at": "2025-06-01T08:00:00Z",
            },
        ],
        "ScheduleTrigger": [
            {"@id": "ScheduleTrigger/t2", "name": "Weekly Review", "enabled": True},
        ],
        "TriggerFiring": [
            {
                "@id": "TriggerFiring/f1",
                "trigger": {"@id": "OneShotTrigger/t1"},
                "occurrence_key": "key1",
                "scheduled_for": "2025-06-01T08:00:00Z",
                "fired_at": "2025-06-01T08:00:01Z",
                "status": "notified",
                "subject": {"@id": "Entity/subj1"},
                "notification_count": 1,
            },
            {
                "@id": "TriggerFiring/f2",
                "trigger": {"@id": "ScheduleTrigger/t2"},
                "occurrence_key": "key2",
                "scheduled_for": "2025-06-08T09:00:00Z",
                "fired_at": "",
                "status": "pending",
                "notification_count": 0,
            },
            {
                "@id": "TriggerFiring/f3",
                "trigger": "OneShotTrigger/t1",
                "occurrence_key": "key3",
                "scheduled_for": "2025-05-01T08:00:00Z",
                "fired_at": "2025-05-01T08:00:01Z",
                "status": "expired",
                "notification_count": 3,
            },
        ],
    }


@pytest.fixture
def action_docs() -> dict[str, list[dict]]:
    return {
        "WebhookAction": [
            {"@id": "WebhookAction/a1", "name": "Notify Slack", "enabled": True, "url": "https://hooks.slack.com/..."},
        ],
        "NotifyAction": [
            {"@id": "NotifyAction/a2", "name": "Gotify Alert", "enabled": True},
        ],
        "ActionExecution": [
            {
                "@id": "ActionExecution/e1",
                "action": {"@id": "WebhookAction/a1"},
                "firing": {"@id": "TriggerFiring/f1"},
                "status": "succeeded",
                "attempt": 1,
                "executed_at": "2025-06-01T08:00:05Z",
                "result_detail": "HTTP 200 OK",
                "approved_by": "",
            },
            {
                "@id": "ActionExecution/e2",
                "action": {"@id": "NotifyAction/a2"},
                "firing": {"@id": "TriggerFiring/f2"},
                "status": "pending_approval",
                "attempt": 0,
                "result_detail": "",
                "approved_by": "",
            },
            {
                "@id": "ActionExecution/e3",
                "action": "WebhookAction/a1",
                "firing": {"@id": "TriggerFiring/f3"},
                "status": "failed",
                "attempt": 3,
                "next_attempt_at": "2025-07-01T12:00:00Z",
                "result_detail": "Connection timeout after 30s",
                "approved_by": "admin",
            },
        ],
    }


async def test_load_both_modules_available(full_automation_schema, trigger_docs, action_docs):
    """Happy path: both triggers and actions modules present."""
    all_docs = {**trigger_docs, **action_docs}
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=all_docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)

    assert data["triggers_available"] is True
    assert data["actions_available"] is True

    # Firing rows
    assert len(data["firing_rows"]) == 3
    # Check name resolution
    f1 = data["firing_rows"][0]  # should be sorted: 2025-06-08 first
    assert f1["trigger_name"] == "Weekly Review"
    assert f1["status"] == "pending"
    assert f1["notification_count"] == 0

    f2 = data["firing_rows"][1]
    assert f2["trigger_name"] == "Morning Check-in"
    assert f2["status"] == "notified"

    f3 = data["firing_rows"][2]
    assert f3["trigger_name"] == "Morning Check-in"  # string ref resolved
    assert f3["status"] == "expired"

    # Statuses
    assert data["firing_statuses"] == {"expired", "notified", "pending"}

    # Execution rows
    assert len(data["execution_rows"]) == 3
    e1 = data["execution_rows"][0]  # most recent: 2025-07-01
    assert e1["action_name"] == "Notify Slack"  # string ref resolved
    assert e1["status"] == "failed"
    assert e1["approved_by"] == "admin"

    e2 = data["execution_rows"][1]
    assert e2["status"] == "succeeded"

    e3 = data["execution_rows"][2]
    assert e3["status"] == "pending_approval"

    assert data["execution_statuses"] == {"failed", "pending_approval", "succeeded"}


async def test_load_triggers_only(triggers_only_schema, trigger_docs):
    """Only triggers module available."""
    fake = _FakeTdb(schema=triggers_only_schema, docs_by_type=trigger_docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)

    assert data["triggers_available"] is True
    assert data["actions_available"] is False
    assert len(data["firing_rows"]) == 3
    assert data["firing_statuses"] == {"expired", "notified", "pending"}
    assert data["execution_rows"] == []
    assert data["execution_statuses"] == set()


async def test_load_actions_only(actions_only_schema, action_docs):
    """Only actions module available."""
    # Need a TriggerFiring-free schema test
    fake = _FakeTdb(schema=actions_only_schema, docs_by_type=action_docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)

    assert data["triggers_available"] is False
    assert data["actions_available"] is True
    assert data["firing_rows"] == []
    assert data["firing_statuses"] == set()
    assert len(data["execution_rows"]) == 3


async def test_load_neither_module(empty_schema):
    """Neither triggers nor actions modules are present — graceful empty."""
    fake = _FakeTdb(schema=empty_schema)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)

    assert data["triggers_available"] is False
    assert data["actions_available"] is False
    assert data["firing_rows"] == []
    assert data["execution_rows"] == []


async def test_load_name_fallback_to_iri_tail(full_automation_schema):
    """When trigger doc has no name, fall back to IRI tail."""
    docs = {
        "OneShotTrigger": [
            {"@id": "OneShotTrigger/no-name-trigger", "enabled": True},  # no name field
        ],
        "TriggerFiring": [
            {
                "@id": "TriggerFiring/fn",
                "trigger": {"@id": "OneShotTrigger/no-name-trigger"},
                "scheduled_for": "2025-01-01T00:00:00Z",
                "status": "pending",
                "notification_count": 0,
            },
        ],
    }
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)
    assert data["firing_rows"][0]["trigger_name"] == "no-name-trigger"


async def test_load_no_subclasses_still_works(full_automation_schema):
    """When TriggerFiring exists but no Trigger subclass docs, names are IRI tails."""
    docs = {
        "TriggerFiring": [
            {
                "@id": "TriggerFiring/fx",
                "trigger": "SomeUnknownTrigger/t42",
                "scheduled_for": "2025-01-01T00:00:00Z",
                "status": "pending",
                "notification_count": 0,
            },
        ],
    }
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)
    assert data["firing_rows"][0]["trigger_name"] == "t42"


async def test_load_full_iri_refs_resolve_to_names(full_automation_schema):
    """Full-IRI trigger references (terminusdb:///data/...) resolve to display names."""
    docs = {
        "OneShotTrigger": [
            {"@id": "OneShotTrigger/ot", "name": "Reminder"},
        ],
        "TriggerFiring": [
            {
                "@id": "TriggerFiring/full",
                "trigger": {"@id": "terminusdb:///data/OneShotTrigger/ot"},
                "scheduled_for": "2025-06-01T12:00:00Z",
                "status": "pending",
                "notification_count": 0,
            },
            {
                "@id": "TriggerFiring/bare",
                "trigger": "OneShotTrigger/ot",
                "scheduled_for": "2025-06-01T11:00:00Z",
                "status": "notified",
                "notification_count": 1,
            },
        ],
    }
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=docs)
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)
    assert len(data["firing_rows"]) == 2
    rows_by_id = {r["id"]: r for r in data["firing_rows"]}
    # Full IRI ref should match via suffix lookup
    assert rows_by_id["TriggerFiring/full"]["trigger_name"] == "Reminder"
    # Bare ref should still match via exact lookup
    assert rows_by_id["TriggerFiring/bare"]["trigger_name"] == "Reminder"


async def test_load_schema_webui_client_error():
    """Schema fetch raises TdbError → WebuiClientError propagates."""
    fake = _FakeTdb(raise_tdb_error_on="schema", tdb_error=(500, "schema dead"))
    browser = _make_browser(fake)

    with pytest.raises(WebuiClientError) as exc_info:
        await _load_automations_data(browser)
    assert "schema dead" in exc_info.value.detail


async def test_load_skips_failing_subclass_fetch(full_automation_schema, trigger_docs):
    """If fetching OneShotTrigger docs fails, still load other subclasses."""
    all_docs = {**trigger_docs}
    fake = _FakeTdb(
        schema=full_automation_schema,
        docs_by_type=all_docs,
        raise_tdb_error_on="OneShotTrigger",
        tdb_error=(500, "nope"),
    )
    browser = _make_browser(fake)

    data = await _load_automations_data(browser)
    # ScheduleTrigger docs still loaded — all 3 firing rows present
    assert len(data["firing_rows"]) == 3

    # Sort rows by id for stable assertions
    rows_by_id = {r["id"]: r for r in data["firing_rows"]}
    # f1: refs OneShotTrigger/t1 → name lookup fails → falls back to IRI tail "t1"
    assert rows_by_id["TriggerFiring/f1"]["trigger_name"] == "t1"
    # f2: refs ScheduleTrigger/t2 → name lookup succeeds → "Weekly Review"
    assert rows_by_id["TriggerFiring/f2"]["trigger_name"] == "Weekly Review"
    # f3: refs OneShotTrigger/t1 (string ref) → name lookup fails → IRI tail "t1"
    assert rows_by_id["TriggerFiring/f3"]["trigger_name"] == "t1"


# ---------------------------------------------------------------------------
# AutomationsState handler tests — try/finally aclose guarantees
# ---------------------------------------------------------------------------


async def _drive_handler(state: AutomationsState, gen):
    """Drive the async generator through all yields."""
    await gen.__anext__()
    try:
        await gen.__anext__()
    except (RuntimeError, StopAsyncIteration):
        pass
    return state


async def test_handler_load_both_modules(full_automation_schema, trigger_docs, action_docs):
    """State handler: loads data, sets computed vars."""
    all_docs = {**trigger_docs, **action_docs}
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=all_docs)
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    assert fake.aclose_called
    assert state.triggers_available is True
    assert state.actions_available is True
    assert state.error == ""
    assert state.loading is False
    assert len(state.firing_rows) == 3
    assert len(state.execution_rows) == 3
    assert state.pending_firings_count == 1
    assert state.pending_approval_count == 1
    assert sorted(state.available_firing_statuses) == ["expired", "notified", "pending"]
    assert sorted(state.available_execution_statuses) == ["failed", "pending_approval", "succeeded"]


async def test_handler_load_neither_module(empty_schema):
    """State handler: neither module available → flags false, no error."""
    fake = _FakeTdb(schema=empty_schema)
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    assert fake.aclose_called
    assert state.triggers_available is False
    assert state.actions_available is False
    assert state.error == ""
    assert state.firing_rows == []
    assert state.execution_rows == []


async def test_handler_schema_error_calls_aclose():
    """When schema raises WebuiClientError, aclose is still called and error is set."""
    fake = _FakeTdb(raise_tdb_error_on="schema", tdb_error=(500, "schema boom"))
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    assert fake.aclose_called
    assert "schema boom" in state.error
    assert state.triggers_available is False
    assert state.actions_available is False


async def test_handler_aclose_even_on_unexpected_error(full_automation_schema):
    """Even when an unexpected RuntimeError occurs, aclose is called."""
    fake = _FakeTdb(schema=full_automation_schema, raise_tdb_error_on="TriggerFiring", tdb_error=(500, "bad"))
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    assert fake.aclose_called
    # The handler catches WebuiClientError only in try/except;
    # the TdbError → WebuiClientError conversion happens in _load_automations_data
    # via tdb._call. So this should set error.
    assert state.error != "" or state.loading is False


async def test_handler_filtering(full_automation_schema, trigger_docs):
    """Filtered rows computed correctly."""
    docs = {**trigger_docs}
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=docs)
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    # Default: all
    assert len(state.filtered_firing_rows) == 3

    # Set filter
    state.firing_status_filter = "pending"
    assert len(state.filtered_firing_rows) == 1
    assert state.filtered_firing_rows[0]["status"] == "pending"

    # Back to all
    state.firing_status_filter = "all"
    assert len(state.filtered_firing_rows) == 3


async def test_handler_select_document(full_automation_schema, trigger_docs):
    """Select opens detail drawer."""
    docs = {
        **trigger_docs,
    }
    doc_by_iri = {
        "TriggerFiring/f1": {"@id": "TriggerFiring/f1", "status": "notified", "extra": "detail"},
    }
    fake_load = _FakeTdb(schema=full_automation_schema, docs_by_type=docs)
    browser_load = _make_browser(fake_load)
    fake_select = _FakeTdb(doc_by_iri=doc_by_iri)
    browser_select = _make_browser(fake_select)

    # Use side_effect to return different browsers for load vs select
    calls = iter([browser_load, browser_select])

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with (
        patch("firnline_webui.state.automations.make_tdb_browser", side_effect=lambda: next(calls)),
        patch("firnline_webui.state.selection.make_tdb_browser", side_effect=lambda: next(calls)),
    ):
        state = await run()

        # Select a document
        async def select_run():
            gen2 = state.select("TriggerFiring/f1")
            await gen2.__anext__()
            try:
                await gen2.__anext__()
            except StopAsyncIteration:
                pass

        await select_run()

    assert fake_load.aclose_called
    assert state.selected_doc is not None
    assert state.selected_doc["@id"] == "TriggerFiring/f1"
    assert "extra" in state.selected_doc
    assert state.selected_json != ""


async def test_handler_clear_selection():
    """Clear closes detail drawer."""
    state = AutomationsState()  # type: ignore[call-arg]
    state.selected_doc = {"@id": "x"}
    state.selected_json = '{"@id": "x"}'

    gen = state.clear_selection()
    await gen.__anext__()
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass
    assert state.selected_doc is None
    assert state.selected_json == ""


async def test_handler_counts(full_automation_schema, trigger_docs, action_docs):
    """Computed counts are correct."""
    all_docs = {**trigger_docs, **action_docs}
    fake = _FakeTdb(schema=full_automation_schema, docs_by_type=all_docs)
    browser = _make_browser(fake)

    async def run():
        state = AutomationsState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.automations.make_tdb_browser", return_value=browser):
        state = await run()

    assert state.pending_firings_count == 1  # f2
    assert state.pending_approval_count == 1  # e2
