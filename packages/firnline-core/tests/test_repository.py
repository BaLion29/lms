"""Tests for firnline_core.repository — Repository.update method."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from firnline_core.repository import Repository
from firnline_core.tdb import TdbConflictError, TdbError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo() -> Repository:
    """Create a Repository with a mocked TdbClient."""
    tdb = MagicMock()
    tdb.get_document = AsyncMock()
    tdb.replace_document = AsyncMock()
    tdb.insert_documents = AsyncMock()
    return Repository(tdb)


def _existing_doc() -> dict:
    return {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Original name",
        "priority": 1,
        "provenance": {"agent": "user:basti", "at": "2025-01-01T00:00:00Z"},
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_happy_path():
    """Update merges fields and stamps provenance."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    result = await repo.update(
        "Task/abc",
        {"name": "Updated name", "priority": 2},
        agent="user:basti",
    )

    assert result == "Task/abc"

    # Verify get_document was called
    repo._tdb.get_document.assert_awaited_once_with("Task/abc", branch="main")

    # Verify replace_document was called with merged doc
    repo._tdb.replace_document.assert_awaited_once()
    call_args = repo._tdb.replace_document.call_args
    updated_doc = call_args[0][0]

    assert updated_doc["@id"] == "Task/abc"
    assert updated_doc["@type"] == "Task"
    assert updated_doc["name"] == "Updated name"
    assert updated_doc["priority"] == 2
    assert "provenance" in updated_doc
    assert updated_doc["provenance"]["agent"] == "user:basti"
    assert "method" not in updated_doc["provenance"]  # update doesn't set method


@pytest.mark.asyncio
async def test_update_partial_merge():
    """Only supplied fields are updated; other fields are preserved."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    await repo.update(
        "Task/abc",
        {"priority": 5},
        agent="ext:mcp",
    )

    call_args = repo._tdb.replace_document.call_args
    updated_doc = call_args[0][0]

    assert updated_doc["name"] == "Original name"  # preserved
    assert updated_doc["priority"] == 5  # updated


# ---------------------------------------------------------------------------
# @type / @id disallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rejects_type_change():
    """Cannot change @type."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    with pytest.raises(ValueError, match="Cannot change @type"):
        await repo.update(
            "Task/abc",
            {"@type": "Project", "name": "test"},
            agent="user:basti",
        )


@pytest.mark.asyncio
async def test_update_rejects_id_change():
    """Cannot change @id."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    with pytest.raises(ValueError, match="Cannot change @id"):
        await repo.update(
            "Task/abc",
            {"@id": "Task/xyz", "name": "test"},
            agent="user:basti",
        )


@pytest.mark.asyncio
async def test_update_allows_type_in_fields_when_same():
    """@type in fields is harmless when it matches existing."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    result = await repo.update(
        "Task/abc",
        {"@type": "Task", "name": "test"},
        agent="user:basti",
    )

    assert result == "Task/abc"
    call_args = repo._tdb.replace_document.call_args
    updated_doc = call_args[0][0]
    assert updated_doc["@type"] == "Task"


# ---------------------------------------------------------------------------
# Agent validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rejects_bad_agent():
    """Invalid agent grammar raises ValueError."""
    repo = _make_repo()

    with pytest.raises(ValueError, match="agent"):
        await repo.update(
            "Task/abc",
            {"name": "test"},
            agent="nonsense",
        )


# ---------------------------------------------------------------------------
# Document not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_not_found():
    """TdbError(404) from get_document propagates."""
    repo = _make_repo()
    repo._tdb.get_document.side_effect = TdbError(404, "Document not found")

    with pytest.raises(TdbError) as exc_info:
        await repo.update(
            "Task/nope",
            {"name": "test"},
            agent="user:basti",
        )

    assert exc_info.value.status == 404


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_conflict():
    """TdbConflictError from replace_document propagates."""
    repo = _make_repo()
    repo._tdb.get_document.return_value = _existing_doc()
    repo._tdb.replace_document.side_effect = TdbConflictError("abc", "def")

    with pytest.raises(TdbConflictError):
        await repo.update(
            "Task/abc",
            {"name": "test"},
            agent="user:basti",
        )


# ---------------------------------------------------------------------------
# Full IRI input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_with_full_iri():
    """Full terminusdb:///data/... IRI is accepted."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    result = await repo.update(
        "terminusdb:///data/Task/abc",
        {"name": "test"},
        agent="user:basti",
    )

    assert result == "terminusdb:///data/Task/abc"
    # Should have been converted to short for get_document
    repo._tdb.get_document.assert_awaited_once_with("Task/abc", branch="main")


# ---------------------------------------------------------------------------
# Branch parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_branch():
    """Branch parameter is passed through."""
    repo = _make_repo()
    doc = _existing_doc()
    repo._tdb.get_document.return_value = doc

    await repo.update(
        "Task/abc",
        {"name": "test"},
        agent="user:basti",
        branch="feature",
    )

    repo._tdb.get_document.assert_awaited_once_with("Task/abc", branch="feature")
    call_args = repo._tdb.replace_document.call_args
    assert call_args[1]["branch"] == "feature"
