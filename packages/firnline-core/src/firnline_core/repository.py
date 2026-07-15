"""Repository — the single sanctioned write path for Entity documents.

Design law L6: every Entity write goes through this layer.  Extensions
and services must never call ``tdb.insert_documents`` or
``tdb.replace_document`` directly on Entity instances.
"""

from __future__ import annotations

from typing import Any

from firnline_core.base import _format_datetime
from firnline_core.conventions import parse_agent, utc_now
from firnline_core.generated.core import Provenance
from firnline_core.tdb import TdbClient, TdbConflictError, short_iri


class TransitionError(Exception):
    """Raised when a state transition is illegal or the source status is stale."""


class Repository:
    """Sanctioned Entity read/write layer.

    Accepts a *transitions* dict at construction time:
    ``{"ClassName": {"from_status": ["to_status", ...], ...}, ...}``.
    Build it from model ``ClassVar.transitions`` attributes.
    """

    def __init__(
        self,
        tdb: TdbClient,
        *,
        transitions: dict[str, dict[str, list[str]]] | None = None,
    ) -> None:
        self._tdb = tdb
        self._transitions = transitions or {}

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        doc: dict[str, Any],
        *,
        agent: str,
        method: str | None = None,
        confidence: float | None = None,
        branch: str = "main",
    ) -> str:
        """        Insert *doc*, stamping provenance.

        Validates the *agent* grammar.  Overwrites any existing
        ``provenance`` on *doc*.  Timestamps are covered by prov and
        the TerminusDB commit graph.

        Returns the full IRI of the created document.
        """
        parse_agent(agent)
        now = utc_now()
        now_str = _format_datetime(now)

        prov = Provenance(
            agent=agent,
            at=now,
            method=method,
            confidence=confidence,
        )
        prov_dict = prov.to_tdb()
        # Provenance is a subdocument — strip @type when embedding
        prov_dict.pop("@type", None)
        prov_dict.pop("@id", None)

        doc["provenance"] = prov_dict

        iris = await self._tdb.insert_documents(
            [doc],
            branch=branch,
            message=f"repo: create {doc.get('@type', '?')}",
        )
        return iris[0]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(
        self,
        iri: str,
        fields: dict[str, Any],
        *,
        agent: str,
        branch: str = "main",
    ) -> str:
        """Update an existing document, merging *fields* into it.

        Disallows changing ``@type`` and ``@id``.  Stamps provenance
        the same way :meth:`create` does.  Timestamps are covered by
        prov and the TerminusDB commit graph.

        Returns the full IRI of the updated document.
        """
        parse_agent(agent)
        short = short_iri(iri)
        now = utc_now()
        now_str = _format_datetime(now)

        # Fetch existing document
        doc = await self._tdb.get_document(short, branch=branch)

        existing_type = doc.get("@type")
        existing_id = doc.get("@id")

        # Disallow @type / @id changes
        if "@type" in fields and fields.get("@type") != existing_type:
            raise ValueError(
                f"Cannot change @type from {existing_type!r} to {fields['@type']!r}"
            )
        if "@id" in fields and fields.get("@id") != existing_id:
            raise ValueError(
                f"Cannot change @id from {existing_id!r} to {fields['@id']!r}"
            )

        # Shallow merge
        doc.update(fields)

        # Restore @type / @id to their original values (in case fields
        # contained the same values — harmless — or were popped)
        doc["@type"] = existing_type
        doc["@id"] = existing_id

        # Provenance stamp (same pattern as create)
        prov = Provenance(
            agent=agent,
            at=now,
        )
        prov_dict = prov.to_tdb()
        prov_dict.pop("@type", None)
        prov_dict.pop("@id", None)
        doc["provenance"] = prov_dict

        await self._tdb.replace_document(
            doc,
            branch=branch,
            message=f"repo: update {short}",
        )
        return iri

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------

    async def transition(
        self,
        doc_iri: str,
        field: str,
        from_status: str,
        to_status: str,
        *,
        agent: str,
        branch: str = "main",
    ) -> None:
        """Atomically transition *doc_iri*.*field* from *from_status* to *to_status*.

        Validates the transition against the per-class table declared in
        ``@metadata.transitions``.  Fails with ``TransitionError`` on
        illegal transitions or when the current value does not match
        *from_status* (stale-guard).
        """
        parse_agent(agent)
        short = short_iri(doc_iri)
        now = utc_now()
        now_str = _format_datetime(now)

        doc = await self._tdb.get_document(short, branch=branch)
        class_name = doc.get("@type", "")
        current = doc.get(field)

        if current != from_status:
            raise TransitionError(
                f"Stale status on {short}: expected '{from_status}', "
                f"got '{current}'"
            )

        table = self._transitions.get(class_name, {})
        allowed = table.get(from_status, [])
        if allowed and to_status not in allowed:
            raise TransitionError(
                f"Illegal transition on {class_name} {short}: "
                f"'{from_status}' -> '{to_status}' "
                f"(allowed: {sorted(allowed)})"
            )

        doc[field] = to_status

        transition_doc: dict[str, Any] = {
            "@type": "Transition",
            "subject": short,
            "field": field,
            "from_status": str(from_status),
            "to_status": str(to_status),
            "at": now_str,
            "agent": agent,
        }

        msg = f"repo: transition {short} {from_status}->{to_status}"
        try:
            await self._tdb.insert_documents(
                [doc, transition_doc],
                branch=branch,
                message=msg,
            )
        except TdbConflictError:
            raise
        except Exception:
            raise

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    async def archive(
        self,
        doc_iri: str,
        *,
        agent: str,
        branch: str = "main",
    ) -> None:
        """Soft-delete *doc_iri* by setting ``archived_at``.

        This is the only sanctioned way to archive a document.  Services
        must never set ``archived_at`` directly.
        """
        parse_agent(agent)
        short = short_iri(doc_iri)
        now = utc_now()
        now_str = _format_datetime(now)

        doc = await self._tdb.get_document(short, branch=branch)
        doc["archived_at"] = now_str

        archive_doc: dict[str, Any] = {
            "@type": "Transition",
            "subject": short,
            "field": "archived_at",
            "from_status": str(doc.get("archived_at", "null")),
            "to_status": "archived",
            "at": now_str,
            "agent": agent,
        }

        await self._tdb.insert_documents(
            [doc, archive_doc],
            branch=branch,
            message=f"repo: archive {short}",
        )

    # ------------------------------------------------------------------
    # Reads (with archive filtering)
    # ------------------------------------------------------------------

    async def get_documents(
        self,
        type_: str,
        *,
        include_archived: bool = False,
        branch: str = "main",
    ) -> list[dict[str, Any]]:
        """Fetch *type_* documents, filtering out archived by default."""
        docs = await self._tdb.get_documents(type_, branch=branch)
        if not include_archived:
            docs = [d for d in docs if not d.get("archived_at")]
        return docs

    async def get_documents_by_status(
        self,
        type_: str,
        status: str,
        *,
        include_archived: bool = False,
        branch: str = "main",
    ) -> list[dict[str, Any]]:
        """Fetch *type_* documents by *status*, filtering out archived by default."""
        docs = await self._tdb.get_documents_by_status(type_, status, branch=branch)
        if not include_archived:
            docs = [d for d in docs if not d.get("archived_at")]
        return docs

    async def get_document(
        self,
        iri: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Fetch a single document by IRI (pass-through)."""
        return await self._tdb.get_document(iri, branch=branch)

    # ------------------------------------------------------------------
    # Low-level access (for schema ops, non-Entity writes, etc.)
    # ------------------------------------------------------------------

    @property
    def tdb(self) -> TdbClient:
        """Direct TdbClient for non-Entity operations (schema, branches, etc.)."""
        return self._tdb
