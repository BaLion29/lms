"""Pydantic v2 models mirroring the TerminusDB schema."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


# ---------------------------------------------------------------------------
# Enums (lowercase StrEnum values matching schema)
# ---------------------------------------------------------------------------


class InboxNoteStatus(StrEnum):
    NEW = "new"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class InboxAudioStatus(StrEnum):
    NEW = "new"
    TRANSCRIBED = "transcribed"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    OPEN = "open"
    PLANNED = "planned"
    DONE = "done"


class EventStatus(StrEnum):
    OPEN = "open"
    PLANNED = "planned"
    CLOSED = "closed"
    CANCELLED = "cancelled"


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

    Provides ``@id``, ``extra="ignore"`` (forward-compat) and
    ``to_tdb()`` which serialises with ``@`` aliases and omits ``None``
    values.
    """

    id_: str | None = Field(alias="@id", default=None)
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    def to_tdb(self) -> dict[str, object]:
        """Return a dict suitable for the TerminusDB document API."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


# ---------------------------------------------------------------------------
# Document models (flat, no schema-inheritance mirroring)
# ---------------------------------------------------------------------------


class InboxNote(TdbDocument):
    type_: Literal["InboxNote"] = Field(alias="@type", default="InboxNote")
    content: str
    status: InboxNoteStatus
    created_at: TdbDateTime
    updated_at: TdbDateTime


class InboxAudio(TdbDocument):
    type_: Literal["InboxAudio"] = Field(alias="@type", default="InboxAudio")
    file_name: str
    file_path: str
    transcription: str
    recorded_at: TdbDateTime
    status: InboxAudioStatus
    created_at: TdbDateTime
    updated_at: TdbDateTime


class Task(TdbDocument):
    type_: Literal["Task"] = Field(alias="@type", default="Task")
    name: str
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    required_context: list[str] = Field(default_factory=list)
    due_date: TdbDateTime | None = None
    status: TaskStatus
    derived_from: str | None = None
    created_at: TdbDateTime
    updated_at: TdbDateTime


class Event(TdbDocument):
    type_: Literal["Event"] = Field(alias="@type", default="Event")
    name: str
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    start_datetime: TdbDateTime | None = None
    end_datetime: TdbDateTime | None = None
    location: str | None = None
    status: EventStatus
    derived_from: str | None = None
    created_at: TdbDateTime
    updated_at: TdbDateTime


class Reminder(TdbDocument):
    type_: Literal["Reminder"] = Field(alias="@type", default="Reminder")
    name: str
    description: str | None = None
    priority: int | None = None
    refers_to: str | None = None
    trigger: str | None = None
    derived_from: str | None = None
    created_at: TdbDateTime
    updated_at: TdbDateTime


class Contact(TdbDocument):
    """@subdocument – nested inline in ``Person.contact``."""

    type_: Literal["Contact"] = Field(alias="@type", default="Contact")
    email: str | None = None
    phone: str | None = None
    domicile: str | None = None


class Person(TdbDocument):
    type_: Literal["Person"] = Field(alias="@type", default="Person")
    name: str
    contact: Contact | None = None


class Location(TdbDocument):
    type_: Literal["Location"] = Field(alias="@type", default="Location")
    name: str
    address: str | None = None
    aliases: list[str] = Field(default_factory=list)
    # xdd:coordinate is deliberately omitted (v1 does not write it)
