"""Unit tests for indexed.store — no network, real SQLite on tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from indexed.store import (
    Store,
    _cosine,
    _norm,
    _pack_vector,
    _unpack_vector,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_embedding(*values: float, dim: int = 3) -> list[float]:
    """Deterministic short embedding vector padded to *dim*."""
    vec = list(values)
    vec += [0.0] * (dim - len(vec))
    return vec[:dim]


def _entity_entry(
    iri: str,
    *,
    class_name: str = "TestClass",
    name: str = "",
    embedding: list[float] | None = None,
    branch: str = "main",
    commit_id: str = "abc123",
) -> dict:
    if embedding is None:
        embedding = _make_embedding(1.0)
    return {
        "iri": iri,
        "class": class_name,
        "name": name or iri.rsplit("/", 1)[-1],
        "aliases": [],
        "text": name or iri,
        "embedding": embedding,
        "commit_id": commit_id,
        "branch": branch,
    }


def _schema_entry(
    kind: str,
    *,
    class_name: str = "",
    field: str = "",
    name: str = "",
    type_hint: str = "",
    docstring: str = "",
    embedding: list[float] | None = None,
    commit_id: str = "abc123",
) -> dict:
    if embedding is None:
        embedding = _make_embedding(1.0)
    return {
        "kind": kind,
        "class": class_name,
        "field": field,
        "name": name,
        "type_hint": type_hint,
        "docstring": docstring,
        "embedding": embedding,
        "commit_id": commit_id,
    }


# ---------------------------------------------------------------------------
# 1. open / lifecycle
# ---------------------------------------------------------------------------


def test_open_creates_db_and_parent_dirs(tmp_path: Path):
    db_path = tmp_path / "sub" / "test.db"
    store = Store(db_path)
    store.open()
    try:
        assert db_path.exists()
        # get_last_commit returns "" for unknown branch
        assert store.get_last_commit("main") == ""
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. set_last_commit / get_last_commit round-trip
# ---------------------------------------------------------------------------


def test_commit_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        store.set_last_commit("main", "deadbeef")
        assert store.get_last_commit("main") == "deadbeef"

        # overwrite
        store.set_last_commit("main", "cafebabe")
        assert store.get_last_commit("main") == "cafebabe"

        # different branch
        store.set_last_commit("develop", "1234567")
        assert store.get_last_commit("develop") == "1234567"
        assert store.get_last_commit("main") == "cafebabe"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 3. replace_all_entities_for_branch
# ---------------------------------------------------------------------------


def test_replace_all_entities_deletes_old_inserts_new(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        e1 = _entity_entry("test://1", name="first")
        e2 = _entity_entry("test://2", name="second")
        store.replace_all_entities_for_branch("main", [e1, e2])

        # search with empty query returns all entities on branch
        results = store.search_entities(query_text="", query_vector=_make_embedding(1.0), branch="main")
        assert len(results) == 2

        # replace with a different set
        e3 = _entity_entry("test://3", name="third")
        store.replace_all_entities_for_branch("main", [e3])

        results = store.search_entities(query_text="", query_vector=_make_embedding(1.0), branch="main")
        assert len(results) == 1
        assert results[0].iri == "test://3"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. search_entities — lexical match
# ---------------------------------------------------------------------------


def test_search_entities_lexical_exact_name_match(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        e1 = _entity_entry("test://1", name="Alice")
        e2 = _entity_entry("test://2", name="Bob")
        store.replace_all_entities_for_branch("main", [e1, e2])

        results = store.search_entities("Alice", _make_embedding(1.0))
        assert len(results) >= 1
        assert results[0].name == "Alice"
    finally:
        store.close()


def test_search_entities_lexical_substring_in_name(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        e1 = _entity_entry("test://1", name="Alice Anderson")
        e2 = _entity_entry("test://2", name="Bob")
        store.replace_all_entities_for_branch("main", [e1, e2])

        results = store.search_entities("Alice", _make_embedding(1.0))
        assert len(results) >= 1
        assert results[0].name == "Alice Anderson"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. search_entities — vector score contributes
# ---------------------------------------------------------------------------


def test_search_entities_vector_boosts_identical_entity(tmp_path: Path):
    """An entity whose embedding perfectly matches the query gets a high score."""
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        # same name, different embeddings — the one matching query wins
        e1 = _entity_entry("test://1", name="SameName", embedding=_make_embedding(1.0))
        e2 = _entity_entry("test://2", name="SameName", embedding=_make_embedding(-1.0))
        store.replace_all_entities_for_branch("main", [e1, e2])

        results = store.search_entities("SameName", _make_embedding(1.0), min_confidence=-1.0)
        assert len(results) >= 2
        # Both have identical lexical score (exact name match → 1.0),
        # but e1's vector cosine is higher, so it ranks first.
        assert results[0].iri == "test://1"
        assert results[0].score > results[1].score
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 6. search_entities — classes filter
# ---------------------------------------------------------------------------


def test_search_entities_classes_filter(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        e1 = _entity_entry("test://p", name="Alice", class_name="Person")
        e2 = _entity_entry("test://t", name="Alice-task", class_name="Task")
        store.replace_all_entities_for_branch("main", [e1, e2])

        results = store.search_entities("", _make_embedding(1.0), classes=["Person"])
        assert len(results) == 1
        assert results[0].class_name == "Person"

        results = store.search_entities("Alice", _make_embedding(1.0), classes=["Person"])
        assert len(results) == 1
        assert results[0].class_name == "Person"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 7. search_entities — min_confidence
# ---------------------------------------------------------------------------


def test_search_entities_min_confidence_filters(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        # This entity's embedding is orthogonal to query → low score
        e1 = _entity_entry("test://1", name="Zaphod", embedding=_make_embedding(0.0, 0.0, 0.0))
        store.replace_all_entities_for_branch("main", [e1])

        results = store.search_entities(
            "Zaphod",
            _make_embedding(1.0, 0.0, 0.0),
            min_confidence=0.8,
        )
        # vector score = cosine([0,0,0], [1,0,0]) = 0.0
        # lexical score = exact name match = 1.0
        # combined = 0.7*0 + 0.3*1.0 = 0.3  → below 0.8
        assert len(results) == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 8. search_entities — branch isolation
# ---------------------------------------------------------------------------


def test_search_entities_branch_isolation(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        e1 = _entity_entry("test://1", name="Alice")
        store.replace_all_entities_for_branch("main", [e1])

        # Searching branch "other" (with empty query) should yield nothing
        results = store.search_entities("", _make_embedding(1.0), branch="other")
        assert len(results) == 0

        # Searching branch "main" still works
        results = store.search_entities("", _make_embedding(1.0), branch="main")
        assert len(results) == 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 9. search_schema — kind filter
# ---------------------------------------------------------------------------


def test_search_schema_kind_filter(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        items = [
            _schema_entry("class", class_name="Task", name="Task", type_hint="Class"),
            _schema_entry("field", class_name="Task", field="name", name="Task.name", type_hint="xsd:string"),
            _schema_entry("enum_value", class_name="TaskStatus", name="TaskStatus.open", type_hint="enum"),
        ]
        store.replace_all_schema_items(items)

        class_results = store.search_schema("", _make_embedding(1.0), kind="class")
        assert len(class_results) == 1
        assert class_results[0].kind == "class"

        field_results = store.search_schema("", _make_embedding(1.0), kind="field")
        assert len(field_results) == 1
        assert field_results[0].kind == "field"

        enum_results = store.search_schema("", _make_embedding(1.0), kind="enum_value")
        assert len(enum_results) == 1
        assert enum_results[0].kind == "enum_value"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 10. search_schema — class_name filter
# ---------------------------------------------------------------------------


def test_search_schema_class_name_filter(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        items = [
            _schema_entry("class", class_name="Task", name="Task"),
            _schema_entry("class", class_name="Event", name="Event"),
            _schema_entry("field", class_name="Task", field="status", name="Task.status"),
            _schema_entry("field", class_name="Event", field="status", name="Event.status"),
        ]
        store.replace_all_schema_items(items)

        results = store.search_schema("", _make_embedding(1.0), class_name="Task")
        assert len(results) == 2
        for r in results:
            assert r.class_name == "Task"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 11. search_schema — lexical query
# ---------------------------------------------------------------------------


def test_search_schema_lexical_name_match(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        items = [
            _schema_entry("class", class_name="Task", name="Task"),
            _schema_entry("class", class_name="Event", name="Event"),
        ]
        store.replace_all_schema_items(items)

        results = store.search_schema("Task", _make_embedding(1.0))
        assert len(results) >= 1
        assert results[0].name == "Task"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 12. upsert_entity — insert & update
# ---------------------------------------------------------------------------


def test_upsert_entity_insert_new(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        store.upsert_entity(
            iri="test://alpha",
            class_name="Person",
            name="Alpha",
            aliases=["a"],
            text="Alpha person",
            embedding=_make_embedding(0.2, 0.3),
            commit_id="c001",
            branch="main",
        )

        results = store.search_entities("Alpha", _make_embedding(0.2, 0.3))
        assert len(results) == 1
        r = results[0]
        assert r.iri == "test://alpha"
        assert r.name == "Alpha"
        assert r.aliases == ["a"]
        assert r.class_name == "Person"
        assert r.commit_id == "c001"
    finally:
        store.close()


def test_upsert_entity_update_existing(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        # Insert initial
        store.upsert_entity(
            iri="test://beta",
            class_name="Task",
            name="Beta",
            aliases=["b1"],
            text="Beta task v1",
            embedding=_make_embedding(1.0),
            commit_id="c001",
            branch="main",
        )

        # Update same IRI — name, text, embedding, commit change
        store.upsert_entity(
            iri="test://beta",
            class_name="Task",
            name="Beta Updated",
            aliases=["b2"],
            text="Beta task v2",
            embedding=_make_embedding(0.5),
            commit_id="c002",
            branch="main",
        )

        results = store.search_entities("Beta", _make_embedding(0.5))
        assert len(results) == 1
        r = results[0]
        assert r.iri == "test://beta"
        assert r.name == "Beta Updated"
        assert r.aliases == ["b2"]
        assert r.commit_id == "c002"
    finally:
        store.close()


def test_upsert_and_search_fts_consistency(tmp_path: Path):
    """Upserting should keep FTS and content rows in sync (no rebuild needed)."""
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        store.upsert_entity(
            iri="test://gamma",
            class_name="Note",
            name="Gamma Ray",
            aliases=["g-ray"],
            text="A gamma radiation note",
            embedding=_make_embedding(0.7),
            commit_id="c003",
            branch="main",
        )

        # Lexical search via FTS should find it
        results = store.search_entities("Gamma", _make_embedding(0.7))
        assert len(results) == 1
        assert results[0].iri == "test://gamma"
    finally:
        store.close()


def test_delete_entity_removes_row_and_fts(tmp_path: Path):
    store = Store(tmp_path / "store.db")
    store.open()
    try:
        store.upsert_entity(
            iri="test://delta",
            class_name="Item",
            name="Delta",
            aliases=[],
            text="Delta item",
            embedding=_make_embedding(0.9),
            commit_id="c004",
            branch="main",
        )

        # Pre-condition: search finds it
        results = store.search_entities("Delta", _make_embedding(0.9))
        assert len(results) == 1

        store.delete_entity("test://delta")

        # Post-condition: gone from search results
        results = store.search_entities("Delta", _make_embedding(0.9))
        assert len(results) == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 13. vector helpers — unit tests
# ---------------------------------------------------------------------------


def test_pack_unpack_roundtrip():
    v = [1.0, -2.5, 3.0]
    data = _pack_vector(v)
    assert _unpack_vector(data) == v


def test_cosine_same_direction():
    v = [1.0, 0.0, 0.0]
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector():
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_norm():
    assert _norm([3.0, 4.0]) == pytest.approx(5.0)
