"""SQLite-backed hybrid vector+lexical store for indexed documents and schema items.

Uses built-in ``sqlite3`` with FTS5 for lexical search and in-process cosine
similarity for vector ranking.  No native extension dependency — sufficient
for personal-scale LMS (thousands of documents).
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_vector(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


class Candidate:
    __slots__ = ("iri", "class_name", "name", "aliases", "score", "commit_id")

    def __init__(
        self,
        iri: str,
        class_name: str,
        name: str,
        aliases: list[str],
        score: float,
        commit_id: str,
    ):
        self.iri = iri
        self.class_name = class_name
        self.name = name
        self.aliases = aliases
        self.score = score
        self.commit_id = commit_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "iri": self.iri,
            "class": self.class_name,
            "name": self.name,
            "aliases": self.aliases,
            "score": round(self.score, 4),
            "commit_id": self.commit_id,
        }


class SchemaCandidate:
    __slots__ = ("kind", "class_name", "field", "name", "type_hint", "docstring", "score")

    def __init__(
        self,
        kind: str,
        class_name: str,
        field: str,
        name: str,
        type_hint: str,
        docstring: str,
        score: float,
    ):
        self.kind = kind
        self.class_name = class_name
        self.field = field
        self.name = name
        self.type_hint = type_hint
        self.docstring = docstring
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "class": self.class_name,
            "field": self.field,
            "name": self.name,
            "type": self.type_hint,
            "description": self.docstring,
            "score": round(self.score, 4),
        }


class Store:
    """Hybrid vector+lexical store backed by a single SQLite file.

    Tables:
    - ``entities(iri, class, name, aliases_json, text, embedding, norm, commit_id, branch, updated_at)``
    - ``entities_fts`` — FTS5 content table shadowing ``entities``
    - ``schema_items(kind, class, field, name, type_hint, docstring, embedding, norm, commit_id)``
    - ``schema_items_fts``
    - ``sync_state(branch PK, last_commit_id, last_polled_at)``
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store not opened")
        return self._conn

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                iri       TEXT PRIMARY KEY,
                class     TEXT NOT NULL,
                name      TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                text      TEXT NOT NULL DEFAULT '',
                embedding BLOB,
                norm      REAL,
                commit_id TEXT NOT NULL DEFAULT '',
                branch    TEXT NOT NULL DEFAULT 'main',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS schema_items (
                kind      TEXT NOT NULL CHECK(kind IN ('class', 'field', 'enum_value')),
                class     TEXT NOT NULL DEFAULT '',
                field     TEXT NOT NULL DEFAULT '',
                name      TEXT NOT NULL,
                type_hint TEXT NOT NULL DEFAULT '',
                docstring TEXT NOT NULL DEFAULT '',
                embedding BLOB,
                norm      REAL,
                commit_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, class, field, name)
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                branch          TEXT PRIMARY KEY,
                last_commit_id  TEXT NOT NULL DEFAULT '',
                last_polled_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                iri UNINDEXED,
                name,
                aliases_json,
                text,
                content='entities',
                content_rowid='rowid'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS schema_items_fts USING fts5(
                name,
                docstring,
                content='schema_items',
                content_rowid='rowid'
            );
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Sync state
    # ------------------------------------------------------------------

    def get_last_commit(self, branch: str) -> str:
        row = self.conn.execute("SELECT last_commit_id FROM sync_state WHERE branch = ?", (branch,)).fetchone()
        return row["last_commit_id"] if row else ""

    def set_last_commit(self, branch: str, commit_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO sync_state (branch, last_commit_id, last_polled_at)
            VALUES (?, ?, ?)
            ON CONFLICT(branch) DO UPDATE SET
                last_commit_id = excluded.last_commit_id,
                last_polled_at = excluded.last_polled_at
            """,
            (branch, commit_id, now),
        )
        self.conn.commit()

    def get_last_polled_at(self, branch: str) -> str:
        row = self.conn.execute("SELECT last_polled_at FROM sync_state WHERE branch = ?", (branch,)).fetchone()
        return row["last_polled_at"] if row else ""

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    def delete_entity(self, iri: str) -> None:
        self.conn.execute("DELETE FROM entities WHERE iri = ?", (iri,))
        self.conn.commit()

    def replace_all_entities_for_branch(
        self,
        branch: str,
        entries: list[dict[str, Any]],
    ) -> None:
        """Atomically replace all entities for *branch* with *entries*.

        Each entry must have: iri, class, name, aliases, text, embedding, commit_id.
        """
        self.conn.execute("DELETE FROM entities WHERE branch = ?", (branch,))
        now = datetime.now(timezone.utc).isoformat()
        rows: list[tuple] = []
        for e in entries:
            packed = _pack_vector(e["embedding"])
            norm_val = _norm(e["embedding"])
            aliases_json = json.dumps(e.get("aliases", []), ensure_ascii=False)
            rows.append(
                (
                    e["iri"],
                    e["class"],
                    e["name"],
                    aliases_json,
                    e.get("text", ""),
                    packed,
                    norm_val,
                    e.get("commit_id", ""),
                    branch,
                    now,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO entities (iri, class, name, aliases_json, text, embedding, norm, commit_id, branch, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.execute("INSERT INTO entities_fts(entities_fts) VALUES('rebuild')")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Schema item CRUD
    # ------------------------------------------------------------------

    def replace_all_schema_items(self, items: list[dict[str, Any]]) -> None:
        """Atomically replace all schema items."""
        self.conn.execute("DELETE FROM schema_items")
        rows: list[tuple] = []
        for item in items:
            packed = _pack_vector(item["embedding"])
            norm_val = _norm(item["embedding"])
            rows.append(
                (
                    item["kind"],
                    item.get("class", ""),
                    item.get("field", ""),
                    item["name"],
                    item.get("type_hint", ""),
                    item.get("docstring", ""),
                    packed,
                    norm_val,
                    item.get("commit_id", ""),
                )
            )
        self.conn.executemany(
            """
            INSERT INTO schema_items (kind, class, field, name, type_hint, docstring, embedding, norm, commit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.execute("INSERT INTO schema_items_fts(schema_items_fts) VALUES('rebuild')")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_entities(
        self,
        query_text: str,
        query_vector: list[float],
        *,
        classes: list[str] | None = None,
        branch: str = "main",
        k: int = 10,
        min_confidence: float = 0.0,
    ) -> list[Candidate]:
        """Hybrid search: weighted cosine + FTS BM25, filtered by branch."""
        if not query_text.strip():
            all_rows = self.conn.execute(
                "SELECT iri, class, name, aliases_json, embedding, norm, commit_id FROM entities WHERE branch = ?",
                (branch,),
            ).fetchall()
        else:
            fts_clause = "entities_fts MATCH ?"
            like_pattern = f"%{query_text}%"
            lex_rows = {
                r["iri"]
                for r in self.conn.execute(
                    f"SELECT e.iri FROM entities e JOIN entities_fts f ON e.rowid = f.rowid WHERE {fts_clause} AND e.branch = ?",
                    (query_text, branch),
                ).fetchall()
            }
            name_rows = {
                r["iri"]
                for r in self.conn.execute(
                    "SELECT iri FROM entities WHERE (name LIKE ? OR aliases_json LIKE ?) AND branch = ?",
                    (like_pattern, like_pattern, branch),
                ).fetchall()
            }
            candidate_iris = lex_rows | name_rows
            if not candidate_iris:
                return []
            placeholders = ",".join("?" for _ in candidate_iris)
            all_rows = self.conn.execute(
                f"SELECT iri, class, name, aliases_json, embedding, norm, commit_id "
                f"FROM entities WHERE iri IN ({placeholders})",
                tuple(candidate_iris),
            ).fetchall()

        if classes:
            all_rows = [r for r in all_rows if r["class"] in classes]

        candidates: list[Candidate] = []
        for row in all_rows:
            vec = _unpack_vector(row["embedding"]) if row["embedding"] else []
            if vec and query_vector:
                vector_score = _cosine(query_vector, vec)
            else:
                vector_score = 0.0

            lexical_score = 0.0
            q_lower = query_text.lower()
            name_lower = (row["name"] or "").lower()
            if q_lower == name_lower:
                lexical_score = 1.0
            elif q_lower in name_lower:
                lexical_score = 0.8
            else:
                aliases = json.loads(row["aliases_json"])
                for alias in aliases:
                    alias_lower = alias.lower()
                    if q_lower == alias_lower:
                        lexical_score = 0.95
                        break
                    elif q_lower in alias_lower:
                        lexical_score = 0.7
                        break

            score = 0.7 * vector_score + 0.3 * lexical_score
            if score < min_confidence:
                continue

            candidates.append(
                Candidate(
                    iri=row["iri"],
                    class_name=row["class"],
                    name=row["name"],
                    aliases=json.loads(row["aliases_json"]),
                    score=score,
                    commit_id=row["commit_id"],
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k]

    def search_schema(
        self,
        query_text: str,
        query_vector: list[float],
        *,
        kind: str | None = None,
        class_name: str | None = None,
        k: int = 10,
        min_confidence: float = 0.0,
    ) -> list[SchemaCandidate]:
        """Hybrid search over schema items."""
        if query_text.strip():
            fts_clause = "schema_items_fts MATCH ?"
            lex_rows = {
                (r["kind"], r["class"], r["field"], r["name"])
                for r in self.conn.execute(
                    f"SELECT s.kind, s.class, s.field, s.name FROM schema_items s "
                    f"JOIN schema_items_fts f ON s.rowid = f.rowid WHERE {fts_clause}",
                    (query_text,),
                ).fetchall()
            }
            like_pattern = f"%{query_text}%"
            name_rows = {
                (r["kind"], r["class"], r["field"], r["name"])
                for r in self.conn.execute(
                    "SELECT kind, class, field, name FROM schema_items WHERE name LIKE ?",
                    (like_pattern,),
                ).fetchall()
            }
            candidate_keys = lex_rows | name_rows
        else:
            candidate_keys = {
                (r["kind"], r["class"], r["field"], r["name"])
                for r in self.conn.execute("SELECT kind, class, field, name FROM schema_items").fetchall()
            }

        if not candidate_keys:
            return []

        placeholders = ",".join("(?,?,?,?)" for _ in candidate_keys)
        flat_keys: list[Any] = []
        for kt in candidate_keys:
            flat_keys.extend(kt)

        all_rows = self.conn.execute(
            f"SELECT kind, class, field, name, type_hint, docstring, embedding, norm "
            f"FROM schema_items WHERE (kind, class, field, name) IN ({placeholders})",
            flat_keys,
        ).fetchall()

        if kind:
            all_rows = [r for r in all_rows if r["kind"] == kind]
        if class_name:
            all_rows = [r for r in all_rows if r["class"] == class_name]

        candidates: list[SchemaCandidate] = []
        for row in all_rows:
            vec = _unpack_vector(row["embedding"]) if row["embedding"] else []
            if vec and query_vector:
                vector_score = _cosine(query_vector, vec)
            else:
                vector_score = 0.0

            lexical_score = 0.0
            q_lower = query_text.lower()
            name_lower = (row["name"] or "").lower()
            if q_lower == name_lower:
                lexical_score = 1.0
            elif q_lower in name_lower:
                lexical_score = 0.8

            score = 0.7 * vector_score + 0.3 * lexical_score
            if score < min_confidence:
                continue

            candidates.append(
                SchemaCandidate(
                    kind=row["kind"],
                    class_name=row["class"],
                    field=row["field"],
                    name=row["name"],
                    type_hint=row["type_hint"],
                    docstring=row["docstring"],
                    score=score,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k]
