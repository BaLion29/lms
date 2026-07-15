"""Transport-neutral async operations for queryd.

Plain async functions with explicit dependencies (no RunContext).  Used by
REST endpoints and tool invocation paths.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from firnline_core.indexed_client import IndexedClient
from firnline_core.tdb import TdbClient, TdbError

from queryd.schema_briefing import (
    fetch_introspection,
    fetch_module_list,
    render_schema_summary,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# GraphQL mutation guard (shared between tools and REST)
# ---------------------------------------------------------------------------

_STRIP_PATTERN = re.compile(
    r'""".*?"""'
    r"|"
    r'"(?:[^"\\]|\\.)*"'
    r"|"
    r"'(?:[^'\\]|\\.)*'"
    r"|"
    r"#[^\n]*",
    re.DOTALL,
)

_HARMFUL_KEYWORDS = re.compile(
    r"\b(mutation|subscription)\b", re.IGNORECASE
)
_HARMFUL_FUNCTIONS = [
    "_insertDocuments",
    "_replaceDocuments",
    "_deleteDocuments",
]


def check_graphql(query: str) -> str | None:
    """Return an error message if *query* is dangerous, ``None`` otherwise.

    After stripping string literals and comments, any standalone
    ``mutation`` or ``subscription`` word is treated as a prohibited
    operation keyword.  The function-name blacklist provides additional
    defense-in-depth against bare mutation function calls.
    """
    stripped = _STRIP_PATTERN.sub(" ", query)
    if m := _HARMFUL_KEYWORDS.search(stripped):
        return f"Query contains prohibited keyword: {m.group()}"
    for func in _HARMFUL_FUNCTIONS:
        if func in stripped:
            return f"Query contains prohibited function: {func}"
    return None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


async def get_schema_summary(tdb: TdbClient) -> str:
    """Fetch introspection and render the full schema summary."""
    intro = await fetch_introspection(tdb)
    return render_schema_summary(intro)


async def get_introspection(tdb: TdbClient) -> dict[str, Any]:
    """Return raw GraphQL introspection JSON."""
    return await fetch_introspection(tdb)


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------


async def run_graphql(
    tdb: TdbClient,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a read-only GraphQL query.  Raises ``ValueError`` on mutation."""
    error = check_graphql(query)
    if error is not None:
        raise ValueError(error)
    return await tdb.graphql(query, variables)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def get_document(tdb: TdbClient, iri: str) -> dict[str, Any]:
    """Fetch a single document by IRI.  Raises ``TdbError`` on failure."""
    return await tdb.get_document(iri)


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


async def list_modules(
    tdb: TdbClient,
    *,
    branch: str = "main",
) -> list[dict[str, Any]]:
    """Fetch SchemaModule registry docs."""
    return await fetch_module_list(tdb, branch=branch)


# ---------------------------------------------------------------------------
# Indexed operations
# ---------------------------------------------------------------------------


async def find_entity(
    indexed_url: str,
    indexed_token: str,
    indexed_timeout: float,
    text: str,
    *,
    classes: list[str] | None = None,
    branch: str = "main",
    k: int = 5,
) -> list[dict[str, Any]]:
    """Search for known entities matching *text*."""
    async with IndexedClient(
        base_url=indexed_url,
        token=indexed_token,
        timeout=indexed_timeout,
    ) as client:
        candidates = await client.find_entity(
            text, classes=classes, branch=branch, k=k
        )
    return [
        {
            "iri": c.iri,
            "class": c.class_name,
            "name": c.name,
            "aliases": c.aliases,
            "score": round(c.score, 4),
            "commit_id": c.commit_id,
        }
        for c in candidates
    ]


async def find_class(
    indexed_url: str,
    indexed_token: str,
    indexed_timeout: float,
    text: str,
    *,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Search for schema classes matching *text*."""
    async with IndexedClient(
        base_url=indexed_url,
        token=indexed_token,
        timeout=indexed_timeout,
    ) as client:
        candidates = await client.find_class(text, k=k)
    return [
        {
            "class": c.class_name,
            "description": c.description,
            "score": round(c.score, 4),
        }
        for c in candidates
    ]


async def find_field(
    indexed_url: str,
    indexed_token: str,
    indexed_timeout: float,
    text: str,
    *,
    class_name: str | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Search for class field/property names matching *text*."""
    async with IndexedClient(
        base_url=indexed_url,
        token=indexed_token,
        timeout=indexed_timeout,
    ) as client:
        candidates = await client.find_field(text, class_name=class_name, k=k)
    return [
        {
            "class": c.class_name,
            "field": c.field,
            "type": c.type,
            "description": c.description,
            "score": round(c.score, 4),
        }
        for c in candidates
    ]
