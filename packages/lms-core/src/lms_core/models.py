"""Pydantic v2 models mirroring the TerminusDB schema."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from lms_core.base import TdbDateTime, TdbDocument, _format_datetime  # noqa: F401 — re-exported

__all__ = [
    "TdbDateTime",
    "TdbDocument",
    "_format_datetime",
    "Contact",
    "Event",
    "EventStatus",
    "InboxAudio",
    "InboxAudioStatus",
    "InboxNote",
    "InboxNoteStatus",
    "Location",
    "Person",
    "Reminder",
    "Task",
    "TaskStatus",
]


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
