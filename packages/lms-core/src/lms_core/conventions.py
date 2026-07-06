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

    def put(self, data: bytes, ext: str = "") -> BlobRef:
        """Store *data* and return a :class:`BlobRef`.

        *ext* is normalised: if non-empty and lacking a leading dot, one is
        prepended (e.g. ``"pdf"`` → ``".pdf"``).  Pass ``""`` for extension-less
        blobs.

        If a blob with the same SHA-256 digest already exists anywhere under
        ``self.root`` the write is skipped and ``BlobRef.deduplicated`` is
        ``True``.
        """
        sha256 = hashlib.sha256(data).hexdigest()
        ext = _normalise_ext(ext)

        # Check for an existing blob with the same digest (any yyyy/mm).
        existing = self.get_path(sha256)
        if existing is not None:
            return BlobRef(sha256=sha256, path=existing, deduplicated=True)

        # Compute target path based on the current UTC date.
        now = utc_now()
        yyyy = now.strftime("%Y")
        mm = now.strftime("%m")
        dir_path = self.root / yyyy / mm / sha256[:2]
        target = dir_path / f"{sha256}{ext}"

        dir_path.mkdir(parents=True, exist_ok=True)

        # Atomic write using a NamedTemporaryFile, then os.replace.
        tmp = tempfile.NamedTemporaryFile(
            dir=dir_path, delete=False, suffix=".tmp"
        )
        try:
            tmp.write(data)
            tmp.close()
            os.replace(tmp.name, target)
        except BaseException:
            # Clean up the temp file on any failure.
            Path(tmp.name).unlink(missing_ok=True)
            raise

        return BlobRef(sha256=sha256, path=target, deduplicated=False)

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
    """Read ``LMS_BLOB_ROOT`` from the environment.

    Returns ``None`` when the variable is unset or empty.
    """
    raw = os.environ.get("LMS_BLOB_ROOT", "")
    return Path(raw) if raw else None
