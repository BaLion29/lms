"""Tests for lms_core.conventions — UTC helpers, BlobStore, blob_root_from_env."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lms_core.conventions import (
    BlobRef,
    BlobStore,
    blob_root_from_env,
    utc_now,
)


# ---------------------------------------------------------------------------
# utc_now
# ---------------------------------------------------------------------------


class TestUtcNow:
    def test_returns_tz_aware_utc(self) -> None:
        now = utc_now()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None
        assert now.tzinfo.utcoffset(now) is not None
        assert now.utcoffset() is not None  # type: ignore[union-attr]
        # Quick sanity: should be close to current time
        delta = abs((datetime.now(timezone.utc) - now).total_seconds())
        assert delta < 5


# ---------------------------------------------------------------------------
# BlobStore
# ---------------------------------------------------------------------------


class TestBlobStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> BlobStore:
        return BlobStore(root=tmp_path)

    def test_put_stores_at_expected_path(self, store: BlobStore) -> None:
        data = b"hello world"
        ref = store.put(data)

        assert isinstance(ref, BlobRef)
        assert ref.sha256 == (
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )
        assert ref.size == len(data)
        assert ref.mime is None  # no suggested_name
        assert ref.deduplicated is False
        assert ref.path.exists()
        assert ref.path.read_bytes() == data

        # Path follows {root}/{yyyy}/{mm}/{sha256[:2]}/{sha256}
        rel = ref.path.relative_to(store.root)
        parts = rel.parts
        assert len(parts) == 4  # yyyy / mm / xx / fullsha256
        now = utc_now()
        assert parts[0] == now.strftime("%Y")
        assert parts[1] == now.strftime("%m")
        assert parts[2] == ref.sha256[:2]
        assert parts[3] == ref.sha256

    def test_same_bytes_twice_deduplicates(self, store: BlobStore) -> None:
        data = b"dedup test"
        ref1 = store.put(data)
        ref2 = store.put(data)

        assert ref2.deduplicated is True
        assert ref2.sha256 == ref1.sha256
        assert ref2.path == ref1.path

    def test_ext_normalisation(self, store: BlobStore) -> None:
        ref = store.put(b"pdf content", ext="pdf")
        assert ref.path.suffix == ".pdf"
        assert ref.path.name.endswith(".pdf")

        ref2 = store.put(b"pdf content 2", ext=".txt")
        assert ref2.path.suffix == ".txt"

        ref3 = store.put(b"no ext", ext="")
        assert ref3.path.suffix == ""

    def test_suggested_name_derives_ext_and_mime(self, store: BlobStore) -> None:
        ref = store.put(b"hello", suggested_name="report.pdf")
        assert ref.path.suffix == ".pdf"
        assert ref.mime == "application/pdf"

    def test_suggested_name_no_ext(self, store: BlobStore) -> None:
        ref = store.put(b"hello", suggested_name="README")
        assert ref.path.suffix == ""

    def test_suggested_name_takes_precedence_over_ext(self, store: BlobStore) -> None:
        ref = store.put(b"hello", suggested_name="notes.txt", ext="pdf")
        assert ref.path.suffix == ".txt"

    def test_unsafe_suggested_name_falls_back_extensionless(self, store: BlobStore) -> None:
        ref = store.put(b"payload", suggested_name="evil.t<x>t")
        assert ref.path.suffix == ""

    def test_unsafe_suggested_name_falls_back_to_ext(self, store: BlobStore) -> None:
        ref = store.put(b"payload", suggested_name="evil.t<x>t", ext=".txt")
        assert ref.path.suffix == ".txt"

    def test_stream_input(self, store: BlobStore) -> None:
        import io
        stream = io.BytesIO(b"stream data")
        ref = store.put(stream, suggested_name="data.bin")
        assert ref.sha256 == hashlib.sha256(b"stream data").hexdigest()
        assert ref.size == 11
        assert ref.deduplicated is False

    def test_suggested_name_mime_text(self, store: BlobStore) -> None:
        ref = store.put(b"text", suggested_name="notes.txt")
        assert ref.mime == "text/plain"

    def test_suggested_name_mime_html(self, store: BlobStore) -> None:
        ref = store.put(b"<html></html>", suggested_name="page.html")
        assert ref.mime == "text/html"

    def test_get_path_finds_blob(self, store: BlobStore) -> None:
        ref = store.put(b"find me")
        found = store.get_path(ref.sha256)
        assert found == ref.path

    def test_get_path_returns_none_for_unknown_digest(self, store: BlobStore) -> None:
        result = store.get_path(
            "0000000000000000000000000000000000000000000000000000000000000000"
        )
        assert result is None

    def test_dedup_across_different_dates(self, store: BlobStore) -> None:
        """Simulate a blob stored under an older yyyy/mm being deduplicated."""
        data = b"cross-date blob"

        # First put under a fake old date by bypassing the normal path logic.
        import hashlib

        sha256 = hashlib.sha256(data).hexdigest()
        old_path = store.root / "2020" / "01" / sha256[:2] / sha256
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(data)

        # Now put from "today" — should find the old blob.
        ref = store.put(data)
        assert ref.deduplicated is True
        assert ref.path == old_path

    def test_get_path_finds_blob_in_old_date(self, store: BlobStore) -> None:
        data = b"old-date find"
        import hashlib

        sha256 = hashlib.sha256(data).hexdigest()
        old_path = store.root / "2021" / "06" / sha256[:2] / f"{sha256}.json"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(data)

        found = store.get_path(sha256)
        assert found is not None
        assert found.name.startswith(sha256)

    def test_put_cleanup_temp_on_failure(self, store: BlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
        """If os.replace fails, no .tmp file should remain."""
        import os

        def _failing_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", _failing_replace)

        with pytest.raises(OSError, match="simulated replace failure"):
            store.put(b"temp cleanup")

        # No stray .tmp files anywhere under root.
        tmps = list(store.root.glob("**/*.tmp"))
        assert len(tmps) == 0

    @pytest.mark.parametrize(
        "ext",
        ["/../../x", "a/b", "..", "x" * 40, "\\\\path", "a\\.txt"],
    )
    def test_unsafe_ext_raises_value_error(
        self, store: BlobStore, ext: str
    ) -> None:
        with pytest.raises(ValueError):
            store.put(b"x", ext=ext)

    def test_tmp_file_not_returned_by_get_path(
        self, store: BlobStore
    ) -> None:
        """get_path ignores .tmp files."""
        import hashlib

        data = b"orphan tmp test"
        sha256 = hashlib.sha256(data).hexdigest()
        now = utc_now()
        dir_path = (
            store.root
            / now.strftime("%Y")
            / now.strftime("%m")
            / sha256[:2]
        )
        dir_path.mkdir(parents=True, exist_ok=True)
        # Plant only a .tmp file — no real blob.
        tmp_path = dir_path / f"{sha256}.tmp"
        tmp_path.write_bytes(b"partial write")
        assert store.get_path(sha256) is None
        # Now plant a real blob as well; get_path returns the real one.
        real_path = dir_path / sha256
        real_path.write_bytes(data)
        found = store.get_path(sha256)
        assert found == real_path

    def test_tmp_file_does_not_trigger_dedup(
        self, store: BlobStore
    ) -> None:
        """A .tmp file with matching prefix does not cause false dedup."""
        data = b"dedup with tmp noise"
        ref = store.put(data)
        # Plant a .tmp file next to the real blob.
        tmp_path = ref.path.with_name(ref.path.name + ".tmp")
        tmp_path.write_bytes(b"crashed write")
        # Dedup should still find the real blob.
        ref2 = store.put(data)
        assert ref2.deduplicated is True
        assert ref2.path == ref.path


# ---------------------------------------------------------------------------
# blob_root_from_env
# ---------------------------------------------------------------------------


class TestBlobRootFromEnv:
    def test_returns_path_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LMS_BLOB_ROOT", "/tmp/my-blobs")
        result = blob_root_from_env()
        assert result == Path("/tmp/my-blobs")

    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LMS_BLOB_ROOT", raising=False)
        result = blob_root_from_env()
        assert result is None

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LMS_BLOB_ROOT", "")
        result = blob_root_from_env()
        assert result is None
