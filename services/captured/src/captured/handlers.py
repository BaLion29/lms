"""Capture handlers for inbox — create InboxNote / InboxAudio documents."""

from __future__ import annotations

from firnline_core.models import InboxAudio, InboxAudioStatus, InboxNote, InboxNoteStatus, Provenance
from firnline_core.plugins import CaptureContext, CapturePayload, ModuleRequirement


class InboxNoteHandler:
    """Handle ``note`` captures → ``InboxNote@new``."""

    name: str = "inbox_note"
    kinds: tuple[str, ...] = ("note",)
    requires: list[ModuleRequirement] = [ModuleRequirement(name="inbox", range=">=0.1.0 <0.2.0")]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        now = payload.captured_at or ctx.now()
        doc = InboxNote(
            content=payload.text or "",
            created_at=now,
            status=InboxNoteStatus.NEW,
            updated_at=now,
            provenance=Provenance(agent="captured", at=ctx.now(), method="capture", source=None),
        )
        tdb_doc = doc.to_tdb()
        iris = await ctx.tdb.insert_documents([tdb_doc])
        return iris[0] if iris else ""


class InboxAudioHandler:
    """Handle ``file`` captures → ``InboxAudio@new``.

    Requires ``payload.blob_sha256`` to be set by captured.  The blob digest
    is stored in ``file_path`` (the closest existing field — there is no
    dedicated blob/sha256 column on InboxAudio as of schema 0.1.0).
    """

    name: str = "inbox_audio"
    kinds: tuple[str, ...] = ("file",)
    requires: list[ModuleRequirement] = [ModuleRequirement(name="inbox", range=">=0.1.0 <0.2.0")]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        if not payload.blob_sha256:
            raise ValueError("InboxAudio capture requires blob_sha256 (file upload)")

        if ctx.blob_store is None:
            raise RuntimeError(
                "InboxAudio handler requires a BlobStore; the captured service "
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
        doc = InboxAudio(
            created_at=now,
            file_name=payload.filename or "unnamed",
            file_path=str(blob_path),
            recorded_at=now,
            status=InboxAudioStatus.NEW,
            transcription="",
            updated_at=now,
            provenance=Provenance(agent="captured", at=ctx.now(), method="capture", source=None),
        )
        tdb_doc = doc.to_tdb()
        iris = await ctx.tdb.insert_documents([tdb_doc])
        return iris[0] if iris else ""


# Module-level instances for entry-point discovery
inbox_note_handler = InboxNoteHandler()
inbox_audio_handler = InboxAudioHandler()
