"""Shared models, TerminusDB client and settings base for the Firnline services.

Re-exports the most commonly used names for convenience.
"""

# Pre-load generated package to avoid circular import when
# firnline_core.generated.core is the entry-point module (e.g. during
# codegen freshness checks that import the package after regeneration).
import firnline_core.generated  # noqa: F401 (side-effect: loads all submodules)

from firnline_core.models import (
    Captured,
    CapturedStatus,
    CompositeMode,
    CompositeTrigger,
    EventKind,
    EventTrigger,
    ExternalRef,
    FiringStatus,
    OneShotTrigger,
    Provenance,
    RelativeTrigger,
    ScheduleTrigger,
    SchemaMigration,
    SchemaModule,
    Tag,
    TdbDateTime,
    TdbDocument,
    TriggerFiring,
    _format_datetime,
)
from firnline_core.conventions import (
    BlobRef,
    BlobStore,
    agent_id,
    blob_root_from_env,
    parse_agent,
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
    EvalContext,
    ExtractorPlugin,
    HostPolicy,
    HostResult,
    IndexerPlugin,
    IngestSourcePlugin,
    ModuleRequirement,
    NotificationChannel,
    NotifyContext,
    PluginHost,
    PluginSelection,
    ToolPlugin,
    TriggerEvaluator,
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
    "Captured",
    "CapturedStatus",
    "CompositeMode",
    "CompositeTrigger",
    "EventKind",
    "EventTrigger",
    "ExternalRef",
    "FiringStatus",
    "OneShotTrigger",
    "Provenance",
    "RelativeTrigger",
    "ScheduleTrigger",
    "SchemaMigration",
    "SchemaModule",
    "Tag",
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
    "agent_id",
    "blob_root_from_env",
    "parse_agent",
    "utc_now",
    # plugins
    "BuildContext",
    "CaptureContext",
    "CaptureHandler",
    "CapturePayload",
    "DeliveryResult",
    "DiscoveryResult",
    "EntityIndex",
    "EvalContext",
    "ExtractorPlugin",
    "HostPolicy",
    "HostResult",
    "IndexerPlugin",
    "IngestSourcePlugin",
    "ModuleRequirement",
    "NotificationChannel",
    "NotifyContext",
    "PluginHost",
    "PluginSelection",
    "ToolPlugin",
    "TriggerEvaluator",
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
