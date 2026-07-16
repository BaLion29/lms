"""History state — commit log browsing (framework-free)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext

_LOG_COUNT = 200


@dataclass(frozen=True)
class HistoryData:
    commits: tuple[dict, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class CommitDiffData:
    inserted: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    error: str = ""


async def load_history(ctx: AppContext) -> HistoryData:
    """Fetch commit log and pre-format timestamps."""
    tdb = ctx.make_tdb()
    try:
        commits = await tdb.get_commit_log(_LOG_COUNT)
    except UiClientError as exc:
        await tdb.aclose()
        return HistoryData(error=f"Failed to load commit log: {exc.detail}")
    except Exception as exc:
        await tdb.aclose()
        return HistoryData(error=f"Failed to load commit log: {exc!s}")

    formatted: list[dict] = []
    for c in commits:
        formatted.append(
            {
                "id": c.get("id", ""),
                "short_id": c.get("short_id", ""),
                "author": c.get("author", ""),
                "message": c.get("message", ""),
                "timestamp": c.get("timestamp"),
                "timestamp_fmt": _format_ts(c.get("timestamp")),
            }
        )

    await tdb.aclose()
    return HistoryData(commits=tuple(formatted))


async def load_commit(ctx: AppContext, commit_id: str) -> CommitDiffData:
    """Fetch changes for a single commit."""
    if not commit_id:
        return CommitDiffData(error="No commit ID provided.")

    tdb = ctx.make_tdb()
    try:
        changes = await tdb.get_commit_changes(commit_id)
    except UiClientError as exc:
        await tdb.aclose()
        return CommitDiffData(error=f"Failed to load changes: {exc.detail}")
    except Exception as exc:
        await tdb.aclose()
        return CommitDiffData(error=f"Failed to load changes: {exc!s}")

    await tdb.aclose()
    return CommitDiffData(
        inserted=tuple(changes.get("inserted", []) or []),
        updated=tuple(changes.get("updated", []) or []),
        deleted=tuple(changes.get("deleted", []) or []),
    )


def _format_ts(ts: float | None) -> str:
    """Format a POSIX timestamp into a human-readable string."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""
