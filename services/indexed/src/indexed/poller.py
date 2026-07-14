"""Polling loop — synchronises TerminusDB documents and schema into the hybrid store."""

from __future__ import annotations

from typing import Any

import structlog

from firnline_core.tdb import ChangeEvent, StaleCommitError, TdbError
from indexed.store import Store

logger = structlog.get_logger(__name__)

_SCHEMA_KEYWORDS = frozenset(
    {
        "schema",
        "migration",
        "class",
        "property",
        "enum",
        "type",
        "field",
        "attribute",
        "relationship",
        "documentation",
        "abstract",
        "inherits",
        "domain",
        "range",
    }
)


class Poller:
    """Incrementally mirrors TDB document classes and schema into the store.

    Uses the kernel change feed (``changes_since``) for incremental sync,
    falling back to a full reindex on error.
    """

    def __init__(
        self,
        tdb: Any,
        store: Store,
        settings: Any,
        indexer_plugins: list[Any],
        *,
        embed_fn: Any | None = None,
    ) -> None:
        self.tdb = tdb
        self.store = store
        self.settings = settings
        self._indexer_plugins = indexer_plugins
        self._embed_fn = embed_fn
        self._branch = settings.tdb_branch

    # ------------------------------------------------------------------
    # Cycle entry
    # ------------------------------------------------------------------

    async def sync_once(self) -> bool:
        """Run one sync cycle.  Returns ``True`` on success.

        Decision tree
        -------------
        1. No stored last commit (fresh store) → full reindex.
        2. Otherwise: call ``changes_since(last_commit)``.
           a. ``TdbError`` → full reindex fallback.
           b. No events → update stored head if changed; done.
           c. Events → incremental apply.
              - Any ``TdbError`` during incremental → full reindex fallback.
        """
        last = self.store.get_last_commit(self._branch)

        # ---- fresh store: baseline with a full reindex ----
        if last == "":
            return await self._full_sync()

        # ---- ask the kernel what changed since last_commit ----
        try:
            events, new_head = await self.tdb.changes_since(last, self._branch)
        except StaleCommitError as exc:
            logger.warning(
                "cursor_stale_full_resync",
                branch=self._branch,
                stale_commit=exc.commit_id,
            )
            return await self._full_sync()
        except TdbError:
            logger.warning("changes_since_failed", branch=self._branch, exc_info=True)
            return await self._full_sync()

        # ---- no events: just bump the stored head if needed ----
        if not events:
            if new_head != last:
                self.store.set_last_commit(self._branch, new_head)
            return True

        # ---- incremental apply ----
        try:
            await self._apply_changes(events, new_head)
        except TdbError:
            logger.warning("incremental_apply_tdberror", branch=self._branch, exc_info=True)
            return await self._full_sync()
        except Exception:
            logger.warning("incremental_apply_unexpected", branch=self._branch, exc_info=True)
            return await self._full_sync()

        self.store.set_last_commit(self._branch, new_head)
        return True

    # ------------------------------------------------------------------
    # Full sync (today's behaviour)
    # ------------------------------------------------------------------

    async def _full_sync(self) -> bool:
        """Full reindex — fetch everything and replace store contents."""
        try:
            head = await self.tdb.get_branch_head(self._branch)
        except Exception:
            logger.warning("branch_head_fetch_failed", branch=self._branch, exc_info=True)
            return False

        logger.info("full_sync_triggered", branch=self._branch, head=head)

        if self._indexer_plugins:
            await self._reindex_entities(head)

        await self._reindex_schema(head)

        self.store.set_last_commit(self._branch, head)
        return True

    # ------------------------------------------------------------------
    # Incremental apply
    # ------------------------------------------------------------------

    async def _apply_changes(
        self, events: list[ChangeEvent], new_head: str
    ) -> None:
        """Apply a batch of change events incrementally.

        Collects affected IRIs from all events, fetches only changed
        documents, and upserts/deletes single entities.  Schema reindex
        is triggered only when a commit message / author suggests a
        schema change (keyword heuristic).
        """

        # --- collect affected IRIs & detect schema changes ---
        all_inserted: set[str] = set()
        all_updated: set[str] = set()
        all_deleted: set[str] = set()
        schema_changed = False

        for event in events:
            all_inserted.update(event.inserted)
            all_updated.update(event.updated)
            all_deleted.update(event.deleted)

            combined = (event.message + " " + event.author).lower()
            if any(kw in combined for kw in _SCHEMA_KEYWORDS):
                schema_changed = True

        # --- build class → plugin mapping ---
        plugin_by_class: dict[str, Any] = {}
        for plugin in self._indexer_plugins:
            for cls in plugin.indexed_classes():
                plugin_by_class[cls] = plugin

        # --- upsert inserted + updated documents ---
        for iri in sorted(all_inserted | all_updated):
            class_name = iri.split("/", 1)[0]
            plugin = plugin_by_class.get(class_name)
            if plugin is None:
                continue  # not an indexed class

            doc = await self.tdb.get_document(iri, branch=self._branch)

            # Soft-delete: if archived_at is set, remove from index
            if doc.get("archived_at"):
                self.store.delete_entity(iri)
                continue

            name = plugin.entity_name(doc)
            aliases = plugin.entity_aliases(doc)
            text = plugin.entity_text(doc)

            embeddings = await self._embed([text])
            embedding = embeddings[0] if embeddings else []

            self.store.upsert_entity(
                iri=iri,
                class_name=class_name,
                name=name,
                aliases=aliases,
                text=text,
                embedding=embedding,
                commit_id=new_head,
                branch=self._branch,
            )

        # --- delete removed documents ---
        for iri in sorted(all_deleted):
            self.store.delete_entity(iri)

        # --- schema reindex (conditionally) ---
        if schema_changed:
            await self._reindex_schema(new_head)

        affected = len(all_inserted) + len(all_updated) + len(all_deleted)
        logger.info(
            "incremental_sync_complete",
            affected_iris=affected,
            schema_reindexed=schema_changed,
            new_head=new_head,
        )

    # ------------------------------------------------------------------
    # Schema indexing
    # ------------------------------------------------------------------

    async def _reindex_schema(self, commit_id: str) -> None:
        try:
            raw_schema = await self.tdb.get_schema(self._branch)
        except Exception:
            logger.warning("schema_fetch_failed", branch=self._branch, exc_info=True)
            return

        items: list[dict[str, Any]] = []
        texts: list[str] = []

        for entry in raw_schema:
            if not isinstance(entry, dict):
                continue
            class_id = entry.get("@id")
            if not isinstance(class_id, str):
                continue

            if entry.get("@type") == "Class":
                class_name = class_id
                docstring = (
                    entry.get("@documentation", {}).get("@comment", "")
                    if isinstance(entry.get("@documentation"), dict)
                    else entry.get("comment", "")
                    if isinstance(entry.get("comment"), str)
                    else ""
                )
                abstract = entry.get("@abstract", False)
                if abstract:
                    continue
                text = f"Class {class_name}. {docstring}"
                texts.append(text)
                items.append(
                    {
                        "kind": "class",
                        "class": class_name,
                        "field": "",
                        "name": class_name,
                        "type_hint": "Class",
                        "docstring": docstring,
                        "commit_id": commit_id,
                    }
                )

                for prop_name, prop_def in entry.items():
                    if prop_name.startswith("@"):
                        continue
                    if isinstance(prop_def, str):
                        prop_type = prop_def
                    elif isinstance(prop_def, dict):
                        prop_type = prop_def.get("@class", "unknown")
                    else:
                        continue
                    if isinstance(prop_def, dict):
                        prop_docstring = (
                            prop_def.get("@documentation", {}).get("@comment", "")
                            if isinstance(prop_def.get("@documentation"), dict)
                            else prop_def.get("comment", "")
                            if isinstance(prop_def.get("comment"), str)
                            else ""
                        )
                    else:
                        prop_docstring = ""
                    prop_text = f"Field {class_name}.{prop_name} type {prop_type}. {prop_docstring}"
                    texts.append(prop_text)
                    items.append(
                        {
                            "kind": "field",
                            "class": class_name,
                            "field": prop_name,
                            "name": f"{class_name}.{prop_name}",
                            "type_hint": prop_type,
                            "docstring": prop_docstring,
                            "commit_id": commit_id,
                        }
                    )

            elif entry.get("@type") == "Enum":
                enum_name = class_id
                docstring = (
                    entry.get("@documentation", {}).get("@comment", "")
                    if isinstance(entry.get("@documentation"), dict)
                    else entry.get("comment", "")
                    if isinstance(entry.get("comment"), str)
                    else ""
                )
                values = entry.get("@value", [])
                for val in values:
                    val_text = f"Enum value {enum_name}.{val}"
                    texts.append(val_text)
                    items.append(
                        {
                            "kind": "enum_value",
                            "class": enum_name,
                            "field": "",
                            "name": f"{enum_name}.{val}",
                            "type_hint": "enum",
                            "docstring": docstring,
                            "commit_id": commit_id,
                        }
                    )

        if not texts:
            return

        embeddings = await self._embed(texts)
        for item, emb in zip(items, embeddings):
            item["embedding"] = emb

        self.store.replace_all_schema_items(items)
        logger.info("schema_indexed", item_count=len(items))

    # ------------------------------------------------------------------
    # Entity indexing
    # ------------------------------------------------------------------

    async def _reindex_entities(self, commit_id: str) -> None:
        entries: list[dict[str, Any]] = []
        texts: list[str] = []

        indexed_classes: set[str] = set()
        plugin_by_class: dict[str, Any] = {}
        for plugin in self._indexer_plugins:
            for cls in plugin.indexed_classes():
                indexed_classes.add(cls)
                plugin_by_class[cls] = plugin

        for class_name in sorted(indexed_classes):
            try:
                docs = await self.tdb.get_documents(class_name, branch=self._branch)
            except Exception:
                logger.warning("entity_fetch_failed", class_name=class_name, exc_info=True)
                continue

            plugin = plugin_by_class[class_name]
            for doc in docs:
                iri = doc.get("@id", "")
                if not iri:
                    continue
                # Soft-delete: skip documents with archived_at set
                if doc.get("archived_at"):
                    continue
                name = plugin.entity_name(doc)
                aliases = plugin.entity_aliases(doc)
                text = plugin.entity_text(doc)

                texts.append(text)
                entries.append(
                    {
                        "iri": iri,
                        "class": class_name,
                        "name": name,
                        "aliases": aliases,
                        "text": text,
                        "commit_id": commit_id,
                    }
                )

        if not texts:
            return

        embeddings = await self._embed(texts)
        for entry, emb in zip(entries, embeddings):
            entry["embedding"] = emb

        self.store.replace_all_entities_for_branch(self._branch, entries)
        logger.info("entities_indexed", class_count=len(indexed_classes), entity_count=len(entries))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is not None:
            return await self._embed_fn(texts)
        from indexed.embed import embed_texts

        return await embed_texts(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            model=self.settings.embedding_model,
            texts=texts,
        )
