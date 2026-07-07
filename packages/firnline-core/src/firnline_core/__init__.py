"""Shared models, TerminusDB client and settings base for the Firnline services.

Re-exports the most commonly used names for convenience.
"""

from firnline_core.models import (
    CompositeMode,
    CompositeTrigger,
    EventKind,
    EventTrigger,
    ExternalRef,
    FiringStatus,
    InboxAudio,
    InboxAudioStatus,
    InboxNote,
    InboxNoteStatus,
    OneShotTrigger,
    Provenance,
    RelativeTrigger,
    ScheduleTrigger,
    SchemaMigration,
    SchemaModule,
    TdbDateTime,
    TdbDocument,
    TriggerFiring,
    _format_datetime,
)
from firnline_core.conventions import (
    BlobRef,
    BlobStore,
    blob_root_from_env,
    utc_now,
)
from firnline_core.indexed_client import (
    ClassCandidate,
    EntityCandidate,
    FieldCandidate,
    IndexedClient,
    IndexedError,
)
from firnline_core.plugins import (
    BuildContext,
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    DeliveryResult,
    DiscoveryResult,
    EntityIndex,
    ExtractorPlugin,
    IndexerPlugin,
    IngestSourcePlugin,
    ModuleRequirement,
    NotificationChannel,
    NotifyContext,
    PluginSelection,
    ToolPlugin,
    check_requirements,
    discover_plugins,
    select_plugins,
    validate_plugin,
)
from firnline_core.semver import Range, RangeError, Version, VersionError
from firnline_core.settings import TdbSettings
from firnline_core.tdb import (
    ChangeEvent,
    TdbClient,
    TdbConflictError,
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
    "CompositeMode",
    "CompositeTrigger",
    "EventKind",
    "EventTrigger",
    "ExternalRef",
    "FiringStatus",
    "InboxAudio",
    "InboxAudioStatus",
    "InboxNote",
    "InboxNoteStatus",
    "OneShotTrigger",
    "Provenance",
    "RelativeTrigger",
    "ScheduleTrigger",
    "SchemaMigration",
    "SchemaModule",
    "TdbDateTime",
    "TdbDocument",
    "TriggerFiring",
    "_format_datetime",
    # tdb
    "ChangeEvent",
    "TdbClient",
    "TdbConflictError",
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
    "DeliveryResult",
    "DiscoveryResult",
    "EntityIndex",
    "ExtractorPlugin",
    "IndexerPlugin",
    "IngestSourcePlugin",
    "ModuleRequirement",
    "NotificationChannel",
    "NotifyContext",
    "PluginSelection",
    "ToolPlugin",
    "check_requirements",
    "discover_plugins",
    "select_plugins",
    "validate_plugin",
    # indexed client
    "ClassCandidate",
    "EntityCandidate",
    "FieldCandidate",
    "IndexedClient",
    "IndexedError",
    # tooling
    "ToolTraceEntry",
    "now_utc_str",
    "traced",
]
