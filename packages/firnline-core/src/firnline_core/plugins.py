"""Plugin protocols, requirement checking, discovery, and selection.

Design law L5: Services and plugins declare module requirements as semver
ranges, verified at startup against the in-database registry.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel

from firnline_core.conventions import BlobStore
from firnline_core.semver import Range, Version
from firnline_core.tdb import TdbError


# ---------------------------------------------------------------------------
# ModuleRequirement — a plugin's declared dependency on a schema module
# ---------------------------------------------------------------------------


class ModuleRequirement(BaseModel):
    """A single schema-module dependency with a semver range."""

    name: str
    range: str  # semver range, e.g. ">=1.0.0 <2.0.0"


# ---------------------------------------------------------------------------
# check_requirements — verify requirements against the SchemaModule registry
# ---------------------------------------------------------------------------


async def check_requirements(
    tdb: Any,
    reqs: list[ModuleRequirement],
    *,
    branch: str = "main",
) -> list[str]:
    """Return human-readable violations vs the SchemaModule registry docs.

    Each violation is a string describing one unsatisfied requirement.
    An empty list means all requirements are satisfied.

    Possible violation patterns:

    * *module missing* — ``"module 'x' not installed"``
    * *version out of range* — ``"module 'x' 1.0.0 does not satisfy '>=2.0.0'"``
    * *malformed range* — violation message (no exception raised)
    * *registry unavailable* — ``"schema module registry not available"``
      returned as a single violation when ``tdb.get_documents("SchemaModule")``
      raises ``TdbError`` (e.g. legacy database without the class).
    """
    try:
        docs: list[dict[str, Any]] = await tdb.get_documents("SchemaModule", branch=branch)
    except TdbError as exc:
        return [f"schema module registry not available: {exc.status} {exc.body}"]

    violations: list[str] = []
    installed: dict[str, Version] = {}
    for doc in docs:
        name = doc.get("name")
        version_str = doc.get("version")
        if name and version_str:
            try:
                installed[name] = Version.parse(version_str)
            except Exception:
                violations.append(f"module '{name}' has unparseable version '{version_str}'")

    for req in reqs:
        # Check malformed range
        try:
            rng = Range(req.range)
        except Exception:
            violations.append(f"module '{req.name}' has malformed range '{req.range}'")
            continue

        # Check module installed
        v = installed.get(req.name)
        if v is None:
            violations.append(f"module '{req.name}' not installed")
            continue

        # Check version in range
        if not rng.contains(v):
            violations.append(f"module '{req.name}' {v} does not satisfy '{req.range}'")

    return violations


# ---------------------------------------------------------------------------
# EntityIndex — shared type for the linking_context plugin seam
# ---------------------------------------------------------------------------


@dataclass
class EntityIndex:
    """Pre-built lookup structures for entity linking.

    ``people`` / ``locations`` are keyed by casefolded name for O(1) lookup.
    ``people_display`` / ``locations_display`` preserve the original name
    for use in prompt context blocks.
    """

    people: dict[str, str] = field(default_factory=dict)
    locations: dict[str, str] = field(default_factory=dict)
    people_display: list[tuple[str, str]] = field(default_factory=list)
    locations_display: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plugin protocols
# ---------------------------------------------------------------------------


class BuildContext:
    """Convention carrier passed to ``build_documents``.

    Fields:
        tdb: The TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        inbox_iri: The IRI of the inbox item being processed.
        now: Callable returning ``datetime`` (default: ``datetime.now``).
        create_or_link: Async callable ``(type_name, name, doc_factory) -> IRI``
            that looks up an existing entity by name or inserts via *doc_factory*.
        branch: The TDB branch for side-inserts (default: ``"main"``).
    """

    def __init__(
        self,
        tdb: Any,
        inbox_iri: str,
        *,
        now: Callable[[], datetime] | None = None,
        create_or_link: Any = None,
        branch: str = "main",
    ) -> None:
        self.tdb = tdb
        self.inbox_iri = inbox_iri
        self._now = now if now is not None else datetime.now
        self.create_or_link = create_or_link
        self.branch = branch

    def now(self) -> datetime:
        return self._now()


@runtime_checkable
class ExtractorPlugin(Protocol):
    """Protocol for ingestd extraction plugins.

    Duck-typing note: ``@runtime_checkable`` works for callable checks
    (``isinstance(obj, ExtractorPlugin)``) but attribute-only checks
    (``name``, ``requires``) are verified by convention, not at runtime.
    """

    name: str
    requires: list[ModuleRequirement]

    def proposal_models(self) -> list[type[BaseModel]]: ...

    def prompt_snippet(self) -> str: ...

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str: ...

    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict[str, Any]]: ...


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol for queryd write-tool plugins.

    Duck-typing note: same ``@runtime_checkable`` caveat as above.
    """

    name: str
    requires: list[ModuleRequirement]

    def tools(self, deps: Any) -> list[Any]:
        """Return a list of pydantic-ai ``Tool`` objects.

        Typed as ``list[Any]`` to avoid a pydantic-ai dependency in firnline-core.
        """
        ...


# ---------------------------------------------------------------------------
# Capture plugins (for the captured service)
# ---------------------------------------------------------------------------


@dataclass
class CapturePayload:
    """A single item captured by the captured HTTP endpoint.

    Fields:
        kind: Semantic kind, e.g. ``"note"`` or ``"file"``.
        text: Inline text content (when the capture is text-only).
        blob_sha256: SHA-256 digest of the blob stored via :class:`BlobStore`.
        filename: Original filename, if applicable.
        content_type: MIME type of the blob content.
        metadata: Arbitrary extra key-value pairs.
        captured_at: Optional timestamp when the capture was created.
    """

    kind: str
    text: str | None = None
    blob_sha256: str | None = None
    filename: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime | None = None


@dataclass
class CaptureContext:
    """Convention carrier passed to :meth:`CaptureHandler.handle`.

    Fields:
        tdb: A TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        blob_store: Optional :class:`~firnline_core.conventions.BlobStore` for
            retrieving blob content by digest.
        logger: A ``logging.Logger``-like object.
        now: Callable returning ``datetime`` (default: ``utc_now``).
    """

    tdb: Any
    blob_store: BlobStore | None
    logger: Any
    now: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.now is None:
            from firnline_core.conventions import utc_now as _utc_now

            self.now = _utc_now


@runtime_checkable
class CaptureHandler(Protocol):
    """Protocol for captured per-kind handler plugins.

    Duck-typing note: ``@runtime_checkable`` only verifies that the
    ``handle`` method exists; attribute checks (``name``, ``kinds``,
    ``requires``) are verified by convention.
    """

    name: str
    kinds: tuple[str, ...]
    requires: list[ModuleRequirement]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        """Process a capture and return the created document id.

        ctx provides tdb, blob store, now().
        """
        ...


@runtime_checkable
class IngestSourcePlugin(Protocol):
    """Protocol for ingestd *pull-source* plugins.

    The ingestd host owns polling and status-state transitions.  Plugin
    authors only need to provide the document-type metadata, a way to
    extract the text that will be fed to the extraction agent, and a
    reference datetime for resolving relative dates.
    """

    name: str
    requires: list[ModuleRequirement]
    document_type: str
    ready_status: str
    done_status: str
    failed_status: str

    def text(self, doc: dict) -> str:
        """Return the text that is handed to the extraction agent."""
        ...

    def reference_time(self, doc: dict) -> datetime:
        """Anchor for resolving relative dates (created_at / recorded_at)."""
        ...


# ---------------------------------------------------------------------------
# Trigger evaluator protocol (triggerd)
# ---------------------------------------------------------------------------


@dataclass
class EvalContext:
    """Convention carrier passed to :meth:`TriggerEvaluator.occurrences`.

    Fields:
        tdb: A TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        default_tz: Default ``zoneinfo.ZoneInfo`` for expanding schedule rules.
        now: Callable returning a tz-aware UTC ``datetime``.
        resolve_anchor: Async callable ``(anchor_iri_or_doc) -> datetime | None``
            that resolves a Remindable document/IRI to a temporal instant.
        get_occurrences: Async callable
            ``(trigger_dict, window_start, window_end, visited) -> list[datetime]``
            for CompositeTrigger recursion into operand sub-triggers.
    """

    tdb: Any
    default_tz: Any
    now: Callable[[], datetime]
    resolve_anchor: Callable[..., Awaitable[datetime | None]]
    get_occurrences: Callable[..., Awaitable[list[datetime]]]


@runtime_checkable
class TriggerEvaluator(Protocol):
    """Protocol for triggerd evaluator plugins.

    Each evaluator handles one or more ``@type`` entries (``trigger_types``)
    and returns scheduled fire instants for the half-open interval
    ``(window_start, window_end]``.
    """

    name: str
    requires: list[ModuleRequirement]
    trigger_types: tuple[str, ...]

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        """Return scheduled instants (tz-aware UTC) due within ``(window_start, window_end]``."""
        ...


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    """Result of ``discover_plugins``."""

    active: list[tuple[str, object]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def discover_plugins(group: str) -> DiscoveryResult:
    """Discover plugins registered under the given entry-point *group*.

    Uses ``importlib.metadata.entry_points``. Each entry-point is loaded
    independently; a plugin that fails to import is recorded in
    ``DiscoveryResult.failed`` rather than aborting discovery.

    Returns a ``DiscoveryResult`` with two lists:
    ``active`` — ``[(entry_point_name, loaded_object), ...]``
    ``failed`` — ``[(entry_point_name, error_string), ...]``
    """
    import logging
    import traceback
    from importlib.metadata import entry_points

    logger = logging.getLogger(__name__)
    result = DiscoveryResult()

    eps = entry_points(group=group)

    for ep in eps:
        try:
            obj = ep.load()
        except Exception:
            err = traceback.format_exc().strip()
            logger.warning("plugin '%s' failed to load:\n%s", ep.name, err)
            result.failed.append((ep.name, err))
        else:
            result.active.append((ep.name, obj))

    return result


# ---------------------------------------------------------------------------
# Selection (startup helper shared by ingestd and queryd)
# ---------------------------------------------------------------------------


@dataclass
class PluginSelection:
    """Result of ``select_plugins``."""

    active: list[tuple[str, object]] = field(default_factory=list)
    skipped: list[tuple[str, list[str]]] = field(default_factory=list)


async def select_plugins(
    tdb: Any,
    discovered: DiscoveryResult,
    *,
    strict: bool = False,
    branch: str = "main",
) -> PluginSelection:
    """Check requirements for every discovered plugin and return the selection.

    * **active** — plugins whose requirements are all satisfied.
    * **skipped** — ``[(name, [violation, ...]), ...]``

    When *strict* is ``True`` a ``RuntimeError`` is raised if any plugin
    was skipped or any discovery failure occurred.
    """
    selection = PluginSelection()

    for name, obj in discovered.active:
        requires: list[ModuleRequirement] = getattr(obj, "requires", [])
        violations = await check_requirements(tdb, requires, branch=branch)
        if violations:
            selection.skipped.append((name, violations))
        else:
            selection.active.append((name, obj))

    if strict and (selection.skipped or discovered.failed):
        skipped_names = [n for n, _ in selection.skipped]
        failed_names = [n for n, _ in discovered.failed]
        raise RuntimeError(f"Strict plugin mode: skipped={skipped_names}, failed={failed_names}")

    return selection
