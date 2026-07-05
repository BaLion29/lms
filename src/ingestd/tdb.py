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
                "author": "ingestd",
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
                "author": "ingestd",
                "message": message,
            },
            json=doc,
        )
        await self._raise_on_error(response)

    async def graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query and return the ``data`` field.

        Raises ``TdbError`` on non-2xx **or** when the response contains
        an ``errors`` field (GraphQL can return 200 with errors).
        """
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        response = await self._client.post(
            f"/api/graphql/{self.org}/{self.db}",
            json=payload,
        )
        await self._raise_on_error(response)
        body: dict[str, Any] = response.json()
        if body.get("errors"):
            raise TdbError(response.status_code, response.text)
        return body.get("data", {})  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def get_documents_by_status(
        self, type_: str, status: str, branch: str = "main"
    ) -> list[dict[str, Any]]:
        """Fetch *type_* documents on *branch* and filter by ``status`` in Python."""
        docs = await self.get_documents(type_, branch=branch)
        return [d for d in docs if d.get("status") == status]
