"""Polling loop — synchronises TerminusDB documents and schema into the hybrid store."""

from __future__ import annotations

from typing import Any

import structlog

from indexed.store import Store

logger = structlog.get_logger(__name__)


class Poller:
    """Incrementally mirrors TDB document classes and schema into the store.

    Uses ``/api/log`` to detect new commits and reindexes only when the
    branch head has advanced.  Document indexing is driven by
    ``IndexerPlugin`` instances discovered via entry points.
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
        """Run one sync cycle.  Returns ``True`` on success."""
        try:
            head = await self.tdb.get_branch_head(self._branch)
        except Exception:
            logger.warning("branch_head_fetch_failed", branch=self._branch, exc_info=True)
            return False

        last = self.store.get_last_commit(self._branch)
        if head == last:
            return True

        logger.info("new_commits_detected", last=last, head=head, branch=self._branch)

        if self._indexer_plugins:
            await self._reindex_entities(head)

        await self._reindex_schema(head)

        self.store.set_last_commit(self._branch, head)
        return True

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
