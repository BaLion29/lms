"""Naive entity linking helpers — index building, matching."""

from __future__ import annotations

import structlog

from firnline_core.plugins import EntityIndex  # re-exported for backward compat

logger = structlog.get_logger(__name__)


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
# Matching
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
        # Substring containment
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
        # Shared first token
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
