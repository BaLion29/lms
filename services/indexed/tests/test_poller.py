"""Unit tests for indexed.poller — AsyncMock TdbClient + real Store on tmp_path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from indexed.poller import Poller
from indexed.store import Store

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_embedding(*values: float, dim: int = 3) -> list[float]:
    vec = list(values)
    vec += [0.0] * (dim - len(vec))
    return vec[:dim]


def _make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "index.db")
    store.open()
    return store


class FakeSettings:
    """Minimal settings matching what the Poller constructor expects."""

    tdb_branch: str = "main"
    llm_base_url: str = ""
    llm_api_key: str = ""
    embedding_model: str = "test-model"


# ---------------------------------------------------------------------------
# 1. Cursor no-op — head unchanged
# ---------------------------------------------------------------------------


async def test_sync_once_noop_when_head_equals_last_commit(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "abc123")

        tdb = AsyncMock()
        tdb.get_branch_head = AsyncMock(return_value="abc123")
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_documents = AsyncMock(return_value=[])

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        changed = await poller.sync_once()
        assert changed is True

        # No reindex calls should have happened
        tdb.get_schema.assert_not_called()
        tdb.get_documents.assert_not_called()

        # Commit should not have changed
        assert store.get_last_commit("main") == "abc123"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. Cursor advance — head moved forward
# ---------------------------------------------------------------------------


async def test_sync_once_reindexes_when_head_advanced(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "abc123")

        tdb = AsyncMock()
        tdb.get_branch_head = AsyncMock(return_value="def456")
        tdb.get_schema = AsyncMock(return_value=[])  # empty schema → no schema items
        tdb.get_documents = AsyncMock(return_value=[])

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        changed = await poller.sync_once()
        assert changed is True

        # Schema reindex always called (even if empty schema)
        tdb.get_schema.assert_called_once_with("main")

        # get_documents only called when there are indexer plugins — here none
        tdb.get_documents.assert_not_called()

        # Commit should be updated
        assert store.get_last_commit("main") == "def456"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 3. _reindex_schema — realistic planning schema
# ---------------------------------------------------------------------------

RAW_SCHEMA = [
    {
        "@id": "Task",
        "@type": "Class",
        "@inherits": ["Remindable", "Source", "TaskSpec"],
        "created_at": "xsd:dateTime",
        "derived_from": {
            "@class": "Source",
            "@type": "Optional",
        },
        "due_date": {
            "@class": "xsd:dateTime",
            "@type": "Optional",
        },
        "status": "TaskStatus",
        "updated_at": "xsd:dateTime",
        "@key": {"@type": "Lexical", "@fields": ["name"]},
        "@documentation": {"@comment": "A task that can be scheduled."},
    },
    {
        "@id": "TaskStatus",
        "@type": "Enum",
        "@value": ["open", "planned", "done"],
        "@documentation": {"@comment": "Possible task states."},
    },
]


async def test_reindex_schema_class_and_enum_properties(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        tdb = AsyncMock()
        tdb.get_schema = AsyncMock(return_value=RAW_SCHEMA)
        tdb.get_documents = AsyncMock(return_value=[])

        embed_fn = AsyncMock()
        embed_fn.return_value = [_make_embedding(1.0, i * 0.1) for i in range(10)]

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
            embed_fn=embed_fn,
        )

        await poller._reindex_schema("commit99")

        # Check that schema items were stored
        results = store.search_schema("", _make_embedding(1.0))
        assert len(results) > 0, "Schema items should have been stored"

        # --- Find the Task class entry ---
        class_entries = [r for r in results if r.kind == "class" and r.name == "Task"]
        assert len(class_entries) == 1
        task_class = class_entries[0]
        assert task_class.type_hint == "Class"
        assert task_class.docstring == "A task that can be scheduled."

        # --- No @-prefixed key should be a field ---
        field_names = {r.name for r in results if r.kind == "field"}
        for fn in field_names:
            assert not fn.endswith("@key")
            assert not fn.endswith("@inherits")
            assert not fn.endswith("@documentation")
            assert not fn.endswith("@id")
            assert not fn.endswith("@type")

        # --- String property type_hint ---
        created_at_fields = [r for r in results if r.name == "Task.created_at"]
        assert len(created_at_fields) == 1
        assert created_at_fields[0].type_hint == "xsd:dateTime"

        # --- Dict property type_hint (@class) ---
        derived_from_fields = [r for r in results if r.name == "Task.derived_from"]
        assert len(derived_from_fields) == 1
        assert derived_from_fields[0].type_hint == "Source"

        # --- Dict property type_hint (Optional with @class) ---
        due_date_fields = [r for r in results if r.name == "Task.due_date"]
        assert len(due_date_fields) == 1
        assert due_date_fields[0].type_hint == "xsd:dateTime"

        # --- Enum values are indexed (regression: code uses @value) ---
        enum_entries = [r for r in results if r.kind == "enum_value"]
        enum_names = {r.name for r in enum_entries}
        assert "TaskStatus.open" in enum_names
        assert "TaskStatus.planned" in enum_names
        assert "TaskStatus.done" in enum_names

        for e in enum_entries:
            assert e.type_hint == "enum"
            assert e.class_name == "TaskStatus"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. _reindex_entities — fake plugin
# ---------------------------------------------------------------------------


class FakeIndexerPlugin:
    """Minimal plugin implementing the IndexerPlugin protocol (duck-typed)."""

    name: str = "fake_plugin"
    requires: list = [  # noqa: RUF012
        # Normally ModuleRequirement objects — empty for testing
    ]

    def indexed_classes(self) -> list[str]:
        return ["Person"]

    def entity_text(self, doc: dict) -> str:
        return f"Person: {doc.get('name', '')}"

    def entity_name(self, doc: dict) -> str:
        return str(doc.get("name", ""))

    def entity_aliases(self, doc: dict) -> list[str]:
        name = doc.get("name", "")
        return [name.lower()] if name else []


async def test_reindex_entities_plugin_integration(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        tdb = AsyncMock()
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_branch_head = AsyncMock(return_value="abc")
        tdb.get_documents = AsyncMock(
            return_value=[
                {"@id": "Person/alice", "name": "Alice"},
                {"@id": "Person/bob", "name": "Bob"},
            ]
        )

        embed_fn = AsyncMock()
        embed_fn.return_value = [_make_embedding(1.0), _make_embedding(0.5)]

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
            embed_fn=embed_fn,
        )

        await poller._reindex_entities("commit42")

        # tdb.get_documents was called with branch=
        tdb.get_documents.assert_called_once_with("Person", branch="main")

        # Entities stored
        results = store.search_entities("", _make_embedding(1.0), branch="main")
        assert len(results) == 2

        iri_map = {r.iri: r for r in results}

        # Alice
        alice = iri_map["Person/alice"]
        assert alice.name == "Alice"
        assert alice.class_name == "Person"
        assert alice.aliases == ["alice"]
        assert alice.commit_id == "commit42"

        # Bob
        bob = iri_map["Person/bob"]
        assert bob.name == "Bob"
        assert bob.aliases == ["bob"]
        assert bob.commit_id == "commit42"
    finally:
        store.close()


async def test_reindex_entities_empty_docs_no_crash(tmp_path: Path):
    """When tdb returns no documents, no entities are stored (no crash)."""
    store = _make_store(tmp_path)
    try:
        tdb = AsyncMock()
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_documents = AsyncMock(return_value=[])

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
        )

        await poller._reindex_entities("commit42")

        results = store.search_entities("", _make_embedding(1.0), branch="main")
        assert len(results) == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. sync_once — branch_head fetch failure is graceful
# ---------------------------------------------------------------------------


async def test_sync_once_branch_head_fetch_failure(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        tdb = AsyncMock()
        tdb.get_branch_head = AsyncMock(side_effect=RuntimeError("network down"))

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        ok = await poller.sync_once()
        assert ok is False
    finally:
        store.close()
