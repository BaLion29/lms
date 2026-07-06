"""Ingestd source plugins — InboxNote and InboxAudio.

Each source knows the TerminusDB document type, its pollable ready_status,
the statuses for done/failed, how to extract the text that will be fed into
the extraction agent, and how to get a reference datetime for relative-date
resolution.

Registered via the ``firnline.ingestd.sources`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from firnline_core.conventions import utc_now
from firnline_core.plugins import IngestSourcePlugin, ModuleRequirement

logger = structlog.get_logger(__name__)


class InboxNoteSource:
    """Pull-source for InboxNote documents (status="new" → text from content)."""

    name: str = "inbox_note"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="inbox", range=">=1.0.0 <2.0.0")]
    document_type: str = "InboxNote"
    ready_status: str = "new"
    done_status: str = "processed"
    failed_status: str = "failed"

    def text(self, doc: dict[str, Any]) -> str:
        return doc["content"]

    def reference_time(self, doc: dict[str, Any]) -> datetime:
        created_at = doc.get("created_at", "")
        if not created_at:
            logger.warning(
                "reference_datetime_missing",
                iri=doc.get("@id", ""),
                field="created_at",
            )
            return utc_now()
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "reference_datetime_unparseable",
                iri=doc.get("@id", ""),
                field="created_at",
                value=created_at,
            )
            return utc_now()


class InboxAudioSource:
    """Pull-source for InboxAudio documents (status="transcribed" → text from transcription)."""

    name: str = "inbox_audio"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="inbox", range=">=1.0.0 <2.0.0")]
    document_type: str = "InboxAudio"
    ready_status: str = "transcribed"
    done_status: str = "processed"
    failed_status: str = "failed"

    def text(self, doc: dict[str, Any]) -> str:
        return doc["transcription"]

    def reference_time(self, doc: dict[str, Any]) -> datetime:
        recorded_at = doc.get("recorded_at", "")
        if not recorded_at:
            logger.warning(
                "reference_datetime_missing",
                iri=doc.get("@id", ""),
                field="recorded_at",
            )
            return utc_now()
        try:
            return datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "reference_datetime_unparseable",
                iri=doc.get("@id", ""),
                field="recorded_at",
                value=recorded_at,
            )
            return utc_now()


# Module-level instances for entry-point discovery
inbox_note_plugin = InboxNoteSource()
inbox_audio_plugin = InboxAudioSource()
