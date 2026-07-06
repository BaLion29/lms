"""Tests for inbox source plugins (moved verbatim from ingestd's original sources)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import ANY

import structlog
import pytest

from lms_ext_inbox.sources import InboxAudioSource, InboxNoteSource


class TestInboxNoteSource:
    def test_name(self) -> None:
        src = InboxNoteSource()
        assert src.name == "inbox_note"

    def test_document_type_and_statuses(self) -> None:
        src = InboxNoteSource()
        assert src.document_type == "InboxNote"
        assert src.ready_status == "new"
        assert src.done_status == "processed"
        assert src.failed_status == "failed"

    def test_text_returns_content(self) -> None:
        src = InboxNoteSource()
        assert src.text({"content": "hello world"}) == "hello world"

    def test_reference_time_valid(self) -> None:
        src = InboxNoteSource()
        doc = {"created_at": "2026-07-05T14:00:00Z"}
        dt = src.reference_time(doc)
        assert dt == datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)

    def test_reference_time_missing_warns(self) -> None:
        src = InboxNoteSource()
        doc = {"@id": "InboxNote/xyz"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_missing"
        ]
        assert len(warning_events) == 1
        assert warning_events[0]["iri"] == "InboxNote/xyz"
        assert warning_events[0]["field"] == "created_at"

    def test_reference_time_unparseable_warns(self) -> None:
        src = InboxNoteSource()
        doc = {"created_at": "not-a-date", "@id": "InboxNote/bad"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_unparseable"
        ]
        assert len(warning_events) == 1

    def test_requires_inbox_module(self) -> None:
        src = InboxNoteSource()
        assert len(src.requires) == 1
        assert src.requires[0].name == "inbox"
        assert src.requires[0].range == ">=1.0.0 <2.0.0"


class TestInboxAudioSource:
    def test_name(self) -> None:
        src = InboxAudioSource()
        assert src.name == "inbox_audio"

    def test_document_type_and_statuses(self) -> None:
        src = InboxAudioSource()
        assert src.document_type == "InboxAudio"
        assert src.ready_status == "transcribed"
        assert src.done_status == "processed"
        assert src.failed_status == "failed"

    def test_text_returns_transcription(self) -> None:
        src = InboxAudioSource()
        assert src.text({"transcription": "call bob"}) == "call bob"

    def test_reference_time_valid(self) -> None:
        src = InboxAudioSource()
        doc = {"recorded_at": "2026-07-05T14:00:00Z"}
        dt = src.reference_time(doc)
        assert dt == datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)

    def test_reference_time_missing_warns(self) -> None:
        src = InboxAudioSource()
        doc = {"@id": "InboxAudio/abc"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_missing"
        ]
        assert len(warning_events) == 1
        assert warning_events[0]["iri"] == "InboxAudio/abc"
        assert warning_events[0]["field"] == "recorded_at"

    def test_reference_time_unparseable_warns(self) -> None:
        src = InboxAudioSource()
        doc = {"recorded_at": "not-a-date", "@id": "InboxAudio/bad"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_unparseable"
        ]
        assert len(warning_events) == 1

    def test_requires_inbox_module(self) -> None:
        src = InboxAudioSource()
        assert len(src.requires) == 1
        assert src.requires[0].name == "inbox"
        assert src.requires[0].range == ">=1.0.0 <2.0.0"
