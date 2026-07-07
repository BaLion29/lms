"""Thin async HTTP client for the indexed service.

Mirrors ``TdbClient``'s style: typed errors, non-2xx raises ``IndexedError``,
timeouts honoured.  Both ``ingestd`` and ``queryd`` import this to call
indexed's ``/v1/find_*`` endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class IndexedError(Exception):
    """Raised when the indexed service returns a non-2xx or network error."""

    def __init__(self, status: int | None, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"indexed error ({status}): {message}")


@dataclass
class EntityCandidate:
    iri: str
    class_name: str
    name: str
    aliases: list[str]
    score: float
    commit_id: str


@dataclass
class ClassCandidate:
    class_name: str
    description: str
    score: float


@dataclass
class FieldCandidate:
    class_name: str
    field: str
    type: str
    description: str
    score: float


class IndexedClient:
    """Async HTTP client for the ``indexed`` service.

    Usage::

        async with IndexedClient("http://indexed:8089", token="...") as client:
            candidates = await client.find_entity("Anna", classes=["Person"])
    """

    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        timeout: float = 10.0,
    ) -> None:
        base = base_url.rstrip("/")
        self._base_url = base
        self._token = token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> IndexedClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("IndexedClient not opened")
        return self._client

    # ------------------------------------------------------------------
    # find_entity
    # ------------------------------------------------------------------

    async def find_entity(
        self,
        text: str,
        *,
        classes: list[str] | None = None,
        branch: str = "main",
        k: int = 5,
    ) -> list[EntityCandidate]:
        """Search for entities matching *text*."""
        body: dict[str, Any] = {"text": text, "branch": branch, "k": k}
        if classes:
            body["classes"] = classes
        data = await self._post("/v1/find_entity", body)
        return [
            EntityCandidate(
                iri=c["iri"],
                class_name=c.get("class", c.get("class_name", "")),
                name=c.get("name", ""),
                aliases=c.get("aliases", []),
                score=c.get("score", 0.0),
                commit_id=c.get("commit_id", ""),
            )
            for c in data.get("candidates", [])
        ]

    # ------------------------------------------------------------------
    # find_class
    # ------------------------------------------------------------------

    async def find_class(self, text: str, *, k: int = 5) -> list[ClassCandidate]:
        """Search for schema classes matching *text*."""
        body: dict[str, Any] = {"text": text, "k": k}
        data = await self._post("/v1/find_class", body)
        return [
            ClassCandidate(
                class_name=c.get("class", ""),
                description=c.get("description", ""),
                score=c.get("score", 0.0),
            )
            for c in data.get("candidates", [])
        ]

    # ------------------------------------------------------------------
    # find_field
    # ------------------------------------------------------------------

    async def find_field(
        self,
        text: str,
        *,
        class_name: str | None = None,
        k: int = 5,
    ) -> list[FieldCandidate]:
        """Search for schema fields matching *text*."""
        body: dict[str, Any] = {"text": text, "k": k}
        if class_name:
            body["class"] = class_name
        data = await self._post("/v1/find_field", body)
        return [
            FieldCandidate(
                class_name=c.get("class", ""),
                field=c.get("field", ""),
                type=c.get("type", ""),
                description=c.get("description", ""),
                score=c.get("score", 0.0),
            )
            for c in data.get("candidates", [])
        ]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def healthz(self) -> dict[str, Any]:
        """Return the indexed /healthz payload."""
        try:
            response = await self.client.get(
                f"{self._base_url}/healthz",
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            raise IndexedError(None, f"connection failed: {e}") from e
        return response.json()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = await self.client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise IndexedError(None, f"connection failed: {e}") from e
        if response.status_code != 200:
            raise IndexedError(response.status_code, response.text[:500])
        return response.json()
