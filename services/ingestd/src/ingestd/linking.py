"""Generic entity linking helpers — index building, matching.

Exact casefold-match is the fast path.  When ``INGESTD_INDEXED_ENABLED=true``
and the fast path misses, ``IndexedClient`` is consulted for a ranked
candidate list; the top candidate is auto-accepted when its score exceeds
``INGESTD_INDEXED_MIN_CONFIDENCE`` (default 0.85).  Below threshold, the
caller falls through to create-new — the same "no guessing" rule, just
with real recall.

All matching functions are now class-agnostic — they operate on any
entity class via the generic ``EntityIndex``.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel

from firnline_core.plugins import EntityIndex  # re-exported for backward compat
from firnline_core.indexed_client import IndexedClient, IndexedError
from firnline_core.tdb import TdbError

logger = structlog.get_logger(__name__)


class LinkingConfig(BaseModel):
    """Configuration passed to async matching functions.

    When *enabled* is ``False`` the async matchers degrade to the fast path.
    """

    enabled: bool = False
    url: str = ""
    token: str = ""
    min_confidence: float = 0.85
    timeout_seconds: float = 10.0
    branch: str = "main"


# ---------------------------------------------------------------------------
# Generic index building
# ---------------------------------------------------------------------------


async def build_index_from_classes(
    tdb,  # TdbClient
    class_names: list[str],
    branch: str = "main",
) -> EntityIndex:
    """Build an ``EntityIndex`` by fetching all documents for each *class_name*.

    Classes that fail with ``TdbError`` (e.g. not installed) are logged and
    skipped.  Docs without a ``"name"`` key are silently skipped.
    Location-style ``"aliases"`` contribute additional lookup keys.
    """
    index = EntityIndex()

    for cls_name in sorted(class_names):
        try:
            docs = await tdb.get_documents(cls_name, branch)
        except TdbError:
            logger.warning("index_fetch_failed", class_name=cls_name, exc_info=True)
            continue

        for doc in docs:
            name: str | None = doc.get("name")
            if not name:
                continue
            iri = doc.get("@id", "")
            index.register(cls_name, name, iri)
            for alias in doc.get("aliases", []) or []:
                if isinstance(alias, str):
                    # Aliases go into the lookup map only, not display
                    index.entities.setdefault(cls_name, {})[alias.casefold()] = iri

    return index


# ---------------------------------------------------------------------------
# Matching — fast path
# ---------------------------------------------------------------------------


def _near_miss(
    proposed: str,
    known_dict: dict[str, str],
    category: str,
) -> None:
    """Log near-miss entries where *proposed* is close to a known key."""
    proposed_tokens = proposed.split()
    proposed_first = proposed_tokens[0] if proposed_tokens else ""

    for known, iri in known_dict.items():
        if proposed in known or known in proposed:
            logger.info(
                "near_miss",
                proposed=proposed,
                known=known,
                iri=iri,
                category=category,
                reason="substring",
            )
            continue
        known_first = known.split()[0] if known.split() else ""
        if proposed_first and known_first and proposed_first == known_first:
            logger.info(
                "near_miss",
                proposed=proposed,
                known=known,
                iri=iri,
                category=category,
                reason="first_token",
            )


def match(index: EntityIndex, class_name: str, name: str) -> str | None:
    """Case-insensitive exact match of *name* against *class_name* entities.

    Returns the IRI on exact match, ``None`` otherwise.
    On miss, logs any near-misses at info level via structlog.
    """
    key = name.strip().casefold()
    iri = index.lookup(class_name, key)
    if iri:
        return iri
    _near_miss(key, index.entities.get(class_name, {}), class_name.lower())
    return None


# Backward-compatible aliases kept for existing test imports
match_person = lambda index, name: match(index, "Person", name)  # noqa: E731
match_location = lambda index, name: match(index, "Location", name)  # noqa: E731


# ---------------------------------------------------------------------------
# Async matching — consults indexed service on fast-path miss
# ---------------------------------------------------------------------------


async def async_match(
    index: EntityIndex,
    class_name: str,
    name: str,
    config: LinkingConfig,
) -> str | None:
    """Exact match first; on miss, consult the indexed service.

    *name* is accepted from indexed only when the top candidate score
    exceeds ``config.min_confidence`` (default 0.85).  Below threshold
    the near-miss is logged with the score and ``None`` is returned.
    """
    fast = match(index, class_name, name)
    if fast is not None:
        return fast

    if not config.enabled or not config.url:
        return None

    try:
        async with IndexedClient(
            base_url=config.url,
            token=config.token,
            timeout=config.timeout_seconds,
        ) as client:
            candidates = await client.find_entity(
                name, classes=[class_name], branch=config.branch, k=1
            )
    except IndexedError:
        logger.warning(
            "indexed_match_failed",
            type=class_name,
            query=name,
            exc_info=True,
        )
        return None

    if not candidates:
        return None

    best = candidates[0]
    if best.score >= config.min_confidence:
        logger.info(
            "indexed_match_accepted",
            type=class_name,
            query=name,
            match=best.name,
            iri=best.iri,
            score=round(best.score, 4),
        )
        return best.iri

    logger.info(
        "indexed_match_below_threshold",
        type=class_name,
        query=name,
        best_match=best.name,
        best_iri=best.iri,
        score=round(best.score, 4),
        threshold=config.min_confidence,
    )
    return None


# Backward-compatible async aliases for existing test imports
async def async_match_person(index, name, config):
    return await async_match(index, "Person", name, config)


async def async_match_location(index, name, config):
    return await async_match(index, "Location", name, config)
