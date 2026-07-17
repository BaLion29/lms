"""Shared helpers for ToolSpec tool handlers: envelope construction, type guards,
repo acquisition.  Centralises the ``{"ok": True/False, ...}`` envelope convention
from ``toolspec.py`` so extensions stop copy-pasting ``_do_*`` boilerplate.
"""

from __future__ import annotations

from typing import Any


def ok_envelope(**payload: object) -> dict[str, object]:
    """Return a success envelope with the given payload keys.

    Example:
        >>> ok_envelope(iri="Task/123")
        {"ok": True, "iri": "Task/123"}
    """
    return {"ok": True, **payload}


def error_envelope(message: str) -> dict[str, object]:
    """Return a domain-error envelope.

    Example:
        >>> error_envelope("provide exactly one of 'query' or 'location_id'")
        {"ok": False, "error": "provide exactly one of 'query' or 'location_id'"}
    """
    return {"ok": False, "error": message}


def not_found_envelope(iri: str, exc: BaseException, *, noun: str = "document") -> dict[str, object]:
    """Return a not-found error envelope.

    Example:
        >>> not_found_envelope("Task/abc", RuntimeError("gone"), noun="task")
        {"ok": False, "error": "task not found: Task/abc: gone"}
    """
    return {"ok": False, "error": f"{noun} not found: {iri}: {exc}"}


def write_error_envelope(exc: BaseException) -> dict[str, object]:
    """Return a truncated write-error envelope.

    Used for both generic ``except Exception`` and ``RepoTransitionError``
    catches — both produce the same ``str(exc)[:200]`` shape.

    Example:
        >>> write_error_envelope(ValueError("bad data"))
        {"ok": False, "error": "bad data"}
    """
    return {"ok": False, "error": str(exc)[:200]}


def type_mismatch_error(iri: str, doc: dict, expected_type: str) -> str | None:
    """Return an error message when *doc* is not of *expected_type*, or ``None``.

    Example:
        >>> type_mismatch_error("Task/1", {"@type": "Event"}, "Task")
        "Task/1 is not a Task (type=Event)"
        >>> type_mismatch_error("Task/1", {"@type": "Task"}, "Event")
        "Task/1 is not an Event (type=Task)"
    """
    actual = doc.get("@type")
    if actual != expected_type:
        article = "an" if expected_type[:1].lower() in "aeiou" else "a"
        return f"{iri} is not {article} {expected_type} (type={actual})"
    return None


def make_repo(tdb: Any, *, transitions: dict) -> Any:
    """Return a ``Repository`` wrapping *tdb* if it is not already one.

    Imports ``Repository`` lazily to avoid import-cycle risk (following the
    pattern used in ``tdb.py`` for ``parse_agent``).

    Example:
        >>> repo = make_repo(tdb, transitions=_TASK_TRANSITIONS)
    """
    from firnline_core.repository import Repository  # noqa: PLC0415  # lazy import

    if not isinstance(tdb, Repository):
        return Repository(tdb, transitions=transitions)
    return tdb
