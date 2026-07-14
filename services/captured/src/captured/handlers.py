"""Capture handlers — create Captured documents."""

from __future__ import annotations

from firnline_core.conventions import agent_id
from firnline_core.models import Captured, CapturedStatus, Provenance
from firnline_core.plugins import CaptureContext, CapturePayload, ModuleRequirement


class CapturedNoteHandler:
    """Handle ``note`` captures → ``Captured`` with content_type ``text/plain``, status ``new``."""

    name: str = "captured_note"
    kinds: tuple[str, ...] = ("note",)
    requires: list[ModuleRequirement] = [ModuleRequirement(name="capture", range=">=0.1.0 <0.2.0")]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        now = payload.captured_at or ctx.now()
        doc = Captured(
            content_type="text/plain",
            content=payload.text or "",
            captured_at=now,
            status=CapturedStatus.NEW,
            created_at=now,
            updated_at=now,
            provenance=Provenance(
                agent=agent_id("service", "captured"),
                at=ctx.now(),
                method="capture:note",
            ),
        )
        tdb_doc = doc.to_tdb()
        iris = await ctx.tdb.insert_documents([tdb_doc])
        return iris[0] if iris else ""


class CapturedAudioHandler:
    """Handle ``file`` captures → ``Captured`` with ``content_type`` from payload, status ``new``.

    Requires ``payload.blob_sha256`` to be set by captured.
    """

    name: str = "captured_audio"
    kinds: tuple[str, ...] = ("file",)
    requires: list[ModuleRequirement] = [ModuleRequirement(name="capture", range=">=0.1.0 <0.2.0")]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        if not payload.blob_sha256:
            raise ValueError("Audio capture requires blob_sha256 (file upload)")

        if ctx.blob_store is None:
            raise RuntimeError(
                "Audio handler requires a BlobStore; the captured service "
                "guarantees the blob was stored before handler dispatch — but "
                "no BlobStore is available in the CaptureContext."
            )
        blob_path = ctx.blob_store.get_path(payload.blob_sha256)
        if blob_path is None:
            raise RuntimeError(
                f"Blob for digest {payload.blob_sha256} not found in BlobStore; "
                f"the captured service guarantees the blob was stored before "
                f"handler dispatch — this indicates a storage integrity issue."
            )

        now = payload.captured_at or ctx.now()
        doc = Captured(
            content_type=payload.content_type or "application/octet-stream",
            blob_sha256=payload.blob_sha256,
            file_name=payload.filename or "unnamed",
            transcription=None,
            captured_at=now,
            status=CapturedStatus.NEW,
            created_at=now,
            updated_at=now,
            provenance=Provenance(
                agent=agent_id("service", "captured"),
                at=ctx.now(),
                method="capture:file",
            ),
        )
        tdb_doc = doc.to_tdb()
        iris = await ctx.tdb.insert_documents([tdb_doc])
        return iris[0] if iris else ""


# Module-level instances for entry-point discovery
captured_note_handler = CapturedNoteHandler()
captured_audio_handler = CapturedAudioHandler()
