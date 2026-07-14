"""Ingestd source plugins — Captured documents (text and audio).

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
from firnline_core.plugins import ModuleRequirement

logger = structlog.get_logger(__name__)


class CapturedTextSource:
    """Pull-source for text-type Captured documents (status="new" → text from content)."""

    name: str = "captured_text"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="capture", range=">=0.1.0 <0.2.0")]
    document_type: str = "Captured"
    ready_status: str = "new"
    done_status: str = "processed"
    failed_status: str = "failed"

    def text(self, doc: dict[str, Any]) -> str:
        return doc.get("content") or ""

    def reference_time(self, doc: dict[str, Any]) -> datetime:
        captured_at = doc.get("captured_at", "")
        if not captured_at:
            logger.warning(
                "reference_datetime_missing",
                iri=doc.get("@id", ""),
                field="captured_at",
            )
            return utc_now()
        try:
            return datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "reference_datetime_unparseable",
                iri=doc.get("@id", ""),
                field="captured_at",
                value=captured_at,
            )
            return utc_now()


class CapturedAudioSource:
    """Pull-source for audio-type Captured documents (status="transcribed" → text from transcription)."""

    name: str = "captured_audio"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="capture", range=">=0.1.0 <0.2.0")]
    document_type: str = "Captured"
    ready_status: str = "transcribed"
    done_status: str = "processed"
    failed_status: str = "failed"

    def text(self, doc: dict[str, Any]) -> str:
        return doc.get("transcription") or ""

    def reference_time(self, doc: dict[str, Any]) -> datetime:
        captured_at = doc.get("captured_at", "")
        if not captured_at:
            logger.warning(
                "reference_datetime_missing",
                iri=doc.get("@id", ""),
                field="captured_at",
            )
            return utc_now()
        try:
            return datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "reference_datetime_unparseable",
                iri=doc.get("@id", ""),
                field="captured_at",
                value=captured_at,
            )
            return utc_now()


# Module-level instances for entry-point discovery
captured_text_plugin = CapturedTextSource()
captured_audio_plugin = CapturedAudioSource()
