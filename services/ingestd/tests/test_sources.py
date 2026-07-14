"""Tests for ingestd source plugins — Captured (text and audio)."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from ingestd.sources import CapturedAudioSource, CapturedTextSource


class TestCapturedTextSource:
    def test_name(self) -> None:
        src = CapturedTextSource()
        assert src.name == "captured_text"

    def test_document_type_and_statuses(self) -> None:
        src = CapturedTextSource()
        assert src.document_type == "Captured"
        assert src.ready_status == "new"
        assert src.done_status == "processed"
        assert src.failed_status == "failed"

    def test_text_returns_content(self) -> None:
        src = CapturedTextSource()
        assert src.text({"content": "hello world"}) == "hello world"

    def test_text_missing_content_returns_empty(self) -> None:
        src = CapturedTextSource()
        assert src.text({}) == ""

    def test_reference_time_valid(self) -> None:
        src = CapturedTextSource()
        doc = {"captured_at": "2026-07-05T14:00:00Z"}
        dt = src.reference_time(doc)
        assert dt == datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)

    def test_reference_time_missing_warns(self) -> None:
        src = CapturedTextSource()
        doc = {"@id": "Captured/xyz"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_missing"
        ]
        assert len(warning_events) == 1
        assert warning_events[0]["iri"] == "Captured/xyz"
        assert warning_events[0]["field"] == "captured_at"

    def test_reference_time_unparseable_warns(self) -> None:
        src = CapturedTextSource()
        doc = {"captured_at": "not-a-date", "@id": "Captured/bad"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_unparseable"
        ]
        assert len(warning_events) == 1

    def test_requires_capture_module(self) -> None:
        src = CapturedTextSource()
        assert len(src.requires) == 1
        assert src.requires[0].name == "capture"
        assert src.requires[0].range == ">=0.1.0 <0.2.0"


class TestCapturedAudioSource:
    def test_name(self) -> None:
        src = CapturedAudioSource()
        assert src.name == "captured_audio"

    def test_document_type_and_statuses(self) -> None:
        src = CapturedAudioSource()
        assert src.document_type == "Captured"
        assert src.ready_status == "transcribed"
        assert src.done_status == "processed"
        assert src.failed_status == "failed"

    def test_text_returns_transcription(self) -> None:
        src = CapturedAudioSource()
        assert src.text({"transcription": "call bob"}) == "call bob"

    def test_text_missing_transcription_returns_empty(self) -> None:
        src = CapturedAudioSource()
        assert src.text({}) == ""

    def test_reference_time_valid(self) -> None:
        src = CapturedAudioSource()
        doc = {"captured_at": "2026-07-05T14:00:00Z"}
        dt = src.reference_time(doc)
        assert dt == datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)

    def test_reference_time_missing_warns(self) -> None:
        src = CapturedAudioSource()
        doc = {"@id": "Captured/abc"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_missing"
        ]
        assert len(warning_events) == 1
        assert warning_events[0]["iri"] == "Captured/abc"
        assert warning_events[0]["field"] == "captured_at"

    def test_reference_time_unparseable_warns(self) -> None:
        src = CapturedAudioSource()
        doc = {"captured_at": "not-a-date", "@id": "Captured/bad"}
        with structlog.testing.capture_logs() as captured:
            dt = src.reference_time(doc)
        assert isinstance(dt, datetime)
        warning_events = [
            e for e in captured if e.get("event") == "reference_datetime_unparseable"
        ]
        assert len(warning_events) == 1

    def test_requires_capture_module(self) -> None:
        src = CapturedAudioSource()
        assert len(src.requires) == 1
        assert src.requires[0].name == "capture"
        assert src.requires[0].range == ">=0.1.0 <0.2.0"
