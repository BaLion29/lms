"""Shared conventions: UTC helpers, content-addressed blob storage.

Design law L6: Blob storage is content-addressed and deduplicated with atomic
writes, organised by date.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# UTC helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# BlobRef — result of a BlobStore.put call
# ---------------------------------------------------------------------------


@dataclass
class BlobRef:
    """Lightweight result describing a stored blob."""

    sha256: str
    """Hex-encoded SHA-256 digest of the blob content."""

    path: Path
    """Filesystem path where the blob is stored."""

    size: int
    """Number of bytes in the blob content."""

    mime: str | None
    """MIME type guessed from the suggested filename, or ``None``."""

    deduplicated: bool
    """``True`` when an identical blob already existed (no write performed)."""


# ---------------------------------------------------------------------------
# BlobStore
# ---------------------------------------------------------------------------


class BlobStore:
    """Content-addressed blob storage on the local filesystem.

    Blobs are organised as ``{root}/{yyyy}/{mm}/{sha256[:2]}/{sha256}{ext}``
    where *yyyy*/*mm* come from the current UTC date at write time.

    Deduplication: if a blob with the same digest already exists under *root*
    (in any ``yyyy/mm`` prefix) it is not rewritten — the existing path is
    returned instead.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    # -- public API ----------------------------------------------------------

    def put(
        self,
        data: bytes | Any,  # BinaryIO accepted at runtime (alpha limitation: read fully)
        *,
        suggested_name: str | None = None,
        ext: str = "",
    ) -> BlobRef:
        """Store *data* and return a :class:`BlobRef`.

        *data* may be ``bytes`` or any ``BinaryIO`` (which is read fully).
        This is a documented alpha limitation; future versions will stream.

        *suggested_name* is an optional filename (e.g. ``"report.pdf"``).
        Its suffix is used to derive the extension (falls back to *ext* when
        *suggested_name* is ``None`` or its suffix is unsafe).  The MIME
        type is guessed from *suggested_name* when provided.

        If a blob with the same SHA-256 digest already exists anywhere under
        ``self.root`` the write is skipped and ``BlobRef.deduplicated`` is
        ``True``.
        """
        import mimetypes

        # Read data: accept bytes or BinaryIO
        raw: bytes
        if isinstance(data, bytes):
            raw = data
        else:
            raw = data.read()

        sha256 = hashlib.sha256(raw).hexdigest()

        # Determine extension: suggested_name suffix takes precedence
        file_ext = ext
        if suggested_name is not None:
            suffix = Path(suggested_name).suffix
            if suffix and len(suffix) > 1:
                try:
                    file_ext = suffix
                    _normalise_ext(file_ext)  # validate
                except ValueError:
                    file_ext = _normalise_ext(ext)  # unsafe suffix → fall back to caller-supplied ext
            else:
                file_ext = ext if ext else ""
        elif ext:
            file_ext = _normalise_ext(ext)

        # Guess MIME type from suggested_name
        mime: str | None = None
        if suggested_name:
            guessed, _ = mimetypes.guess_type(suggested_name)
            mime = guessed

        # Check for an existing blob with the same digest (any yyyy/mm).
        existing = self.get_path(sha256)
        if existing is not None:
            return BlobRef(
                sha256=sha256,
                path=existing,
                size=len(raw),
                mime=mime,
                deduplicated=True,
            )

        # Compute target path based on the current UTC date.
        now = utc_now()
        yyyy = now.strftime("%Y")
        mm = now.strftime("%m")
        dir_path = self.root / yyyy / mm / sha256[:2]
        target = dir_path / f"{sha256}{file_ext}"

        dir_path.mkdir(parents=True, exist_ok=True)

        # Atomic write using a NamedTemporaryFile, then os.replace.
        tmp = tempfile.NamedTemporaryFile(
            dir=dir_path, delete=False, suffix=".tmp"
        )
        try:
            tmp.write(raw)
            tmp.close()
            os.replace(tmp.name, target)
        except BaseException:
            # Clean up the temp file on any failure.
            Path(tmp.name).unlink(missing_ok=True)
            raise

        return BlobRef(
            sha256=sha256,
            path=target,
            size=len(raw),
            mime=mime,
            deduplicated=False,
        )

    def get_path(self, sha256: str) -> Path | None:
        """Return the path to an existing blob, or ``None`` if not found.

        Performs a glob scan under ``self.root`` matching
        ``*/*/{sha256[:2]}/{sha256}*`` so that blobs are located regardless of
        the ``yyyy/mm`` prefix they were originally stored under.
        """
        pattern = f"*/*/{sha256[:2]}/{sha256}*"
        matches = [
            m for m in self.root.glob(pattern)
            if not m.name.endswith(".tmp")
        ]
        return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_EXT_RE = re.compile(r"^\.[A-Za-z0-9]+(\.[A-Za-z0-9]+)*$")


def _normalise_ext(ext: str) -> str:
    """Ensure *ext* starts with a dot and is safe.

    >>> _normalise_ext("pdf")
    '.pdf'
    >>> _normalise_ext(".txt")
    '.txt'
    >>> _normalise_ext("")
    ''
    >>> _normalise_ext("tar.gz")
    '.tar.gz'
    """
    if ext and not ext.startswith("."):
        ext = "." + ext
    if ext and (len(ext) > 32 or not _EXT_RE.match(ext)):
        raise ValueError(f"Unsafe or invalid extension: {ext!r}")
    return ext


# ---------------------------------------------------------------------------
# blob_root_from_env
# ---------------------------------------------------------------------------


def blob_root_from_env() -> Path | None:
    """Read ``FIRNLINE_BLOB_ROOT`` from the environment.

    Returns ``None`` when the variable is unset or empty.
    """
    raw = os.environ.get("FIRNLINE_BLOB_ROOT", "")
    return Path(raw) if raw else None
