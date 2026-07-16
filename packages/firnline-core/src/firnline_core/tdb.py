"""Thin typed async TerminusDB HTTP client using httpx."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PREFIX = "terminusdb:///data/"


def short_iri(iri: str) -> str:
    """Convert ``terminusdb:///data/X/Y`` → ``X/Y``.

    Passes through if already short (no prefix).
    """
    if iri is None:
        raise ValueError("iri must not be None")
    if iri.startswith(PREFIX):
        return iri[len(PREFIX) :]
    return iri


def full_iri(iri: str) -> str:
    """Convert ``X/Y`` → ``terminusdb:///data/X/Y``.

    Passes through if already a full IRI.
    """
    if iri.startswith(PREFIX):
        return iri
    return f"{PREFIX}{iri}"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TdbError(Exception):
    """Raised for non-2xx TerminusDB responses (or GraphQL errors)."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"TdbError({status}): {body}")

    def __str__(self) -> str:
        return f"TdbError({self.status}): {self.body}"


class StaleCommitError(TdbError):
    """Raised when a *commit_id* no longer exists in branch history."""

    def __init__(self, commit_id: str, branch: str) -> None:
        self.commit_id = commit_id
        self.branch = branch
        msg = (
            f"Stale commit '{commit_id}' on branch '{branch}': "
            "commit no longer exists in branch history "
            "(e.g. branch was reset or schema was full-replaced)."
        )
        super().__init__(status=400, body=msg)


class TdbConflictError(TdbError):
    """Raised when an optimistic-concurrency check fails.

    The *body* contains both the expected and actual head identifiers.
    """

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        msg = f"Conflict: expected head '{expected}', actual head '{actual}'"
        super().__init__(status=409, body=msg)


@dataclass
class ChangeEvent:
    """A single commit event in a TerminusDB change feed.

    Fields:
        commit_id: The commit identifier.
        author: Commit author.
        message: Commit message.
        timestamp: POSIX timestamp (if available).
        inserted: Document IRIs that were inserted in this commit.
        updated: Document IRIs that were updated in this commit.
        deleted: Document IRIs that were deleted in this commit.
    """

    commit_id: str
    author: str
    message: str
    timestamp: float | None = None
    inserted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TdbClient:
    """Async TerminusDB HTTP client with basic auth.

    Supports ``async with`` context-manager usage.
    """

    def __init__(
        self,
        base_url: str,
        org: str,
        db: str,
        user: str,
        password: str,
        author: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        from firnline_core.conventions import parse_agent

        parse_agent(author)
        self._author = author
        self.base_url = base_url.rstrip("/")
        self.org = org
        self.db = db
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(user, password),
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> TdbClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _doc_path(self, branch: str) -> str:
        """Build the branch-scoped document API path."""
        return f"/api/document/{self.org}/{self.db}/local/branch/{branch}"

    async def _raise_on_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        raise TdbError(response.status_code, response.text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_documents(
        self,
        type_: str,
        branch: str = "main",
        *,
        skip: int | None = None,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch documents of *type_* from *branch*.

        Optional *skip* and *count* are forwarded as query params for
        server-side pagination (the TerminusDB document API accepts
        ``skip`` and ``count`` as query parameters).
        """
        params: dict[str, str] = {
            "graph_type": "instance",
            "type": type_,
            "as_list": "true",
        }
        if skip is not None:
            params["skip"] = str(skip)
        if count is not None:
            params["count"] = str(count)
        response = await self._client.get(
            self._doc_path(branch),
            params=params,
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def count_documents(
        self, type_: str, branch: str = "main"
    ) -> int:
        """Return the total number of *type_* documents on *branch*.

        Fetches all documents of *type_* with ``as_list=true`` and
        returns the list length.  This works across all TerminusDB
        versions; the ``count=true`` shorthand is not universally
        supported (some versions reject non-integer ``count`` values).
        """
        response = await self._client.get(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "type": type_,
                "as_list": "true",
            },
        )
        await self._raise_on_error(response)
        data = response.json()
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            # Single document or empty
            return 1
        return 0

    async def get_document(self, iri: str, branch: str = "main") -> dict[str, Any]:
        """Fetch a single document by *iri* (short or full) from *branch*.

        Uses the same document API endpoint as ``get_documents`` but
        with an ``id`` query parameter.  Raises ``TdbError`` on any
        non-2xx response (including 404).
        """
        short = short_iri(iri)
        response = await self._client.get(
            self._doc_path(branch),
            params={"id": short},
        )
        await self._raise_on_error(response)
        data = response.json()
        # The endpoint may return a bare object or a list.
        if isinstance(data, list):
            if not data:
                raise TdbError(404, f"Document not found: {iri}")
            return data[0]  # type: ignore[no-any-return]
        return data  # type: ignore[no-any-return]

    async def insert_documents(
        self,
        docs: list[dict[str, Any]],
        branch: str = "main",
        message: str = "ingestd",
    ) -> list[str]:
        """Insert *docs* and return the list of full IRIs."""
        response = await self._client.post(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "author": self._author,
                "message": message,
            },
            json=docs,
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def replace_document(
        self,
        doc: dict[str, Any],
        branch: str = "main",
        message: str = "ingestd",
        *,
        expected_head: str | None = None,
    ) -> None:
        """Replace a single document (must contain ``@id``).

        Raises ``ValueError`` if *doc* is missing ``@id``.

        When *expected_head* is provided, the current branch head is
        checked first — a ``TdbConflictError`` is raised if it differs.
        **Note:** this is best-effort optimistic concurrency (race window
        between check and write), not a true CAS.
        """
        if not doc.get("@id"):
            raise ValueError("Document must contain '@id' for replace")

        if expected_head is not None:
            actual_head = await self.get_branch_head(branch)
            if actual_head != expected_head:
                raise TdbConflictError(expected_head, actual_head)

        response = await self._client.put(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "author": self._author,
                "message": message,
            },
            json=doc,
        )
        await self._raise_on_error(response)

    async def replace_documents(
        self,
        docs: list[dict[str, Any]],
        branch: str = "main",
        message: str = "ingestd",
        *,
        create: bool = False,
    ) -> list[str]:
        """Atomically insert-or-replace a batch of documents.

        When *create* is ``True`` the TerminusDB ``create`` parameter is
        set to ``"true"``, which means: insert-if-absent, replace-if-present
        — all in a single atomic request.

        Returns the list of full IRIs of the written documents.
        """
        params: dict[str, str] = {
            "graph_type": "instance",
            "author": self._author,
            "message": message,
        }
        if create:
            params["create"] = "true"

        response = await self._client.put(
            self._doc_path(branch),
            params=params,
            json=docs,
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def delete_document(
        self,
        iri: str,
        branch: str = "main",
        message: str = "ingestd",
    ) -> None:
        """Delete a document by *iri* from *branch*.

        Raises ``TdbError`` on non-2xx response (including 404).
        """
        short = short_iri(iri)
        response = await self._client.delete(
            self._doc_path(branch),
            params={
                "id": short,
                "author": self._author,
                "message": message,
            },
        )
        await self._raise_on_error(response)

    async def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query and return the ``data`` field.

        When *branch* is ``None`` (default) the query runs against the
        database default (``main``).  For branch-scoped queries pass the
        branch name, which appends ``/local/branch/{branch}`` to the URL.

        Raises ``TdbError`` on non-2xx **or** when the response contains
        an ``errors`` field (GraphQL can return 200 with errors).
        """
        if branch is None:
            path = f"/api/graphql/{self.org}/{self.db}"
        else:
            path = f"/api/graphql/{self.org}/{self.db}/local/branch/{branch}"

        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        response = await self._client.post(path, json=payload)
        await self._raise_on_error(response)
        body: dict[str, Any] = response.json()
        if body.get("errors"):
            raise TdbError(response.status_code, response.text)
        return body.get("data", {})  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Database / schema lifecycle
    # ------------------------------------------------------------------

    async def db_exists(self) -> bool:
        """Check whether the database exists (returns True on 2xx)."""
        response = await self._client.get(
            f"/api/db/{self.org}/{self.db}",
        )
        return response.is_success

    async def create_db(
        self, label: str = "", comment: str = "", *, schema: bool = True
    ) -> None:
        """Create the database.

        Does NOT verify existence first — use ``db_exists()`` to check.
        """
        response = await self._client.post(
            f"/api/db/{self.org}/{self.db}",
            json={
                "label": label or self.db,
                "comment": comment or "created by ingestd bootstrap",
                "schema": schema,
            },
        )
        await self._raise_on_error(response)

    async def push_schema(
        self,
        schema: list[dict[str, Any]],
        branch: str = "main",
        *,
        full_replace: bool = True,
        message: str = "bootstrap",
    ) -> None:
        """Push/replace the full schema (``full_replace=true``, idempotent).

        When *branch* is ``"main"`` the schema is pushed to the default
        (non-branch-scoped) path for backward compatibility.  For any other
        branch the branch-scoped document path is used.
        """
        _NON_WOQL_KEYS = frozenset({"@abstract", "@documentation", "@metadata"})

        def _strip_non_woql(item: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in item.items() if k not in _NON_WOQL_KEYS}

        clean_schema = [
            _strip_non_woql(item) if isinstance(item, dict) else item
            for item in schema
        ]

        if branch == "main":
            path = f"/api/document/{self.org}/{self.db}"
        else:
            path = self._doc_path(branch)

        response = await self._client.post(
            path,
            params={
                "graph_type": "schema",
                "full_replace": "true" if full_replace else "false",
                "author": self._author,
                "message": message,
            },
            json=clean_schema,
        )
        await self._raise_on_error(response)

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    async def create_branch(self, new_branch: str, origin: str = "main") -> None:
        """Create *new_branch* from *origin*.

        Raises ``TdbError`` if the branch already exists (400).
        """
        response = await self._client.post(
            f"/api/branch/{self.org}/{self.db}/local/branch/{new_branch}",
            json={"origin": origin},
        )
        await self._raise_on_error(response)

    async def delete_branch(self, branch: str) -> None:
        """Delete *branch*.

        Raises ``TdbError`` if the branch does not exist or is ``"main"``.
        """
        response = await self._client.delete(
            f"/api/branch/{self.org}/{self.db}/local/branch/{branch}",
        )
        await self._raise_on_error(response)

    async def branch_exists(self, branch: str) -> bool:
        """Return ``True`` when *branch* exists.

        Probes the document endpoint with a minimal request — a 2xx means
        the branch exists, a 4xx (with the ``UnresolvableAbsoluteDescriptor``
        error type) means it does not.
        """
        response = await self._client.get(
            self._doc_path(branch),
            params={"graph_type": "instance", "count": 1},
        )
        return response.is_success

    # ------------------------------------------------------------------
    # Branch head retrieval
    # ------------------------------------------------------------------

    async def get_branch_head(self, branch: str) -> str:
        """Return the head commit identifier for *branch*.

        Uses the log endpoint (GET /api/log/{org}/{db}/local/branch/{branch})
        and returns the ``identifier`` field of the first (newest) commit.
        """
        entries = await self.get_branch_log(branch, count=1)
        if not entries:
            raise TdbError(404, f"No commits found for branch '{branch}'")
        identifier = entries[0].get("identifier")
        if not identifier:
            raise TdbError(500, f"No identifier in head commit for branch '{branch}'")
        return str(identifier)

    async def get_branch_log(
        self, branch: str, count: int | None = None
    ) -> list[dict[str, Any]]:
        """Return the commit log for *branch* (newest first).

        Uses GET /api/log/{org}/{db}/local/branch/{branch}[?count=N].
        When *count* is None the endpoint returns all commits.
        Each entry contains ``identifier`` and ``timestamp`` fields.
        """
        path = f"/api/log/{self.org}/{self.db}/local/branch/{branch}"
        params: dict[str, str] = {}
        if count is not None:
            params["count"] = str(count)
        response = await self._client.get(path, params=params)
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Promote / merge
    # ------------------------------------------------------------------

    async def reset_branch(
        self,
        target_branch: str,
        commit_descriptor: str,
    ) -> None:
        """Move *target_branch* to *commit_descriptor*.

        *commit_descriptor* must be a full commit-descriptor path, e.g.
        ``"admin/mydb/local/commit/<identifier>"``.

        This is the recommended way to *promote* changes from a feature
        branch onto another branch (including ``main``).
        """
        response = await self._client.post(
            f"/api/reset/{self.org}/{self.db}/local/branch/{target_branch}",
            json={"commit_descriptor": commit_descriptor},
        )
        await self._raise_on_error(response)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def get_schema(
        self, branch: str = "main"
    ) -> list[dict[str, Any]]:
        """Fetch the full schema from the document API.

        Returns the schema graph as a list of class/enum/@context definitions.
        Note that the returned list includes the ``@context`` object.
        """
        response = await self._client.get(
            self._doc_path(branch),
            params={
                "graph_type": "schema",
                "as_list": "true",
            },
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def get_documents_by_status(
        self, type_: str, status: str, branch: str = "main"
    ) -> list[dict[str, Any]]:
        """Fetch *type_* documents on *branch* where ``status`` matches.

        Uses the TerminusDB document API's ``query`` parameter for server-side
        template filtering, avoiding client-side filtering of all documents.
        """
        response = await self._client.get(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "type": type_,
                "as_list": "true",
                "query": json.dumps({"@type": type_, "status": status}),
            },
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Change feed
    # ------------------------------------------------------------------

    # Upper bound for log requests to detect truncation.
    # If the endpoint returns this many entries and a commit is still not
    # found we cannot be sure whether the commit is truly stale or just
    # fell outside the fetched window.
    _LOG_REQUEST_CAP: int = 10_000

    async def changes_since(
        self,
        commit_id: str | None,
        branch: str = "main",
        *,
        limit: int | None = None,
    ) -> tuple[list[ChangeEvent], str]:
        """Return change events after *commit_id*, plus the new head.

        Uses a three-tier strategy to handle TerminusDB auto-optimizer races:

        **Tier 1** — Per-commit diffs (happy path):
        Each commit between *commit_id* and the current head is diffed against
        its parent via ``_diff_commit``, producing one ``ChangeEvent`` per
        commit (oldest first).  *limit* caps the number of returned events
        but does **not** affect the staleness check.

        **Tier 2** — Aggregate diff (fallback):
        If any per-commit diff raises ``TdbError`` with ``api:NotValidRefError``
        (the commit was invalidated by a background layer squash between the
        log fetch and the diff request), a single aggregate diff is performed:
        ``{cursor} → {head}``.  The result is one ``ChangeEvent`` with the
        head commit's metadata and the combined inserted/updated/deleted IRIs.
        A ``diff_window_aggregated`` warning is logged.

        **Tier 3** — Stale cursor (bail out):
        If the aggregate diff ALSO fails with ``api:NotValidRefError``, the
        cursor itself has been rolled up and ``StaleCommitError`` is raised.
        Callers should re-baseline with ``commit_id=None``.

        If *commit_id* is ``None``, returns ``([], current_head)`` —
        callers should use this to baseline before polling.

        Raises
        ------
        TdbError
            If any diff endpoint call fails with a non-NotValidRefError,
            or if *commit_id* is not found in the fetched log window and
            the window may be truncated.
        StaleCommitError
            If *commit_id* is not found in the full (untruncated) branch log,
            or if both per-commit and aggregate diffs fail with
            ``api:NotValidRefError``.
        """
        current_head = await self.get_branch_head(branch)

        if commit_id is None:
            return ([], current_head)

        if commit_id == current_head:
            return ([], current_head)

        # Fetch log with a large cap to detect truncation.
        log_entries = await self.get_branch_log(branch, count=self._LOG_REQUEST_CAP)

        # Find the cutoff: scan the FULL log for commit_id (before
        # applying *limit*, which only affects returned events).
        newer: list[dict[str, Any]] = []
        found = False
        for entry in log_entries:
            ident = str(entry.get("identifier", ""))
            if ident == commit_id:
                found = True
                break
            newer.append(entry)

        if not found:
            if len(log_entries) >= self._LOG_REQUEST_CAP:
                raise TdbError(
                    400,
                    f"Commit '{commit_id}' not found in fetched log window "
                    f"({self._LOG_REQUEST_CAP} entries) for branch "
                    f"'{branch}'; log may be truncated.",
                )
            raise StaleCommitError(commit_id, branch)

        # Reverse to oldest→newest order.
        newer.reverse()

        # Apply *limit* only to returned events.
        if limit is not None:
            newer = newer[:limit]

        # ── Tier 1: per-commit diffs ──────────────────────────────────
        events: list[ChangeEvent] = []
        for i, entry in enumerate(newer):
            ident = str(entry.get("identifier", ""))
            author = str(entry.get("author", ""))
            message = str(entry.get("message", ""))
            timestamp_str = entry.get("timestamp")
            timestamp: float | None = None
            if timestamp_str is not None:
                try:
                    ts = timestamp_str
                    if isinstance(ts, str):
                        if ts.endswith("Z"):
                            ts = ts[:-1] + "+00:00"
                        from datetime import datetime as _dt
                        timestamp = _dt.fromisoformat(ts).timestamp()
                    elif isinstance(ts, (int, float)):
                        timestamp = float(ts)
                except (ValueError, TypeError):
                    timestamp = None

            try:
                inserted, updated, deleted = await self._diff_commit(
                    branch, entry, newer, i, log_entries
                )
            except TdbError as exc:
                if "NotValidRefError" not in exc.body:
                    raise  # non-NotValidRef → propagate immediately
                # ── Tier 2: aggregate diff ────────────────────────────
                before_desc = f"{self.org}/{self.db}/local/commit/{commit_id}"
                after_desc = f"{self.org}/{self.db}/local/commit/{current_head}"
                logger.warning(
                    "diff_window_aggregated",
                    branch=branch,
                    cursor=commit_id,
                    head=current_head,
                    commits=len(newer),
                )
                try:
                    agg_inserted, agg_updated, agg_deleted = (
                        await self._diff_between(before_desc, after_desc)
                    )
                except TdbError as agg_exc:
                    if "NotValidRefError" in agg_exc.body:
                        # ── Tier 3: cursor itself stale ──────────
                        raise StaleCommitError(commit_id, branch) from agg_exc
                    raise  # other aggregate error propagates

                # Build a single ChangeEvent from head entry + merged ops.
                head_entry = log_entries[0]
                head_author = str(head_entry.get("author", ""))
                head_message = str(head_entry.get("message", ""))
                head_ts: float | None = None
                head_ts_str = head_entry.get("timestamp")
                if head_ts_str is not None:
                    try:
                        ts = head_ts_str
                        if isinstance(ts, str):
                            if ts.endswith("Z"):
                                ts = ts[:-1] + "+00:00"
                            from datetime import datetime as _dt
                            head_ts = _dt.fromisoformat(ts).timestamp()
                        elif isinstance(ts, (int, float)):
                            head_ts = float(ts)
                    except (ValueError, TypeError):
                        head_ts = None

                if agg_inserted or agg_updated or agg_deleted:
                    return (
                        [
                            ChangeEvent(
                                commit_id=current_head,
                                author=head_author,
                                message=head_message,
                                timestamp=head_ts,
                                inserted=agg_inserted,
                                updated=agg_updated,
                                deleted=agg_deleted,
                            )
                        ],
                        current_head,
                    )
                return ([], current_head)

            events.append(
                ChangeEvent(
                    commit_id=ident,
                    author=author,
                    message=message,
                    timestamp=timestamp,
                    inserted=inserted,
                    updated=updated,
                    deleted=deleted,
                )
            )

        return (events, current_head)

    async def _diff_commit(
        self,
        branch: str,
        entry: dict[str, Any],
        newer_entries: list[dict[str, Any]],
        index: int,
        all_entries: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        """Diff *entry* against its parent commit via POST /api/diff.

        Returns (inserted, updated, deleted) lists of document @ids.
        """
        ident = str(entry.get("identifier", ""))

        # Determine parent commit identifier.
        # The parent is the entry immediately after this one in the
        # full (newest-first) log, OR the next entry in newer_entries
        # (since newer_entries is oldest-first, the next entry after
        # this one in the full log is the prev entry in full log).
        parent_ident: str | None = None
        # Try to find in the full log (newest-first)
        for i_ent, log_entry in enumerate(all_entries):
            if str(log_entry.get("identifier", "")) == ident and i_ent + 1 < len(all_entries):
                parent_ident = str(all_entries[i_ent + 1].get("identifier", ""))
                break

        if parent_ident is None:
            # Fallback: if the entry is not the last in newer_entries,
            # the next entry (older, further along) might be the parent
            if index + 1 < len(newer_entries):
                parent_ident = str(newer_entries[index + 1].get("identifier", ""))

        if parent_ident is None:
            # First commit in the range — no parent to diff against.
            return ([], [], [])

        before_descriptor = f"{self.org}/{self.db}/local/commit/{parent_ident}"
        after_descriptor = f"{self.org}/{self.db}/local/commit/{ident}"

        return await self._diff_between(before_descriptor, after_descriptor)

    async def _diff_between(
        self, before_descriptor: str, after_descriptor: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Diff two commit descriptors via POST /api/diff.

        Returns (inserted, updated, deleted) lists of document @ids.
        """
        try:
            response = await self._client.post(
                f"/api/diff/{self.org}/{self.db}",
                json={
                    "before_data_version": before_descriptor,
                    "after_data_version": after_descriptor,
                    "document_id": "",
                    "keep": {"@id": "", "@type": ""},
                },
            )
            await self._raise_on_error(response)
            patches = response.json()
        except TdbError:
            raise

        inserted: list[str] = []
        updated: list[str] = []
        deleted: list[str] = []

        # The diff API may return a dict with patches or a list of patches.
        patch_list: list[dict[str, Any]] = []
        if isinstance(patches, dict):
            patch_list = patches.get("patch", patches.get("patches", []))
            if not isinstance(patch_list, list):
                patch_list = [patches] if patches else []
        elif isinstance(patches, list):
            patch_list = patches

        for patch in patch_list:
            if not isinstance(patch, dict):
                continue
            op = patch.get("op", patch.get("@op", ""))
            doc_id = patch.get("@id", patch.get("id", patch.get("document", "")))
            if not doc_id:
                continue
            if op in ("Insert", "insert", "Create", "create"):
                inserted.append(str(doc_id))
            elif op in ("Replace", "replace", "Update", "update"):
                updated.append(str(doc_id))
            elif op in ("Delete", "delete"):
                deleted.append(str(doc_id))

        return (inserted, updated, deleted)

    # ------------------------------------------------------------------
    # Single-commit diff
    # ------------------------------------------------------------------

    async def get_commit_diff(
        self, commit_id: str, branch: str = "main"
    ) -> tuple[list[str], list[str], list[str]]:
        """Return (inserted, updated, deleted) document IDs for *commit_id*.

        Diffs the commit against its parent, found by scanning the branch log.
        For the initial commit (no parent), returns empty lists — matching
        the boundary behaviour of :meth:`_diff_commit`.

        Raises ``StaleCommitError`` if *commit_id* is not found in the
        fetched log window, or if the window may be truncated.
        """
        log_entries = await self.get_branch_log(branch, count=self._LOG_REQUEST_CAP)

        # Find the commit and its parent (next entry in newest-first log).
        commit_idx: int | None = None
        for idx, entry in enumerate(log_entries):
            if str(entry.get("identifier", "")) == commit_id:
                commit_idx = idx
                break

        if commit_idx is None:
            if len(log_entries) >= self._LOG_REQUEST_CAP:
                raise TdbError(
                    400,
                    f"Commit '{commit_id}' not found in fetched log window "
                    f"({self._LOG_REQUEST_CAP} entries) for branch "
                    f"'{branch}'; log may be truncated.",
                )
            raise StaleCommitError(commit_id, branch)

        parent_ident: str | None = None
        if commit_idx + 1 < len(log_entries):
            parent_ident = str(log_entries[commit_idx + 1].get("identifier", ""))

        if parent_ident is None:
            # Initial commit — no parent to diff against.
            return ([], [], [])

        before_desc = f"{self.org}/{self.db}/local/commit/{parent_ident}"
        after_desc = f"{self.org}/{self.db}/local/commit/{commit_id}"
        return await self._diff_between(before_desc, after_desc)
