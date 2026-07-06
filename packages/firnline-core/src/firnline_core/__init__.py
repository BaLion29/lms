"""Shared models, TerminusDB client and settings base for the Firnline services.

Re-exports the most commonly used names for convenience.
"""

from firnline_core.models import (
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
from firnline_core.conventions import (
    BlobRef,
    BlobStore,
    blob_root_from_env,
    utc_now,
)
from firnline_core.plugins import (
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
from firnline_core.semver import Range, RangeError, Version, VersionError
from firnline_core.settings import TdbSettings
from firnline_core.tdb import (
    TdbClient,
    TdbError,
    full_iri,
    short_iri,
)
from firnline_core.tooling import (
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
