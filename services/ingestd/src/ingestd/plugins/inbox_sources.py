"""Built-in ingestd source plugins — InboxNote and InboxAudio.

Each source knows the TerminusDB document type, its pollable ready_status,
the statuses for processing/done/failed, and how to extract the text that
will be fed into the extraction agent.

Registered via the ``lms.ingestd.sources`` entry point.
"""

from __future__ import annotations

from typing import Any

from lms_core.plugins import IngestSourcePlugin, ModuleRequirement


class InboxNoteSource:
    """Pull-source for InboxNote documents (status="new" → text from content)."""

    name: str = "inbox_note"
    document_type: str = "InboxNote"
    ready_status: str = "new"
    processing_status: str = "new"  # we flip to "new" during processing (unchanged)
    done_status: str = "processed"
    failed_status: str = "failed"
    requires: list[ModuleRequirement] = []

    def build_extraction_input(self, doc: dict[str, Any]) -> str:
        return doc["content"]


class InboxAudioSource:
    """Pull-source for InboxAudio documents (status="transcribed" → text from transcription)."""

    name: str = "inbox_audio"
    document_type: str = "InboxAudio"
    ready_status: str = "transcribed"
    processing_status: str = "transcribed"  # we flip to "transcribed" during processing (unchanged)
    done_status: str = "processed"
    failed_status: str = "failed"
    requires: list[ModuleRequirement] = []

    def build_extraction_input(self, doc: dict[str, Any]) -> str:
        return doc["transcription"]


# Module-level instances for entry-point discovery
inbox_note_plugin = InboxNoteSource()
inbox_audio_plugin = InboxAudioSource()
