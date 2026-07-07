"""Naive entity linking helpers — index building, matching.

Exact casefold-match is the fast path.  When ``INGESTD_INDEXED_ENABLED=true``
and the fast path misses, ``IndexedClient`` is consulted for a ranked
candidate list; the top candidate is auto-accepted when its score exceeds
``INGESTD_INDEXED_MIN_CONFIDENCE`` (default 0.85).  Below threshold, the
caller falls through to create-new — the same "no guessing" rule, just
with real recall.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel

from firnline_core.plugins import EntityIndex  # re-exported for backward compat
from firnline_core.indexed_client import IndexedClient, IndexedError

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
# Index building
# ---------------------------------------------------------------------------


def build_index(people: list[dict], locations: list[dict]) -> EntityIndex:
    """Build an ``EntityIndex`` from raw TerminusDB document dicts.

    Docs without a ``"name"`` key are silently skipped.
    Location ``"aliases"`` are indexed to the same IRI as the primary name.
    """
    index = EntityIndex()

    for p in people:
        name: str | None = p.get("name")
        if not name:
            continue
        iri = p.get("@id", "")
        key = name.casefold()
        index.people[key] = iri
        index.people_display.append((name, iri))

    for loc in locations:
        name: str | None = loc.get("name")
        if not name:
            continue
        iri = loc.get("@id", "")
        key = name.casefold()
        index.locations[key] = iri
        index.locations_display.append((name, iri))
        for alias in loc.get("aliases", []) or []:
            index.locations[alias.casefold()] = iri

    return index


# ---------------------------------------------------------------------------
# Matching — fast path (synchronous, stays as-is for dry-run / disabled)
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


def match_person(index: EntityIndex, name: str) -> str | None:
    """Case-insensitive exact match of *name* against known people.

    Returns the IRI on exact match, ``None`` otherwise.
    On miss, logs any near-misses at info level via structlog.
    """
    key = name.strip().casefold()
    if key in index.people:
        return index.people[key]
    _near_miss(key, index.people, "person")
    return None


def match_location(index: EntityIndex, name: str) -> str | None:
    """Case-insensitive exact match of *name* against known locations (names + aliases).

    Returns the IRI on exact match, ``None`` otherwise.
    On miss, logs any near-misses at info level via structlog.
    """
    key = name.strip().casefold()
    if key in index.locations:
        return index.locations[key]
    _near_miss(key, index.locations, "location")
    return None


# ---------------------------------------------------------------------------
# Async matching — consults indexed service on fast-path miss
# ---------------------------------------------------------------------------


async def async_match_person(
    index: EntityIndex,
    name: str,
    config: LinkingConfig,
) -> str | None:
    """Exact match first; on miss, consult the indexed service.

    *name* is accepted from indexed only when the top candidate score
    exceeds ``config.min_confidence`` (default 0.85).  Below threshold
    the near-miss is logged with the score and ``None`` is returned.
    """
    fast = match_person(index, name)
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
                name, classes=["Person"], branch=config.branch, k=1
            )
    except IndexedError:
        logger.warning(
            "indexed_match_failed",
            type="Person",
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
            type="Person",
            query=name,
            match=best.name,
            iri=best.iri,
            score=round(best.score, 4),
        )
        return best.iri

    logger.info(
        "indexed_match_below_threshold",
        type="Person",
        query=name,
        best_match=best.name,
        best_iri=best.iri,
        score=round(best.score, 4),
        threshold=config.min_confidence,
    )
    return None


async def async_match_location(
    index: EntityIndex,
    name: str,
    config: LinkingConfig,
) -> str | None:
    """Exact match first; on miss, consult the indexed service.

    Same logic as :func:`async_match_person`, but for locations.
    """
    fast = match_location(index, name)
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
                name, classes=["Location"], branch=config.branch, k=1
            )
    except IndexedError:
        logger.warning(
            "indexed_match_failed",
            type="Location",
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
            type="Location",
            query=name,
            match=best.name,
            iri=best.iri,
            score=round(best.score, 4),
        )
        return best.iri

    logger.info(
        "indexed_match_below_threshold",
        type="Location",
        query=name,
        match=best.name,
        best_iri=best.iri,
        score=round(best.score, 4),
        threshold=config.min_confidence,
    )
    return None
