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
from lms_core.conventions import (
    BlobRef,
    BlobStore,
    blob_root_from_env,
    utc_now,
)
from lms_core.plugins import (
    BuildContext,
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    DiscoveryResult,
    EntityIndex,
    ExtractorPlugin,
    IngestSourcePlugin,
    ModuleRequirement,
    PluginSelection,
    ToolPlugin,
    check_requirements,
    discover_plugins,
    select_plugins,
)
from lms_core.semver import Range, RangeError, Version, VersionError
from lms_core.settings import TdbSettings
from lms_core.tdb import (
    TdbClient,
    TdbError,
    full_iri,
    short_iri,
)
from lms_core.tooling import (
    ToolTraceEntry,
    now_utc_str,
    traced,
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
    # semver
    "Range",
    "RangeError",
    "Version",
    "VersionError",
    # conventions
    "BlobRef",
    "BlobStore",
    "blob_root_from_env",
    "utc_now",
    # plugins
    "BuildContext",
    "CaptureContext",
    "CaptureHandler",
    "CapturePayload",
    "DiscoveryResult",
    "EntityIndex",
    "ExtractorPlugin",
    "IngestSourcePlugin",
    "ModuleRequirement",
    "PluginSelection",
    "ToolPlugin",
    "check_requirements",
    "discover_plugins",
    "select_plugins",
    # tooling
    "ToolTraceEntry",
    "now_utc_str",
    "traced",
]
