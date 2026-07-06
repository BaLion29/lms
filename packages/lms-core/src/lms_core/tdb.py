"""Thin typed async TerminusDB HTTP client using httpx."""

from __future__ import annotations

from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PREFIX = "terminusdb:///data/"


def short_iri(iri: str) -> str:
    """Convert ``terminusdb:///data/X/Y`` → ``X/Y``.

    Passes through if already short (no prefix).
    """
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
        *,
        timeout: float = 30.0,
    ) -> None:
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
        self, type_: str, branch: str = "main"
    ) -> list[dict[str, Any]]:
        """Fetch all documents of *type_* from *branch*."""
        response = await self._client.get(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "type": type_,
                "as_list": "true",
            },
        )
        await self._raise_on_error(response)
        return response.json()  # type: ignore[no-any-return]

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
        *,
        author: str = "ingestd",
    ) -> list[str]:
        """Insert *docs* and return the list of full IRIs."""
        response = await self._client.post(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "author": author,
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
        author: str = "ingestd",
    ) -> None:
        """Replace a single document (must contain ``@id``).

        Raises ``ValueError`` if *doc* is missing ``@id``.
        """
        if not doc.get("@id"):
            raise ValueError("Document must contain '@id' for replace")
        response = await self._client.put(
            self._doc_path(branch),
            params={
                "graph_type": "instance",
                "author": author,
                "message": message,
            },
            json=doc,
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
        author: str = "ingestd",
        message: str = "bootstrap",
    ) -> None:
        """Push/replace the full schema (``full_replace=true``, idempotent).

        When *branch* is ``"main"`` the schema is pushed to the default
        (non-branch-scoped) path for backward compatibility.  For any other
        branch the branch-scoped document path is used.
        """
        if branch == "main":
            path = f"/api/document/{self.org}/{self.db}"
        else:
            path = self._doc_path(branch)

        response = await self._client.post(
            path,
            params={
                "graph_type": "schema",
                "full_replace": "true" if full_replace else "false",
                "author": author,
                "message": message,
            },
            json=schema,
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
        """Fetch *type_* documents on *branch* and filter by ``status`` in Python."""
        docs = await self.get_documents(type_, branch=branch)
        return [d for d in docs if d.get("status") == status]
