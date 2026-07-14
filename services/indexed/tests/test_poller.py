"""Unit tests for indexed.poller — AsyncMock TdbClient + real Store on tmp_path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from firnline_core.tdb import ChangeEvent, StaleCommitError, TdbError
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
# 1. Fresh store — no last commit → full reindex
# ---------------------------------------------------------------------------


async def test_sync_once_fresh_store_full_reindex(tmp_path: Path):
    """When store has no last commit (""), Poller does a full reindex."""
    store = _make_store(tmp_path)
    try:
        assert store.get_last_commit("main") == ""

        tdb = AsyncMock()
        tdb.get_branch_head = AsyncMock(return_value="init-commit")
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_documents = AsyncMock(return_value=[])

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        ok = await poller.sync_once()
        assert ok is True

        # Full reindex path: get_branch_head + get_schema called
        tdb.get_branch_head.assert_called_once_with("main")
        tdb.get_schema.assert_called_once_with("main")
        # changes_since must NOT be called on fresh store
        tdb.changes_since.assert_not_called()

        assert store.get_last_commit("main") == "init-commit"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. Noop — head unchanged (changes_since returns no events, same head)
# ---------------------------------------------------------------------------


async def test_sync_once_noop_same_head(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "abc123")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(return_value=([], "abc123"))

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        ok = await poller.sync_once()
        assert ok is True

        tdb.changes_since.assert_called_once_with("abc123", "main")
        tdb.get_schema.assert_not_called()
        tdb.get_documents.assert_not_called()

        assert store.get_last_commit("main") == "abc123"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 3. No events but head moved — store updated without reindex
# ---------------------------------------------------------------------------


async def test_sync_once_no_events_head_moved(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "abc123")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(return_value=([], "def456"))

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        ok = await poller.sync_once()
        assert ok is True

        # No reindex calls
        tdb.get_schema.assert_not_called()
        tdb.get_documents.assert_not_called()

        # Head bumped
        assert store.get_last_commit("main") == "def456"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. changes_since TdbError → full reindex fallback
# ---------------------------------------------------------------------------


async def test_sync_once_changes_since_tdberror_fallback(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "abc123")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(side_effect=TdbError(500, "boom"))
        tdb.get_branch_head = AsyncMock(return_value="recovery-head")
        tdb.get_schema = AsyncMock(return_value=[])

        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[],
        )

        ok = await poller.sync_once()
        assert ok is True

        # Fallback: get_branch_head + get_schema were called
        tdb.changes_since.assert_called_once_with("abc123", "main")
        tdb.get_branch_head.assert_called_once_with("main")
        tdb.get_schema.assert_called_once_with("main")

        assert store.get_last_commit("main") == "recovery-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4b. changes_since StaleCommitError → full reindex with distinct warning
# ---------------------------------------------------------------------------


async def test_sync_once_stale_commit_full_resync(tmp_path: Path):
    """StaleCommitError triggers full reindex with cursor_stale_full_resync log."""
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "deadbeef")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            side_effect=StaleCommitError("deadbeef", "main")
        )
        tdb.get_branch_head = AsyncMock(return_value="recovery-head")
        tdb.get_schema = AsyncMock(return_value=[])

        import structlog
        with structlog.testing.capture_logs() as captured:
            poller = Poller(
                tdb=tdb,
                store=store,
                settings=FakeSettings(),
                indexer_plugins=[],
            )
            ok = await poller.sync_once()

        assert ok is True

        # Distinct warning event was logged
        stale_warnings = [
            e for e in captured
            if e.get("event") == "cursor_stale_full_resync"
        ]
        assert len(stale_warnings) == 1
        assert stale_warnings[0]["branch"] == "main"
        assert stale_warnings[0]["stale_commit"] == "deadbeef"

        # Same fallback recovery as TdbError path
        tdb.changes_since.assert_called_once_with("deadbeef", "main")
        tdb.get_branch_head.assert_called_once_with("main")
        tdb.get_schema.assert_called_once_with("main")

        assert store.get_last_commit("main") == "recovery-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. Incremental insert path
# ---------------------------------------------------------------------------


async def test_sync_once_incremental_insert(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "old-head")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            return_value=(
                [
                    ChangeEvent(
                        commit_id="new-head",
                        author="testbot",
                        message="schema: add Person/alice",
                        inserted=["Person/alice"],
                        updated=[],
                        deleted=[],
                    )
                ],
                "new-head",
            )
        )
        tdb.get_document = AsyncMock(
            return_value={"@id": "Person/alice", "name": "Alice", "type": "Person"}
        )
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_branch_head = AsyncMock(return_value="new-head")

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

        ok = await poller.sync_once()
        assert ok is True

        # Incremental path used get_document for the single IRI
        tdb.get_document.assert_called_once_with("Person/alice", branch="main")
        # Schema keyword in message → schema reindex triggered
        tdb.get_schema.assert_called_once_with("main")

        # Entity stored
        results = store.search_entities("Alice", _make_embedding(1.0))
        assert len(results) == 1
        assert results[0].iri == "Person/alice"
        assert results[0].name == "Alice"
        assert results[0].commit_id == "new-head"

        assert store.get_last_commit("main") == "new-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 6. Incremental update path
# ---------------------------------------------------------------------------


async def test_sync_once_incremental_update(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        # Pre-seed the store with an existing entity
        store.upsert_entity(
            iri="Person/bob",
            class_name="Person",
            name="Bob Old",
            aliases=["bob"],
            text="Person: Bob Old",
            embedding=_make_embedding(0.1),
            commit_id="old-head",
            branch="main",
        )
        store.set_last_commit("main", "old-head")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            return_value=(
                [
                    ChangeEvent(
                        commit_id="new-head",
                        author="testbot",
                        message="update Person/bob name",
                        inserted=[],
                        updated=["Person/bob"],
                        deleted=[],
                    )
                ],
                "new-head",
            )
        )
        tdb.get_document = AsyncMock(
            return_value={"@id": "Person/bob", "name": "Bob New", "type": "Person"}
        )
        # Schema unchanged → no get_schema call
        tdb.get_schema = AsyncMock(return_value=[])

        embed_fn = AsyncMock()
        embed_fn.return_value = [_make_embedding(0.8)]

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
            embed_fn=embed_fn,
        )

        ok = await poller.sync_once()
        assert ok is True

        tdb.get_document.assert_called_once_with("Person/bob", branch="main")
        # No schema keyword → get_schema NOT called
        tdb.get_schema.assert_not_called()

        results = store.search_entities("Bob", _make_embedding(0.8))
        assert len(results) == 1
        assert results[0].iri == "Person/bob"
        assert results[0].name == "Bob New"
        assert results[0].commit_id == "new-head"

        assert store.get_last_commit("main") == "new-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 7. Incremental delete path
# ---------------------------------------------------------------------------


async def test_sync_once_incremental_delete(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        # Pre-seed
        store.upsert_entity(
            iri="Person/charlie",
            class_name="Person",
            name="Charlie",
            aliases=["chaz"],
            text="Person: Charlie",
            embedding=_make_embedding(0.5),
            commit_id="old-head",
            branch="main",
        )
        store.set_last_commit("main", "old-head")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            return_value=(
                [
                    ChangeEvent(
                        commit_id="new-head",
                        author="testbot",
                        message="remove Person/charlie",
                        inserted=[],
                        updated=[],
                        deleted=["Person/charlie"],
                    )
                ],
                "new-head",
            )
        )
        tdb.get_schema = AsyncMock(return_value=[])

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
        )

        ok = await poller.sync_once()
        assert ok is True

        # Deleted entity gone from search
        results = store.search_entities("Charlie", _make_embedding(0.5))
        assert len(results) == 0

        assert store.get_last_commit("main") == "new-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 8. Incremental — unindexed class IRIs are silently skipped
# ---------------------------------------------------------------------------


async def test_sync_once_incremental_skips_unindexed_class(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "old-head")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            return_value=(
                [
                    ChangeEvent(
                        commit_id="new-head",
                        author="testbot",
                        message="add some data",
                        inserted=["UnindexedClass/foo", "Person/dave"],
                        updated=[],
                        deleted=[],
                    )
                ],
                "new-head",
            )
        )
        tdb.get_document = AsyncMock(
            return_value={"@id": "Person/dave", "name": "Dave", "type": "Person"}
        )
        tdb.get_schema = AsyncMock(return_value=[])

        embed_fn = AsyncMock()
        embed_fn.return_value = [_make_embedding(0.3)]

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
            embed_fn=embed_fn,
        )

        ok = await poller.sync_once()
        assert ok is True

        # Only Person/dave fetched (1 call), UnindexedClass/foo skipped
        tdb.get_document.assert_called_once_with("Person/dave", branch="main")

        results = store.search_entities("", _make_embedding(0.0))
        assert len(results) == 1
        assert results[0].iri == "Person/dave"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 9. Incremental TdbError during doc fetch → full reindex fallback
# ---------------------------------------------------------------------------


async def test_sync_once_incremental_tdberror_fallback(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        store.set_last_commit("main", "old-head")

        tdb = AsyncMock()
        tdb.changes_since = AsyncMock(
            return_value=(
                [
                    ChangeEvent(
                        commit_id="new-head",
                        author="testbot",
                        message="add Person/eve",
                        inserted=["Person/eve"],
                        updated=[],
                        deleted=[],
                    )
                ],
                "new-head",
            )
        )
        # get_document raises TdbError → triggers full-reindex fallback
        tdb.get_document = AsyncMock(side_effect=TdbError(404, "not found"))

        # Full reindex resources
        tdb.get_branch_head = AsyncMock(return_value="fallback-head")
        tdb.get_schema = AsyncMock(return_value=[])
        tdb.get_documents = AsyncMock(return_value=[])

        plugin = FakeIndexerPlugin()
        poller = Poller(
            tdb=tdb,
            store=store,
            settings=FakeSettings(),
            indexer_plugins=[plugin],
        )

        ok = await poller.sync_once()
        assert ok is True

        # Fallback: full reindex happened (get_branch_head + get_documents)
        tdb.get_branch_head.assert_called_once_with("main")
        tdb.get_documents.assert_called_once_with("Person", branch="main")

        assert store.get_last_commit("main") == "fallback-head"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 10. Branch head fetch failure during full sync
# ---------------------------------------------------------------------------


async def test_sync_once_full_sync_head_failure(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        # Store is fresh → triggers full sync
        assert store.get_last_commit("main") == ""

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


# ---------------------------------------------------------------------------
# 11. _reindex_schema — realistic planning schema (unchanged from original)
# ---------------------------------------------------------------------------

RAW_SCHEMA = [
    {
        "@id": "Task",
        "@type": "Class",
        "@inherits": ["Entity", "Source", "TaskSpec"],
        "created_at": "xsd:dateTime",
        "provenance": {
            "@class": "Provenance",
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
        provenance_fields = [r for r in results if r.name == "Task.provenance"]
        assert len(provenance_fields) == 1
        assert provenance_fields[0].type_hint == "Provenance"

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
# 12. _reindex_entities — fake plugin (unchanged from original)
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
