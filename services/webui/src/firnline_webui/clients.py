"""Async HTTP clients for backend service communication.

Tokens are kept server-side — never exposed to the Reflex browser.
All clients raise :class:`WebuiClientError` on failure.
"""

from __future__ import annotations

from typing import Any

import httpx

from firnline_core.tdb import TdbClient as _CoreTdbClient
from firnline_core.tdb import TdbError


class WebuiClientError(Exception):
    """Raised by webui clients on HTTP/non-JSON errors."""

    def __init__(self, status: int | None, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"WebuiClientError({status}): {detail}")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def schema_classes(schema: list[dict]) -> list[dict]:
    """Filter *schema* to class definitions only.

    Skips the ``@context`` entry and enum definitions; returns entries whose
    ``@type`` is ``"Class"``.
    """
    result: list[dict] = []
    for entry in schema:
        if entry.get("@type") == "Class":
            result.append(entry)
    return result


def class_display_fields(class_def: dict) -> list[str]:
    """Return up-to-5 preferred display field names for a class definition.

    Prefers ``@metadata.label_field`` if present, then in order: name, title,
    text, status, kind, created_at, updated_at.  Fills remaining slots (up to
    5) with other non-``@`` keys alphabetically.
    """
    # Schema-driven label field takes priority
    meta = class_def.get("@metadata")
    if isinstance(meta, dict):
        lf = meta.get("label_field")
        if isinstance(lf, str) and lf and lf in class_def:
            preferred = [lf, "name", "title", "text", "status", "kind", "created_at", "updated_at"]
        else:
            preferred = ["name", "title", "text", "status", "kind", "created_at", "updated_at"]
    else:
        preferred = ["name", "title", "text", "status", "kind", "created_at", "updated_at"]

    fields: list[str] = []

    for p in preferred:
        if p in class_def and p not in fields:
            fields.append(p)

    remaining = sorted(k for k in class_def if not k.startswith("@") and k not in fields)
    fields.extend(remaining)

    return fields[:5]


# ---------------------------------------------------------------------------
# Base client
# ---------------------------------------------------------------------------


def _make_client(
    base_url: str,
    token: str,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=httpx.Timeout(timeout),
        transport=transport,
    )


async def _healthz_raw(client: httpx.AsyncClient, path: str = "/healthz") -> dict[str, Any]:
    """GET *path*, return parsed JSON even on non-2xx (if JSON-parsable)."""
    try:
        resp = await client.get(path)
    except httpx.RequestError as exc:
        raise WebuiClientError(None, f"transport error: {exc!s}") from exc
    try:
        data: dict[str, Any] = resp.json()
    except ValueError as exc:
        raise WebuiClientError(resp.status_code, f"non-JSON response: {resp.text[:500]}") from exc
    return data


# ---------------------------------------------------------------------------
# CapturedClient
# ---------------------------------------------------------------------------


class CapturedClient:
    """Async client for the captured service."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    async def aclose(self) -> None:
        """Close the underlying transport if any.

        The httpx client instances used by each method are created and
        closed inside ``async with`` blocks, so there is no persistent
        client to close here.  This method exists for API consistency
        with ``TdbBrowser`` so that callers can use a uniform
        ``try: … finally: await client.aclose()`` pattern.
        """

    async def healthz(self) -> dict[str, Any]:
        """GET /healthz — return JSON body even on 503."""
        async with _make_client(self._base_url, self._token, self._timeout, self._transport) as client:
            return await _healthz_raw(client)

    async def capture_note(
        self,
        text: str,
        kind: str = "note",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capture/note — returns 201 JSON."""
        payload: dict[str, Any] = {"text": text, "kind": kind}
        if metadata is not None:
            payload["metadata"] = metadata
        async with _make_client(self._base_url, self._token, self._timeout, self._transport) as client:
            try:
                resp = await client.post("/v1/capture/note", json=payload)
            except httpx.RequestError as exc:
                raise WebuiClientError(None, f"transport error: {exc!s}") from exc
            if resp.status_code == 201:
                return resp.json()  # type: ignore[no-any-return]
            raise WebuiClientError(
                resp.status_code,
                _safe_detail(resp),
            )

    async def capture_file(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        kind: str = "file",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capture/file multipart — returns 201 JSON."""
        data: dict[str, Any] = {"kind": kind}
        if metadata is not None:
            import json as _json

            data["metadata"] = _json.dumps(metadata)

        async with _make_client(self._base_url, self._token, self._timeout, self._transport) as client:
            try:
                resp = await client.post(
                    "/v1/capture/file",
                    files={"file": (filename, content, content_type)},
                    data=data,
                )
            except httpx.RequestError as exc:
                raise WebuiClientError(None, f"transport error: {exc!s}") from exc
            if resp.status_code == 201:
                return resp.json()  # type: ignore[no-any-return]
            raise WebuiClientError(
                resp.status_code,
                _safe_detail(resp),
            )


# ---------------------------------------------------------------------------
# QuerydClient
# ---------------------------------------------------------------------------


class QuerydClient:
    """Async client for the queryd service."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    async def healthz(self) -> dict[str, Any]:
        """GET /healthz — return JSON body even on 503."""
        async with _make_client(self._base_url, self._token, self._timeout, self._transport) as client:
            return await _healthz_raw(client)


# ---------------------------------------------------------------------------
# ServiceHealthClient — generic healthz client for services with optional auth
# ---------------------------------------------------------------------------


class ServiceHealthClient:
    """Async healthz client for services with optional bearer auth.

    Used for both indexed and mcpd.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    async def healthz(self) -> dict[str, Any]:
        """GET /healthz — return JSON body even on 503."""
        async with _make_client(self._base_url, self._token, self._timeout, self._transport) as client:
            return await _healthz_raw(client)


# ---------------------------------------------------------------------------
# TdbBrowser — wraps firnline_core TdbClient
# ---------------------------------------------------------------------------


class TdbBrowser:
    """Thin wrapper around ``firnline_core.tdb.TdbClient`` for the web UI.

    Translates ``TdbError`` to ``WebuiClientError`` and exposes a subset of
    read‑only operations.
    """

    def __init__(
        self,
        base_url: str,
        org: str,
        db: str,
        user: str,
        password: str,
        *,
        branch: str = "main",
        timeout: float = 30.0,
        tdb: _CoreTdbClient | None = None,
    ) -> None:
        self._branch = branch
        if tdb is not None:
            self._tdb = tdb
        else:
            self._tdb = _CoreTdbClient(
                base_url=base_url,
                org=org,
                db=db,
                user=user,
                password=password,
                timeout=timeout,
                author="service:webui",
            )

    async def _call(self, coro):
        try:
            return await coro
        except TdbError as exc:
            raise WebuiClientError(exc.status, exc.body) from exc

    async def get_schema(self) -> list[dict[str, Any]]:
        """Fetch full schema (branch-scoped)."""
        return await self._call(self._tdb.get_schema(branch=self._branch))

    async def get_modules(self) -> list[dict[str, Any]]:
        """Fetch SchemaModule documents."""
        return await self._call(self._tdb.get_documents("SchemaModule", branch=self._branch))

    async def get_documents(self, type_: str) -> list[dict[str, Any]]:
        """Fetch all documents of *type_*."""
        return await self._call(self._tdb.get_documents(type_, branch=self._branch))

    async def get_document(self, iri: str) -> dict[str, Any]:
        """Fetch a single document by IRI."""
        return await self._call(self._tdb.get_document(iri, branch=self._branch))

    async def aclose(self) -> None:
        await self._tdb.aclose()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_tdb_browser() -> TdbBrowser:
    """Return a ``TdbBrowser`` configured from application settings."""
    from firnline_webui.settings import get_settings

    s = get_settings()
    return TdbBrowser(
        s.tdb_url,
        s.tdb_org,
        s.tdb_db,
        s.tdb_user,
        s.tdb_password,
        branch=s.tdb_branch,
        timeout=s.request_timeout_seconds,
    )


def make_health_clients() -> tuple[CapturedClient, QuerydClient, ServiceHealthClient, ServiceHealthClient]:
    """Return ``(CapturedClient, QuerydClient, indexed_client, mcpd_client)`` configured from application settings."""
    from firnline_webui.settings import get_settings

    s = get_settings()
    timeout = s.request_timeout_seconds
    return (
        CapturedClient(s.captured_url, s.captured_api_token, timeout=timeout),
        QuerydClient(s.queryd_url, s.queryd_api_token, timeout=timeout),
        ServiceHealthClient(s.indexed_url, token=s.indexed_api_token, timeout=timeout),
        ServiceHealthClient(s.mcpd_url, timeout=timeout),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_detail(resp: httpx.Response) -> str:
    """Extract detail from a JSON error response, falling back to text."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            return str(body.get("detail", resp.text[:500]))
        return resp.text[:500]
    except ValueError:
        return resp.text[:500]
