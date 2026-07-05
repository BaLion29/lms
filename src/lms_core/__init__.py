"""Shared models, TerminusDB client and settings base for the LMS services.

Re-exports the most commonly used names for convenience.
"""

from lms_core.models import (
    Contact,
    Event,
    EventStatus,
    InboxAudio,
    InboxAudioStatus,
    InboxNote,
    InboxNoteStatus,
    Location,
    Person,
    Reminder,
    Task,
    TaskStatus,
    TdbDateTime,
    TdbDocument,
    _format_datetime,
)
from lms_core.settings import TdbSettings
from lms_core.tdb import (
    TdbClient,
    TdbError,
    full_iri,
    short_iri,
)

__all__ = [
    # models
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
    "TdbDateTime",
    "TdbDocument",
    "_format_datetime",
    # tdb
    "TdbClient",
    "TdbError",
    "full_iri",
    "short_iri",
    # settings
    "TdbSettings",
]
