"""Plugin protocols, requirement checking, discovery, and selection.

Design law L5: Services and plugins declare module requirements as semver
ranges, verified at startup against the in-database registry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Hashable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel

import httpx

from firnline_core.conventions import BlobStore, utc_now
from firnline_core.semver import Range, Version
from firnline_core.tdb import TdbError

_REGISTRY_ERRORS: tuple[type[BaseException], ...] = (TdbError, OSError, httpx.HTTPError)


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
    registry: list[dict[str, Any]] | None = None,
    required_classes: list[str] | None = None,
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
    * *class not exported* — ``"class 'X' not exported by any installed module"``
    * *legacy registry* — ``"registry has no exports information; reinstall schema modules"``

    When *registry* is provided (a pre-fetched list of SchemaModule docs),
    the database fetch is skipped and *registry* is used directly.

    *required_classes* is an optional list of class ``@id`` strings that must
    appear in the union of ``exports`` across all installed SchemaModule docs.
    When provided and no registry doc carries an ``exports`` field, a legacy-
    registry violation is emitted.
    """
    if registry is None:
        try:
            docs: list[dict[str, Any]] = await tdb.get_documents("SchemaModule", branch=branch)
        except _REGISTRY_ERRORS as exc:
            return [f"schema module registry not available: {exc}"]
    else:
        docs = registry

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

    # --- class-export checks ---
    if required_classes is not None:
        all_exports: set[str] = set()
        any_exports = False
        legacy_modules: list[str] = []
        for doc in docs:
            name = doc.get("name")
            exports = doc.get("exports")
            if exports is not None:
                any_exports = True
                if isinstance(exports, list):
                    for cls_id in exports:
                        if isinstance(cls_id, str):
                            all_exports.add(cls_id)
            elif isinstance(name, str):
                legacy_modules.append(name)

        if not any_exports:
            violations.append("registry has no exports information; reinstall schema modules")
        else:
            for cls in required_classes:
                if cls not in all_exports:
                    msg = f"class '{cls}' not exported by any installed module"
                    if legacy_modules:
                        msg += (
                            f" (modules {', '.join(sorted(legacy_modules))}"
                            " predate exports metadata and may need reinstall)"
                        )
                    violations.append(msg)

    return violations


# ---------------------------------------------------------------------------
# EntityIndex — shared type for the linking_context plugin seam
# ---------------------------------------------------------------------------


@dataclass
class EntityIndex:
    """Generic lookup structures for entity linking, keyed by class name.

    ``entities`` — ``{class_name: {casefolded_name: IRI}}``
    ``display`` — ``{class_name: [(original_name, IRI)]}``
    """

    entities: dict[str, dict[str, str]] = field(default_factory=dict)
    display: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def register(self, class_name: str, name: str, iri: str) -> None:
        """Add *name* → *iri* for *class_name*.  Name is casefolded for
        lookup, original is preserved in display."""
        self.entities.setdefault(class_name, {})[name.casefold()] = iri
        self.display.setdefault(class_name, []).append((name, iri))

    def lookup(self, class_name: str, name: str) -> str | None:
        """Casefolded exact-match lookup.  Returns the IRI or ``None``."""
        return self.entities.get(class_name, {}).get(name.casefold())

    def names(self, class_name: str) -> list[tuple[str, str]]:
        """Return the display list for *class_name* (empty list if none)."""
        return self.display.get(class_name, [])

    def classes(self) -> list[str]:
        """Return the list of registered class names."""
        return list(self.entities.keys())


# ---------------------------------------------------------------------------
# Plugin protocols
# ---------------------------------------------------------------------------


class BuildContext:
    """Convention carrier passed to ``build_documents``.

    Fields:
        tdb: The TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        captured_iri: The IRI of the entity being processed.
        now: Callable returning ``datetime`` (default: ``utc_now`` (tz-aware UTC)).
        ensure_entity: ``async ensure_entity(type_name: str, name: str, factory: Callable[[], dict | None]) -> str | None``
            Resolves an entity by name via the generic index / match service, or
            creates it with a client-supplied ``@id`` and queues it in the current
            batch; returns the IRI immediately (``None`` only if *factory* returns
            ``None`` and no match is found).
        branch: The TDB branch for side-inserts (default: ``"main"``).
    """

    def __init__(
        self,
        tdb: Any,
        captured_iri: str,
        *,
        now: Callable[[], datetime] | None = None,
        ensure_entity: Any = None,
        branch: str = "main",
    ) -> None:
        self.tdb = tdb
        self.captured_iri = captured_iri
        self._now = now if now is not None else utc_now
        self.ensure_entity = ensure_entity
        self.branch = branch

    def now(self) -> datetime:
        return self._now()


@runtime_checkable
class ExtractorPlugin(Protocol):
    """Protocol for ingestd extraction plugins.

    Duck-typing note: ``@runtime_checkable`` works for callable checks
    (``isinstance(obj, ExtractorPlugin)``) but attribute-only checks
    (``name``, ``requires``, ``produces``) are verified by convention, not at runtime.
    """

    name: str
    requires: list[ModuleRequirement]
    produces: list[str]

    def proposal_models(self) -> list[type[BaseModel]]: ...

    def prompt_snippet(self) -> str: ...

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str: ...

    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict[str, Any]]: ...


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol for queryd write-tool plugins.

    .. deprecated::
        Use :class:`ToolSpecPlugin` for new plugins; ``ToolPlugin`` is
        kept for backward compatibility and will be removed in a future
        release.  The canonical interface is :meth:`ToolSpecPlugin.tool_specs`.

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
# Tool-spec protocol — framework-neutral tool contract
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolSpecPlugin(Protocol):
    """Protocol for queryd tool plugins exposing framework-neutral :class:`~firnline_core.toolspec.ToolSpec` objects.

    This is the **canonical** interface for write-tool plugins.
    Unlike :class:`ToolPlugin` (which returns pydantic-ai ``Tool`` objects
    and carries a pydantic-ai dependency), :class:`ToolSpecPlugin` is
    framework-neutral so tools can be exposed over REST, MCP, or other
    transports.

    Discovery note: ``ToolSpecPlugin`` is a separate protocol from
    ``ToolPlugin`` — plugins may implement either (or both).
    ``PluginHost`` validates against whatever protocol the service
    passes to it, so no existing plugin is broken by the new protocol.
    """

    name: str
    requires: list[ModuleRequirement]

    def tool_specs(self) -> list[Any]:
        """Return a list of :class:`~firnline_core.toolspec.ToolSpec` objects.

        Typed as ``list[Any]`` to avoid a pydantic-ai dependency in
        firnline-core.
        """
        ...


# ---------------------------------------------------------------------------
# WebUI page plugin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class WebUIPagePlugin(Protocol):
    """Protocol for WebUI page plugins.

    Entry-point group: ``firnline.webui.pages``

    Plugins implementing this protocol provide
    :class:`~firnline_core.pagespec.PageSpec` objects that the WebUI
    service mounts as reflex pages.  Each page declares a route, title,
    component factory, and optional navigation metadata.
    """

    name: str
    requires: list[ModuleRequirement]

    def pages(self) -> list[Any]:
        """Return a list of :class:`~firnline_core.pagespec.PageSpec` objects.

        Typed as ``list[Any]`` to keep firnline-core free of a reflex
        dependency.
        """
        ...


# ---------------------------------------------------------------------------
# TUI screen plugin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TuiScreenPlugin(Protocol):
    """Protocol for TUI screen plugins.

    Entry-point group: ``firnline.tui.screens``

    Plugins implementing this protocol provide
    :class:`~firnline_core.screenspec.ScreenSpec` objects that the TUI
    service installs as Textual screens.
    """

    name: str
    requires: list[ModuleRequirement]

    def screens(self) -> list[Any]:
        """Return a list of ScreenSpec objects (typed Any to keep
        firnline-core free of a textual dependency)."""
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
        """Anchor for resolving relative dates (e.g. captured_at / recorded_at)."""
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
            that resolves an Anchored document/IRI to a temporal instant.
        get_occurrences: Async callable
            ``(trigger_dict, window_start, window_end, visited) -> list[datetime]``
            for CompositeTrigger recursion into operand sub-triggers.
        changes: ``list[Any]`` — list of ``firnline_core.tdb.ChangeEvent`` for
            the current evaluation window; EventTrigger-style evaluators consume it.
    """

    tdb: Any
    default_tz: Any
    now: Callable[[], datetime]
    resolve_anchor: Callable[..., Awaitable[datetime | None]]
    get_occurrences: Callable[..., Awaitable[list[datetime]]]
    changes: list[Any] = field(default_factory=list)


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
# Indexer plugin protocol (indexed service)
# ---------------------------------------------------------------------------


@runtime_checkable
class IndexerPlugin(Protocol):
    """Protocol for ``indexed`` service indexer plugins.

    Each extension that wants its entities searchable implements this and
    registers it under ``firnline.indexed.indexers``.  The indexed service
    discovers plugins at startup and mirrors the declared document classes
    into the hybrid search index.
    """

    name: str
    requires: list[ModuleRequirement]

    def indexed_classes(self) -> list[str]:
        """Return the TerminusDB class names (``@id`` values) to mirror."""
        ...

    def entity_text(self, doc: dict[str, Any]) -> str:
        """Return the searchable text for *doc*.

        This is what gets vectorised / embedded. Should be a concise
        human-readable summary of the document's distinguishing content.
        """
        ...

    def entity_name(self, doc: dict[str, Any]) -> str:
        """Return the bare display name of *doc*.

        This is the primary label for the entity (e.g. a person's name),
        used for candidate labels in search results.
        """
        ...

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        """Return additional lexical keys for *doc*.

        Aliases participate in exact, FTS, and alias-matching alongside
        the primary ``entity_text``.  Use for alternate names,
        abbreviations, or transliterations.
        """
        ...


# ---------------------------------------------------------------------------
# Protocol validation
# ---------------------------------------------------------------------------


def validate_plugin(obj: object, protocol: type) -> list[str]:
    """Return human-readable violations when *obj* fails *protocol* conformance.

    For the given ``@runtime_checkable`` Protocol, checks that every
    non-callable protocol member exists on *obj* and every method member
    exists and is callable.

    Returns an empty list when *obj* passes all checks.
    """
    violations: list[str] = []
    data_members: set[str] = set()

    # Data members: from __annotations__ (skip dunders and _abc internals)
    for attr_name in getattr(protocol, "__annotations__", {}):
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        if attr_name.startswith("_abc_"):
            continue
        data_members.add(attr_name)
        if not hasattr(obj, attr_name):
            violations.append(f"missing attribute '{attr_name}'")

    # Method members: from vars(protocol) — Protocol objects store methods
    # in their class dict.  Skip dunders, _abc internals, and data members.
    for member_name, member_value in vars(protocol).items():
        if member_name.startswith("__") and member_name.endswith("__"):
            continue
        if member_name.startswith("_abc_"):
            continue
        if member_name in data_members:
            continue  # already handled as data member
        if callable(member_value):
            if not hasattr(obj, member_name):
                violations.append(f"missing method '{member_name}'")
            elif not callable(getattr(obj, member_name)):
                violations.append(f"attribute '{member_name}' is not callable")

    return violations


# ---------------------------------------------------------------------------
# Action execution contracts (effectd seam)
# ---------------------------------------------------------------------------
# Entry-point group convention: "firnline.effectd.executors"


@dataclass
class ExecutionResult:
    """Outcome of an external-effect execution attempt.

    Fields:
        ok: ``True`` if the effect was successfully executed.
        detail: Human-readable status or error description.
        retryable: ``False`` + ``not ok`` → terminal failure for this attempt
            path. ``True`` + ``not ok`` → the effect may succeed on retry.
        external_ref: Optional id / URL of the created external effect.
    """

    ok: bool
    detail: str = ""
    retryable: bool = False
    external_ref: str | None = None


@dataclass
class ActionContext:
    """Convention carrier passed to :meth:`ActionExecutor.execute`.

    Fields:
        tdb: A TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        logger: A ``logging.Logger``-like object.
        now: Callable returning a tz-aware UTC ``datetime``
            (default: :func:`~firnline_core.conventions.utc_now`).
        idempotency_key: Stable per (action, firing); executors SHOULD pass it
            downstream for exactly-once semantics.
        dry_run: When ``True``, executors MUST NOT produce side effects.
    """

    tdb: Any
    logger: Any
    now: Callable[[], datetime] = utc_now
    idempotency_key: str = ""
    dry_run: bool = False


@runtime_checkable
class ActionExecutor(Protocol):
    """Executes one kind of external effect.

    Entry-point group: ``firnline.effectd.executors``

    *kinds* are executor-kind strings matched against ``Action.executor``
    (e.g. ``("notify:gotify",)``, ``("webhook",)``, ``("hass",)``).
    Collisions between active executors on the same kind are fatal at startup.
    """

    name: str
    requires: list[ModuleRequirement]
    kinds: tuple[str, ...]

    async def execute(
        self,
        action: dict[str, Any],
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: ActionContext,
    ) -> ExecutionResult: ...


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
    protocol: type | None = None,
    registry: list[dict[str, Any]] | None = None,
) -> PluginSelection:
    """Check requirements for every discovered plugin and return the selection.

    * **active** — plugins whose requirements are all satisfied.
    * **skipped** — ``[(name, [violation, ...]), ...]``

    When *strict* is ``True`` a ``RuntimeError`` is raised if any plugin
    was skipped or any discovery failure occurred.

    When *protocol* is provided, each plugin is additionally validated
    against the given ``@runtime_checkable`` Protocol via
    :func:`validate_plugin` — structural violations are treated like
    requirement violations (plugin skipped, raised in strict mode).

    When *registry* is provided (a pre-fetched list of SchemaModule docs),
    the database fetch is skipped.  This is the seam for services that
    pre-fetch the registry once.
    """
    # Fetch the SchemaModule registry once and reuse across all plugins.
    registry_error: str | None = None
    if registry is None:
        try:
            registry = await tdb.get_documents("SchemaModule", branch=branch)
        except TdbError as exc:
            registry = None
            registry_error = f"schema module registry not available: {exc.status} {exc.body}"

    selection = PluginSelection()

    for name, obj in discovered.active:
        violations: list[str] = []
        if registry_error is not None:
            violations.append(registry_error)
        else:
            requires: list[ModuleRequirement] = getattr(obj, "requires", [])
            requires_classes: list[str] = getattr(obj, "requires_classes", [])
            violations.extend(
                await check_requirements(
                    tdb,
                    requires,
                    branch=branch,
                    registry=registry,
                    required_classes=requires_classes or None,
                )
            )
        if protocol is not None:
            violations.extend(validate_plugin(obj, protocol))
        if violations:
            selection.skipped.append((name, violations))
        else:
            selection.active.append((name, obj))

    if strict and (selection.skipped or discovered.failed):
        skipped_names = [n for n, _ in selection.skipped]
        failed_names = [n for n, _ in discovered.failed]
        raise RuntimeError(f"Strict plugin mode: skipped={skipped_names}, failed={failed_names}")

    return selection


# ---------------------------------------------------------------------------
# PluginHost — canonical startup helper
# ---------------------------------------------------------------------------


@dataclass
class HostPolicy:
    """Policy flags controlling :class:`PluginHost` behaviour.

    Fields:
        broken_entry_point_fatal: If ``True`` (default), a broken entry-point
            raises ``RuntimeError``.  When ``False`` failures are logged as
            warnings and processing continues.
        zero_active_fatal: If ``True``, an empty active-plugin list raises
            ``RuntimeError``.  Default ``False`` — a warning is logged.
        strict: Propagated to :func:`select_plugins`; skipped plugins are fatal.
        tdb_unavailable_fatal: If ``True`` (default), a failing registry fetch
            raises immediately.  When ``False``, the plugin host returns a
            ``HostResult`` with every discovered plugin in ``skipped`` and an
            empty active list (graceful degradation).
    """

    broken_entry_point_fatal: bool = True
    zero_active_fatal: bool = False
    strict: bool = False
    tdb_unavailable_fatal: bool = True


@dataclass
class HostResult:
    """Result returned by :meth:`PluginHost.start`.

    Fields:
        active: ``[(entry_point_name, plugin_object), ...]`` — plugins that
            passed requirement checks, structural validation, and collision
            detection.
        skipped: ``[(name, [violation, ...]), ...]`` — plugins that were
            discovered but filtered out by requirement or validation failures.
        failed: ``[(entry_point_name, error_string), ...]`` — plugins whose
            entry-point ``load()`` raised an exception during discovery.
    """

    active: list[tuple[str, object]] = field(default_factory=list)
    skipped: list[tuple[str, list[str]]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


class PluginHost:
    """Encapsulate the canonical plugin startup sequence.

    Pattern::

        host = PluginHost(group="firnline.my.group", protocol=MyProto, tdb=tdb,
                          policy=HostPolicy())
        result = await host.start(collision_key=lambda p: p.my_keys)

    The sequence is: discover → broken-entry-point policy → select
    (requirements + structural validation) → collision check → log.
    """

    def __init__(
        self,
        *,
        group: str,
        protocol: type | None,
        tdb: Any,
        branch: str = "main",
        policy: HostPolicy | None = None,
        logger: Any = None,
    ) -> None:
        self._group = group
        self._protocol = protocol
        self._tdb = tdb
        self._branch = branch
        self._policy = policy or HostPolicy()
        self._logger = logger or logging.getLogger(__name__)

    async def start(
        self,
        *,
        collision_key: Callable[[Any], Iterable[Hashable]] | None = None,
        registry: list[dict[str, Any]] | None = None,
        discovered: DiscoveryResult | None = None,
    ) -> HostResult:
        """Run the startup sequence and return a :class:`HostResult`.

        Parameters:
            collision_key: Optional callable ``(plugin_obj) -> Iterable[Hashable]``.
                If two active plugins produce an overlapping key, ``RuntimeError``
                is raised naming both plugins and the colliding key.
            registry: Optional pre-fetched list of SchemaModule docs.  When
                provided the database call inside :func:`select_plugins` is
                skipped.
            discovered: Optional pre-built :class:`DiscoveryResult`.  When
                provided, entry-point discovery is skipped (test seam).
        """
        # ── Discover ────────────────────────────────────────────────
        if discovered is None:
            discovered = discover_plugins(self._group)
            self._logger.info(
                "plugin_discovered group=%s count=%d failed_count=%d",
                self._group,
                len(discovered.active),
                len(discovered.failed),
            )

        # ── Broken entry-point policy ───────────────────────────────
        if discovered.failed:
            names = [n for n, _ in discovered.failed]
            if self._policy.broken_entry_point_fatal:
                raise RuntimeError(f"Plugin entry points failed to load in group '{self._group}': {names}")
            for name, err in discovered.failed:
                self._logger.warning(
                    "plugin_load_failed plugin=%s error=%s",
                    name,
                    err.split("\n")[-1],
                )

        # ── Fetch registry (unless pre-fetched) ─────────────────────
        selection: PluginSelection | None = None
        if registry is None:
            try:
                registry = await self._tdb.get_documents("SchemaModule", branch=self._branch)
            except _REGISTRY_ERRORS as exc:
                if self._policy.tdb_unavailable_fatal:
                    raise
                self._logger.warning(
                    "plugin_registry_unavailable error=%s group=%s",
                    str(exc),
                    self._group,
                )
                reason = f"registry unavailable: {exc}"
                # Degraded path: all plugins skipped, still honor
                # collision checks, zero_active_fatal, and logging.
                selection = PluginSelection(
                    active=[],
                    skipped=[(name, [reason]) for name, _ in discovered.active],
                )
                # Fall through to the shared policy/collision/logging stage.
                # Registry stays None so select_plugins won't re-fetch.

        else:
            # Registry was pre-fetched.
            pass

        # ── Select (requirements + validation) ──────────────────────
        if selection is None:
            try:
                selection = await select_plugins(
                    self._tdb,
                    discovered,
                    strict=self._policy.strict,
                    branch=self._branch,
                    protocol=self._protocol,
                    registry=registry,
                )
            except RuntimeError:
                raise
            except _REGISTRY_ERRORS as exc:
                if self._policy.tdb_unavailable_fatal:
                    raise
                self._logger.warning(
                    "plugin_registry_unavailable error=%s group=%s",
                    str(exc),
                    self._group,
                )
                reason = f"registry unavailable: {exc}"
                selection = PluginSelection(
                    active=[],
                    skipped=[(name, [reason]) for name, _ in discovered.active],
                )
                # Fall through to the shared policy/collision/logging stage.

        # ── Log skipped plugins ─────────────────────────────────────
        for name, violations in selection.skipped:
            self._logger.warning(
                "plugin_skipped plugin=%s violations=%s",
                name,
                violations,
            )

        # ── Collision check ─────────────────────────────────────────
        if collision_key is not None and selection.active:
            key_map: dict[Hashable, str] = {}
            for name, obj in selection.active:
                for key in collision_key(obj):
                    if key in key_map:
                        raise RuntimeError(f"Plugin collision on key {key!r}: {key_map[key]!r} and {name!r}")
                    key_map[key] = name

        # ── Zero-active policy ──────────────────────────────────────
        if not selection.active:
            if self._policy.zero_active_fatal:
                raise RuntimeError(f"No active plugins in group '{self._group}'")
            self._logger.warning(
                "plugin_zero_active group=%s",
                self._group,
            )

        self._logger.info(
            "plugin_startup_complete group=%s active_count=%d skipped_count=%d",
            self._group,
            len(selection.active),
            len(selection.skipped),
        )

        return HostResult(
            active=selection.active,
            skipped=selection.skipped,
            failed=discovered.failed,
        )
