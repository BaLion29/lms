"""Shared base classes and utilities for TerminusDB document models.

Extracted from models.py so that both hand-written and generated models
can import from a single source.
"""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


# ---------------------------------------------------------------------------
# Datetime: ISO 8601 UTC with Z suffix
# ---------------------------------------------------------------------------


def _format_datetime(dt: datetime) -> str:
    """Convert *dt* to UTC and return ISO 8601 with ``Z`` suffix.

    Naive datetimes are treated as UTC.  Microseconds are stripped for
    deterministic output.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    dt = dt.replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


TdbDateTime = Annotated[
    datetime,
    PlainSerializer(_format_datetime, return_type=str),
]


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class TdbDocument(BaseModel):
    """Base for every TerminusDB document model.

    Provides ``@id``, ``extra="allow"`` (forward-compat, preserves unknown
    fields through round-trips) and ``to_tdb()`` which serialises with
    ``@`` aliases and omits ``None`` values.
    """

    id_: str | None = Field(alias="@id", default=None)
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_tdb(self) -> dict[str, object]:
        """Return a dict suitable for the TerminusDB document API."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")
