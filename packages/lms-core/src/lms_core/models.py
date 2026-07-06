"""Stable public facade — re-exports generated models and base utilities.

This module is hand-maintained.  When the generated set expands, add new
symbols here only if they should be part of the public API.
"""

from lms_core.base import TdbDateTime, TdbDocument, _format_datetime  # noqa: F401
from lms_core.generated.inbox import (  # noqa: F401
    InboxAudio,
    InboxAudioStatus,
    InboxNote,
    InboxNoteStatus,
)
from lms_core.generated.people import Contact, Person  # noqa: F401
from lms_core.generated.places import Location  # noqa: F401
from lms_core.generated.planning import (  # noqa: F401
    Event,
    EventStatus,
    Task,
    TaskSpec,
    TaskStatus,
)
from lms_core.generated.reminders import Reminder  # noqa: F401

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
    "TaskSpec",
    "TaskStatus",
]
