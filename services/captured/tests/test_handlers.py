"""Tests for capture handlers against a fake TdbClient."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from firnline_core.plugins import CaptureContext, CapturePayload

from captured.handlers import captured_audio_handler, captured_note_handler

UTC = timezone.utc


def _fake_tdb(iris: list[str] | None = None) -> AsyncMock:
    tdb = AsyncMock()
    tdb.insert_documents = AsyncMock(return_value=iris or ["terminusdb:///data/Captured/new1"])
    return tdb


def _ctx(tdb=None, blob_store=None) -> CaptureContext:
    if tdb is None:
        tdb = _fake_tdb()
    return CaptureContext(tdb=tdb, blob_store=blob_store, logger=None)


class _FakeBlobStore:
    """Fake BlobStore that maps a known digest to a fixed path."""

    def __init__(self, sha256: str, path: Path) -> None:
        self._sha256 = sha256
        self._path = path

    def get_path(self, sha256: str) -> Path | None:
        return self._path if sha256 == self._sha256 else None


class TestCapturedNoteHandler:
    @pytest.mark.asyncio
    async def test_creates_captured_from_payload(self) -> None:
        tdb = _fake_tdb()
        ctx = _ctx(tdb)
        payload = CapturePayload(
            kind="note",
            text="Hello world",
            captured_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        )
        iri = await captured_note_handler.handle(payload, ctx)
        assert iri == "terminusdb:///data/Captured/new1"
        tdb.insert_documents.assert_called_once()
        docs = tdb.insert_documents.call_args[0][0]
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Captured"
        assert doc["content_type"] == "text/plain"
        assert doc["content"] == "Hello world"
        assert doc["status"] == "new"
        assert doc["captured_at"] == "2026-07-05T14:00:00Z"
        assert doc["created_at"] == "2026-07-05T14:00:00Z"
        assert doc["updated_at"] == "2026-07-05T14:00:00Z"
        # Provenance subdocument
        assert "provenance" in doc
        prov = doc["provenance"]
        assert prov["@type"] == "Provenance"
        assert prov["agent"] == "service:captured"
        assert prov["method"] == "capture:note"
        assert "source" not in prov  # source field removed from Provenance
        assert "at" in prov

    @pytest.mark.asyncio
    async def test_falls_back_to_ctx_now_when_no_captured_at(self) -> None:
        tdb = _fake_tdb()
        fixed_now = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        ctx = CaptureContext(tdb=tdb, blob_store=None, logger=None, now=lambda: fixed_now)
        payload = CapturePayload(kind="note", text="no timestamp")
        _iri = await captured_note_handler.handle(payload, ctx)
        tdb.insert_documents.assert_called_once()
        doc = tdb.insert_documents.call_args[0][0][0]
        assert doc["captured_at"] == "2026-01-15T10:30:00Z"
        assert doc["created_at"] == "2026-01-15T10:30:00Z"
        assert doc["updated_at"] == "2026-01-15T10:30:00Z"

    @pytest.mark.asyncio
    async def test_empty_text_defaults_to_empty_string(self) -> None:
        tdb = _fake_tdb()
        ctx = _ctx(tdb)
        payload = CapturePayload(kind="note", text=None)
        await captured_note_handler.handle(payload, ctx)
        doc = tdb.insert_documents.call_args[0][0][0]
        assert doc["content"] == ""

    @pytest.mark.asyncio
    async def test_provenance_always_present(self) -> None:
        """Every created Captured has provenance set."""
        tdb = _fake_tdb()
        ctx = _ctx(tdb)
        payload = CapturePayload(kind="note", text="hi")
        await captured_note_handler.handle(payload, ctx)
        doc = tdb.insert_documents.call_args[0][0][0]
        assert "provenance" in doc
        assert doc["provenance"]["agent"] == "service:captured"
        assert doc["provenance"]["method"] == "capture:note"

    @pytest.mark.asyncio
    async def test_contexts_default_empty_list(self) -> None:
        tdb = _fake_tdb()
        ctx = _ctx(tdb)
        payload = CapturePayload(kind="note", text="hi")
        await captured_note_handler.handle(payload, ctx)
        doc = tdb.insert_documents.call_args[0][0][0]
        # contexts is serialised by TdbDocument only if non-empty; check absence
        assert doc.get("contexts", None) is None or doc["contexts"] == []

    def test_metadata(self) -> None:
        assert captured_note_handler.name == "captured_note"
        assert captured_note_handler.kinds == ("note",)
        assert len(captured_note_handler.requires) == 1
        assert captured_note_handler.requires[0].name == "capture"
        assert captured_note_handler.requires[0].range == ">=0.1.0 <0.2.0"


class TestCapturedAudioHandler:
    @pytest.mark.asyncio
    async def test_creates_captured_from_file_payload(self, tmp_path: Path) -> None:
        tdb = _fake_tdb(["terminusdb:///data/Captured/aud1"])
        blob_path = tmp_path / "blobs" / "2026" / "07" / "ab" / "abc123def456.wav"
        blob_path.parent.mkdir(parents=True)
        blob_path.write_text("fake audio data")
        bs = _FakeBlobStore("abc123def456", blob_path)
        ctx = _ctx(tdb, blob_store=bs)
        payload = CapturePayload(
            kind="file",
            blob_sha256="abc123def456",
            filename="recording.wav",
            content_type="audio/wav",
            captured_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        )
        iri = await captured_audio_handler.handle(payload, ctx)
        assert iri == "terminusdb:///data/Captured/aud1"
        tdb.insert_documents.assert_called_once()
        doc = tdb.insert_documents.call_args[0][0][0]
        assert doc["@type"] == "Captured"
        assert doc["status"] == "new"
        assert doc["content_type"] == "audio/wav"
        assert doc["file_name"] == "recording.wav"
        assert doc["blob_sha256"] == "abc123def456"
        assert doc["captured_at"] == "2026-07-05T14:00:00Z"
        assert doc["created_at"] == "2026-07-05T14:00:00Z"
        assert doc["updated_at"] == "2026-07-05T14:00:00Z"
        # Provenance subdocument
        assert "provenance" in doc
        prov = doc["provenance"]
        assert prov["@type"] == "Provenance"
        assert prov["agent"] == "service:captured"
        assert prov["method"] == "capture:file"
        assert "at" in prov

    @pytest.mark.asyncio
    async def test_raises_when_blob_sha256_missing(self) -> None:
        tdb = _fake_tdb()
        ctx = _ctx(tdb, blob_store=_FakeBlobStore("abc", Path("/tmp")))
        payload = CapturePayload(kind="file", blob_sha256=None)
        with pytest.raises(ValueError, match="blob_sha256"):
            await captured_audio_handler.handle(payload, ctx)

    @pytest.mark.asyncio
    async def test_unnamed_file_defaults_filename(self, tmp_path: Path) -> None:
        tdb = _fake_tdb()
        blob_path = tmp_path / "blobs" / "2026" / "07" / "sh" / "sha.wav"
        blob_path.parent.mkdir(parents=True)
        blob_path.write_text("data")
        bs = _FakeBlobStore("sha", blob_path)
        ctx = _ctx(tdb, blob_store=bs)
        payload = CapturePayload(kind="file", blob_sha256="sha", filename=None)
        await captured_audio_handler.handle(payload, ctx)
        doc = tdb.insert_documents.call_args[0][0][0]
        assert doc["file_name"] == "unnamed"

    def test_metadata(self) -> None:
        assert captured_audio_handler.name == "captured_audio"
        assert captured_audio_handler.kinds == ("file",)
        assert len(captured_audio_handler.requires) == 1
        assert captured_audio_handler.requires[0].name == "capture"
        assert captured_audio_handler.requires[0].range == ">=0.1.0 <0.2.0"

    @pytest.mark.asyncio
    async def test_raises_when_blob_store_is_none(self) -> None:
        """Without a BlobStore, the handler raises RuntimeError."""
        tdb = _fake_tdb()
        ctx = _ctx(tdb, blob_store=None)
        payload = CapturePayload(kind="file", blob_sha256="abc123")
        with pytest.raises(RuntimeError, match="no BlobStore"):
            await captured_audio_handler.handle(payload, ctx)

    @pytest.mark.asyncio
    async def test_raises_when_blob_not_found(self) -> None:
        """When the blob digest is not found, the handler raises RuntimeError."""
        tdb = _fake_tdb()
        bs = _FakeBlobStore("known", Path("/tmp/known"))
        ctx = _ctx(tdb, blob_store=bs)
        payload = CapturePayload(kind="file", blob_sha256="unknown_digest")
        with pytest.raises(RuntimeError, match="unknown_digest"):
            await captured_audio_handler.handle(payload, ctx)

    @pytest.mark.asyncio
    async def test_provenance_always_present(self, tmp_path: Path) -> None:
        """Every created Captured has provenance set."""
        tdb = _fake_tdb()
        blob_path = tmp_path / "blobs" / "2026" / "07" / "sh" / "sha.wav"
        blob_path.parent.mkdir(parents=True)
        blob_path.write_text("data")
        bs = _FakeBlobStore("sha", blob_path)
        ctx = _ctx(tdb, blob_store=bs)
        payload = CapturePayload(kind="file", blob_sha256="sha", filename="test.wav")
        await captured_audio_handler.handle(payload, ctx)
        doc = tdb.insert_documents.call_args[0][0][0]
        assert "provenance" in doc
        assert doc["provenance"]["agent"] == "service:captured"
        assert doc["provenance"]["method"] == "capture:file"
