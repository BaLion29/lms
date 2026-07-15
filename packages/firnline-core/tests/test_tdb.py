"""Tests for firnline_core.tdb – TerminusDB HTTP client (respx-mocked, async)."""

from __future__ import annotations

import json

import httpx
import pytest
import structlog
from firnline_core.tdb import (
    ChangeEvent,
    StaleCommitError,
    TdbClient,
    TdbConflictError,
    TdbError,
    full_iri,
    short_iri,
)

BASE = "http://test.example.com:6363"
ORG = "admin"
DB = "testdb"


# ---------------------------------------------------------------------------
# Unit tests for IRI helpers
# ---------------------------------------------------------------------------


class TestShortIri:
    def test_full_to_short(self):
        assert short_iri("terminusdb:///data/Captured/abc123") == "Captured/abc123"

    def test_already_short_passthrough(self):
        assert short_iri("Captured/abc123") == "Captured/abc123"

    def test_arbitrary_already_short(self):
        assert short_iri("Foo/bar") == "Foo/bar"


class TestFullIri:
    def test_short_to_full(self):
        assert full_iri("Captured/abc123") == "terminusdb:///data/Captured/abc123"

    def test_already_full_passthrough(self):
        assert (
            full_iri("terminusdb:///data/Captured/abc123")
            == "terminusdb:///data/Captured/abc123"
        )

    def test_arbitrary_short(self):
        assert full_iri("Foo/bar") == "terminusdb:///data/Foo/bar"


# ---------------------------------------------------------------------------
# TdbError
# ---------------------------------------------------------------------------


def test_tdberror_str_includes_status_and_body():
    e = TdbError(400, '{"api:message":"bad request"}')
    s = str(e)
    assert "400" in s
    assert "bad request" in s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    c = TdbClient(base_url=BASE, org=ORG, db=DB, user="admin", password="root", author="service:ingestd")
    yield c
    await c.aclose()


# ---------------------------------------------------------------------------
# get_documents
# ---------------------------------------------------------------------------


async def test_get_documents(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"@id": "Captured/abc", "status": "new"},
            {"@id": "Captured/def", "status": "processed"},
        ],
    )

    result = await client.get_documents("Captured")

    assert route.called
    req = route.calls.last.request
    assert req.url.params["graph_type"] == "instance"
    assert req.url.params["type"] == "Captured"
    assert req.url.params["as_list"] == "true"
    assert "authorization" in req.headers  # basic auth present

    assert len(result) == 2
    assert result[0]["@id"] == "Captured/abc"


async def test_get_documents_custom_branch(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/develop",
    ).respond(json=[])

    await client.get_documents("Task", branch="develop")
    assert route.called


async def test_get_documents_with_skip_and_count(client, respx_mock):
    """skip and count are forwarded as query params."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"@id": "Captured/abc"},
        ],
    )

    result = await client.get_documents("Captured", skip=10, count=5)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["skip"] == "10"
    assert req.url.params["count"] == "5"
    assert req.url.params["type"] == "Captured"
    assert req.url.params["as_list"] == "true"
    assert len(result) == 1


async def test_get_documents_skip_count_omitted_when_none(client, respx_mock):
    """When skip/count are None, the params are absent from the request."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    await client.get_documents("Captured")

    assert route.called
    req = route.calls.last.request
    assert "skip" not in req.url.params
    assert "count" not in req.url.params


# ---------------------------------------------------------------------------
# count_documents
# ---------------------------------------------------------------------------


async def test_count_documents_bare_integer(client, respx_mock):
    """TerminusDB returns a bare integer when count=true is supported."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(text="42")

    result = await client.count_documents("Captured")

    assert route.called
    req = route.calls.last.request
    assert req.url.params["count"] == "true"
    assert req.url.params["type"] == "Captured"
    assert req.url.params["graph_type"] == "instance"
    assert result == 42


async def test_count_documents_json_count_key(client, respx_mock):
    """If the response is a JSON object with a 'count' key, extract it."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json={"count": 7, "@type": "api:CountResponse"})

    result = await client.count_documents("Task")

    assert route.called
    assert result == 7


async def test_count_documents_fallback_list_len(client, respx_mock):
    """If the server returns a list (e.g. no count=true support), use len()."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"@id": "Cap/1"},
            {"@id": "Cap/2"},
            {"@id": "Cap/3"},
        ],
    )

    result = await client.count_documents("Captured")

    assert route.called
    assert result == 3


async def test_count_documents_json_string_body(client, respx_mock):
    """If the server returns a JSON-encoded string like "42", parse it."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(text='"42"')  # JSON string, not bare integer

    result = await client.count_documents("Captured")

    assert route.called
    assert result == 42


async def test_count_documents_non_2xx_raises_tdberror(client, respx_mock):
    """Non-2xx responses propagate as TdbError."""
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=500, text="boom")

    with pytest.raises(TdbError) as exc_info:
        await client.count_documents("Captured")

    assert exc_info.value.status == 500


async def test_count_documents_custom_branch(client, respx_mock):
    """Branch parameter is forwarded."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/develop",
    ).respond(text="0")

    result = await client.count_documents("Task", branch="develop")

    assert route.called
    assert result == 0


# ---------------------------------------------------------------------------
# insert_documents
# ---------------------------------------------------------------------------


async def test_insert_documents(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=["terminusdb:///data/Captured/C29bUs1tzWpLMioB"],
    )

    docs = [{"@type": "Captured", "content": "hello", "status": "new"}]
    result = await client.insert_documents(docs)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "service:ingestd"
    assert req.url.params["message"] == "ingestd"
    assert req.url.params["graph_type"] == "instance"

    # Body must be the docs array
    body = req.read()
    parsed = json.loads(body)
    assert parsed == docs

    assert result == ["terminusdb:///data/Captured/C29bUs1tzWpLMioB"]


async def test_insert_documents_custom_message(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    await client.insert_documents([], message="custom commit")
    req = route.calls.last.request
    assert req.url.params["message"] == "custom commit"


async def test_insert_documents_custom_author(respx_mock):
    """The *author* constructor argument controls the commit author."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    c = TdbClient(base_url=BASE, org=ORG, db=DB, user="admin", password="root", author="service:queryd")
    try:
        await c.insert_documents([])
        req = route.calls.last.request
        assert req.url.params["author"] == "service:queryd"
        assert req.url.params["message"] == "ingestd"
    finally:
        await c.aclose()


# ---------------------------------------------------------------------------
# replace_document
# ---------------------------------------------------------------------------


async def test_replace_document(client, respx_mock):
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=["terminusdb:///data/Captured/abc123"])

    doc = {"@id": "Captured/abc123", "@type": "Captured", "status": "processed"}
    await client.replace_document(doc)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "service:ingestd"
    assert req.url.params["graph_type"] == "instance"

    sent = json.loads(req.read())
    assert sent["@id"] == "Captured/abc123"
    assert sent["status"] == "processed"


async def test_replace_document_missing_at_id_raises_valueerror(client, respx_mock):
    """ValueError before any HTTP call when @id is missing."""
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    with pytest.raises(ValueError, match="@id"):
        await client.replace_document({"@type": "Captured", "status": "new"})

    assert not route.called


async def test_replace_document_custom_author(respx_mock):
    """The *author* constructor argument controls the commit author."""
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=["terminusdb:///data/Task/abc"])

    c = TdbClient(base_url=BASE, org=ORG, db=DB, user="admin", password="root", author="service:queryd")
    try:
        doc = {"@id": "Task/abc", "@type": "Task", "status": "open"}
        await c.replace_document(doc, message="status change")
        assert route.called
        req = route.calls.last.request
        assert req.url.params["author"] == "service:queryd"
        assert req.url.params["message"] == "status change"
    finally:
        await c.aclose()


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


async def test_get_document_short_iri(client, respx_mock):
    """Fetch a single document by short IRI."""
    doc = {"@id": "Task/abc", "@type": "Task", "name": "Test", "status": "open"}
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=doc)

    result = await client.get_document("Task/abc")

    assert route.called
    req = route.calls.last.request
    assert req.url.params["id"] == "Task/abc"
    assert result == doc


async def test_get_document_full_iri(client, respx_mock):
    """Full IRI is normalised to short before the request."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json={"@id": "Task/abc", "@type": "Task"})

    result = await client.get_document("terminusdb:///data/Task/abc")

    assert route.called
    req = route.calls.last.request
    assert req.url.params["id"] == "Task/abc"
    assert result["@id"] == "Task/abc"


async def test_get_document_custom_branch(client, respx_mock):
    """Branch parameter is forwarded."""
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/develop",
    ).respond(json={"@id": "Task/abc"})

    await client.get_document("Task/abc", branch="develop")
    assert route.called


async def test_get_document_404_raises_tdberror(client, respx_mock):
    """Non-2xx (e.g. 404) raises TdbError."""
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=404, text='{"api:message":"not found"}')

    with pytest.raises(TdbError) as exc_info:
        await client.get_document("Task/nonexistent")

    assert exc_info.value.status == 404


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


async def test_non_2xx_raises_tdberror_with_verbatim_body(client, respx_mock):
    error_body = (
        '{"@type":"api:InsertDocumentErrorResponse",'
        '"api:error":{"@type":"api:SchemaCheckFailure",'
        '"api:witnesses":[]},'
        '"api:message":"Schema check failure",'
        '"api:status":"api:failure"}'
    )
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=400, text=error_body)

    with pytest.raises(TdbError) as exc_info:
        await client.get_documents("Captured")

    assert exc_info.value.status == 400
    assert exc_info.value.body == error_body


# ---------------------------------------------------------------------------
# get_schema
# ---------------------------------------------------------------------------


async def test_get_schema(client, respx_mock):
    schema_payload = [
        {"@type": "@context", "@base": "terminusdb:///data/"},
        {"@id": "Source", "@type": "Class", "@abstract": []},
        {"@id": "Task", "@type": "Class", "@inherits": "Source", "name": "xsd:string"},
    ]
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=schema_payload)

    result = await client.get_schema()

    assert route.called
    req = route.calls.last.request
    assert req.url.params["graph_type"] == "schema"
    assert req.url.params["as_list"] == "true"
    assert result == schema_payload


async def test_get_schema_custom_branch(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/develop",
    ).respond(json=[])

    await client.get_schema(branch="develop")
    assert route.called


# ---------------------------------------------------------------------------
# get_documents_by_status
# ---------------------------------------------------------------------------


async def test_get_documents_by_status(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"@id": "Captured/a", "status": "new"},
            {"@id": "Captured/b", "status": "new"},
        ],
    )

    result = await client.get_documents_by_status("Captured", "new")
    assert route.called
    req = route.calls.last.request
    # Assert the query param is sent for server-side filtering
    assert "query" in req.url.params
    query_val = json.loads(req.url.params["query"])
    assert query_val["@type"] == "Captured"
    assert query_val["status"] == "new"
    assert req.url.params["graph_type"] == "instance"
    assert req.url.params["type"] == "Captured"
    assert req.url.params["as_list"] == "true"

    assert len(result) == 2
    assert all(d["status"] == "new" for d in result)
    assert result[0]["@id"] == "Captured/a"


# ---------------------------------------------------------------------------
# graphql
# ---------------------------------------------------------------------------


async def test_graphql_returns_data(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        json={"data": {"Captured": [{"_id": "Captured/abc", "status": "new"}]}},
    )

    result = await client.graphql("{ Captured { _id status } }")
    assert route.called
    assert result == {
        "Captured": [{"_id": "Captured/abc", "status": "new"}],
    }


async def test_graphql_with_variables(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        json={"data": {"Captured": []}},
    )

    result = await client.graphql(
        "query($s: String) { Captured(filter:{status:{eq:$s}}){_id} }",
        variables={"s": "new"},
    )

    assert route.called
    req = route.calls.last.request
    body = json.loads(req.read())
    assert body["variables"] == {"s": "new"}
    assert result == {"Captured": []}


async def test_graphql_200_with_errors_raises_tdberror(client, respx_mock):
    error_body = '{"data":null,"errors":[{"message":"Field does not exist"}]}'
    respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        status_code=200, text=error_body
    )

    with pytest.raises(TdbError) as exc_info:
        await client.graphql("{ BadField }")

    assert exc_info.value.status == 200
    assert exc_info.value.body == error_body


async def test_graphql_non_200_raises_tdberror(client, respx_mock):
    respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        status_code=500, text="Internal Server Error"
    )

    with pytest.raises(TdbError) as exc_info:
        await client.graphql("{ Captured { _id } }")

    assert exc_info.value.status == 500
    assert exc_info.value.body == "Internal Server Error"


# ---------------------------------------------------------------------------
# db_exists
# ---------------------------------------------------------------------------


async def test_db_exists_true(client, respx_mock):
    route = respx_mock.get(f"{BASE}/api/db/{ORG}/{DB}").respond(
        status_code=200,
        json={"name": DB},
    )
    assert await client.db_exists() is True
    assert route.called


async def test_db_exists_false(client, respx_mock):
    route = respx_mock.get(f"{BASE}/api/db/{ORG}/{DB}").respond(
        status_code=404,
        json={"api:message": "not found"},
    )
    assert await client.db_exists() is False
    assert route.called


# ---------------------------------------------------------------------------
# create_db
# ---------------------------------------------------------------------------


async def test_create_db(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/db/{ORG}/{DB}").respond(
        status_code=201,
        json={"name": DB},
    )
    await client.create_db(label="testdb", comment="hello")
    assert route.called
    req = route.calls.last.request
    body = json.loads(req.read())
    assert body["label"] == "testdb"
    assert body["comment"] == "hello"
    assert body["schema"] is True


async def test_create_db_defaults(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/db/{ORG}/{DB}").respond(
        status_code=201,
        json={"name": DB},
    )
    await client.create_db()
    assert route.called
    req = route.calls.last.request
    body = json.loads(req.read())
    assert body["label"] == DB
    assert body["comment"] == "created by ingestd bootstrap"
    assert body["schema"] is True


async def test_create_db_non_2xx_raises_tdberror(client, respx_mock):
    respx_mock.post(f"{BASE}/api/db/{ORG}/{DB}").respond(
        status_code=409, text="Database already exists"
    )
    with pytest.raises(TdbError) as exc_info:
        await client.create_db()
    assert exc_info.value.status == 409


# ---------------------------------------------------------------------------
# push_schema
# ---------------------------------------------------------------------------


async def test_push_schema(client, respx_mock):
    schema_payload = [{"@type": "@context"}, {"@id": "Foo", "@type": "Class"}]
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}",
    ).respond(status_code=200, json=[])

    await client.push_schema(schema_payload)
    assert route.called
    req = route.calls.last.request
    assert req.url.params["graph_type"] == "schema"
    assert req.url.params["full_replace"] == "true"
    assert req.url.params["author"] == "service:ingestd"
    assert req.url.params["message"] == "bootstrap"

    sent = json.loads(req.read())
    assert sent == schema_payload


async def test_push_schema_non_2xx_raises_tdberror(client, respx_mock):
    respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}",
    ).respond(status_code=400, text="bad schema")
    with pytest.raises(TdbError) as exc_info:
        await client.push_schema([])
    assert exc_info.value.status == 400


async def test_push_schema_custom_branch(client, respx_mock):
    """When branch != main the branch-scoped document path is used."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/feature",
    ).respond(status_code=200, json=[])

    await client.push_schema(
        [{"@id": "Foo", "@type": "Class"}], branch="feature"
    )
    assert route.called
    req = route.calls.last.request
    assert req.url.params["graph_type"] == "schema"
    assert req.url.params["full_replace"] == "true"


async def test_push_schema_without_full_replace(client, respx_mock):
    """full_replace=False sends 'false'."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}",
    ).respond(status_code=200, json=[])

    await client.push_schema([], full_replace=False)
    assert route.called
    assert route.calls.last.request.url.params["full_replace"] == "false"


async def test_push_schema_custom_author_message(respx_mock):
    """The *author* constructor argument controls the commit author."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}",
    ).respond(status_code=200, json=[])

    c = TdbClient(base_url=BASE, org=ORG, db=DB, user="admin", password="root", author="service:schema-bot")
    try:
        await c.push_schema(
            [], message="v2 migration"
        )
        assert route.called
        req = route.calls.last.request
        assert req.url.params["author"] == "service:schema-bot"
        assert req.url.params["message"] == "v2 migration"
    finally:
        await c.aclose()


# ---------------------------------------------------------------------------
# Branch operations
# ---------------------------------------------------------------------------


async def test_create_branch(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/branch/{ORG}/{DB}/local/branch/feature",
    ).respond(status_code=200, json={"api:status": "api:success"})

    await client.create_branch("feature")
    assert route.called
    body = json.loads(route.calls.last.request.read())
    assert body == {"origin": "main"}


async def test_create_branch_custom_origin(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/branch/{ORG}/{DB}/local/branch/develop",
    ).respond(status_code=200, json={"api:status": "api:success"})

    await client.create_branch("develop", origin="feature")
    assert route.called
    body = json.loads(route.calls.last.request.read())
    assert body == {"origin": "feature"}


async def test_create_branch_already_exists_raises(client, respx_mock):
    respx_mock.post(
        f"{BASE}/api/branch/{ORG}/{DB}/local/branch/feature",
    ).respond(status_code=400, text="Branch exists")

    with pytest.raises(TdbError) as exc_info:
        await client.create_branch("feature")
    assert exc_info.value.status == 400


async def test_delete_branch(client, respx_mock):
    route = respx_mock.delete(
        f"{BASE}/api/branch/{ORG}/{DB}/local/branch/feature",
    ).respond(status_code=200, json={"api:status": "api:success"})

    await client.delete_branch("feature")
    assert route.called


async def test_delete_branch_non_existent_raises(client, respx_mock):
    respx_mock.delete(
        f"{BASE}/api/branch/{ORG}/{DB}/local/branch/nope",
    ).respond(status_code=400, text="No such branch")

    with pytest.raises(TdbError) as exc_info:
        await client.delete_branch("nope")
    assert exc_info.value.status == 400


async def test_branch_exists_true(client, respx_mock):
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=200, json=[])
    assert await client.branch_exists("main") is True


async def test_branch_exists_false(client, respx_mock):
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/nonexistent",
    ).respond(status_code=400, text="UnresolvableAbsoluteDescriptor")
    assert await client.branch_exists("nonexistent") is False

    req = respx_mock.calls.last.request
    assert req.url.params["count"] == "1"
    assert req.url.params["graph_type"] == "instance"


# ---------------------------------------------------------------------------
# reset_branch (promote)
# ---------------------------------------------------------------------------


async def test_reset_branch(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/reset/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=200, json={"api:status": "api:success"})

    await client.reset_branch(
        "main",
        "admin/testdb/local/commit/abc123",
    )
    assert route.called
    body = json.loads(route.calls.last.request.read())
    assert body == {"commit_descriptor": "admin/testdb/local/commit/abc123"}


async def test_reset_branch_to_feature(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/reset/{ORG}/{DB}/local/branch/main",
    ).respond(status_code=200)

    await client.reset_branch("main", "admin/testdb/local/commit/feat")
    assert route.called


# ---------------------------------------------------------------------------
# get_branch_head
# ---------------------------------------------------------------------------


async def test_get_branch_head(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "abc123", "author": "system", "message": "commit"},
        ],
    )

    head = await client.get_branch_head("main")
    assert head == "abc123"
    assert route.called


async def test_get_branch_head_empty_raises(client, respx_mock):
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    with pytest.raises(Exception):
        await client.get_branch_head("main")


# ---------------------------------------------------------------------------
# graphql with branch
# ---------------------------------------------------------------------------


async def test_graphql_branch_scoped(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/graphql/{ORG}/{DB}/local/branch/feature",
    ).respond(json={"data": {"Captured": [{"_id": "a", "content": "branch"}]}})

    result = await client.graphql(
        "{ Captured { _id content } }", branch="feature"
    )
    assert route.called
    assert result == {"Captured": [{"_id": "a", "content": "branch"}]}


async def test_graphql_branch_none_uses_default(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/graphql/{ORG}/{DB}",
    ).respond(json={"data": {"Captured": []}})

    await client.graphql("{ Captured { _id } }")
    assert route.called


# ---------------------------------------------------------------------------
# async context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager():
    async with TdbClient(base_url=BASE, org=ORG, db=DB, user="u", password="p", author="service:ingestd") as c:
        assert isinstance(c._client, httpx.AsyncClient)
        assert not c._client.is_closed
    # After exit the client is closed
    assert c._client.is_closed


# ---------------------------------------------------------------------------
# replace_document with expected_head
# ---------------------------------------------------------------------------


async def test_replace_document_expected_head_match(client, respx_mock):
    """When expected_head matches, replace proceeds normally."""
    # Mock the branch head check
    log_route = respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[{"identifier": "abc123", "author": "system", "message": "commit"}],
    )

    put_route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=["terminusdb:///data/Task/abc"])

    doc = {"@id": "Task/abc", "@type": "Task", "status": "done"}
    await client.replace_document(doc, expected_head="abc123")

    assert log_route.called
    assert put_route.called


async def test_replace_document_expected_head_conflict(client, respx_mock):
    """When expected_head differs, TdbConflictError is raised and no PUT."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[{"identifier": "xyz789", "author": "other", "message": "commit"}],
    )

    put_route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    doc = {"@id": "Task/abc", "@type": "Task", "status": "done"}
    try:
        await client.replace_document(doc, expected_head="abc123")
        assert False, "should have raised"
    except TdbConflictError as exc:
        assert exc.expected == "abc123"
        assert exc.actual == "xyz789"
        assert exc.status == 409
    except TdbError:
        pass  # subclass is catchable as TdbError too

    assert not put_route.called


# ---------------------------------------------------------------------------
# changes_since
# ---------------------------------------------------------------------------


async def test_changes_since_none_commit_baseline(client, respx_mock):
    """commit_id=None returns ([], current_head)."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[{"identifier": "HEAD", "author": "x", "message": "m"}],
    )

    events, head = await client.changes_since(None)
    assert events == []
    assert head == "HEAD"


async def test_changes_since_same_head(client, respx_mock):
    """When commit_id == current_head, returns ([], head)."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[{"identifier": "HEAD", "author": "x", "message": "m"}],
    )

    events, head = await client.changes_since("HEAD")
    assert events == []
    assert head == "HEAD"


async def test_changes_since_new_commits(client, respx_mock):
    """New commits after commit_id are returned oldest-first."""
    # Mock get_branch_log — newest-first
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "third"},
            {"identifier": "C2", "author": "b", "message": "second"},
            {"identifier": "C1", "author": "c", "message": "first"},
        ],
    )

    # Mock diff endpoint for C2 (parent C1)
    respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(
        json={
            "patch": [
                {"op": "Insert", "@id": "Task/1"},
                {"op": "Replace", "@id": "Task/2"},
            ]
        },
    )

    # respx matches by URL only, but we make 2 diff calls for C2 and C3.
    # The diff response handler will match both.
    events, head = await client.changes_since("C1")
    assert head == "C3"
    assert len(events) == 2

    # Oldest first: C2, then C3
    assert events[0].commit_id == "C2"
    assert events[0].author == "b"
    assert events[0].message == "second"
    assert "Task/1" in events[0].inserted
    assert "Task/2" in events[0].updated

    assert events[1].commit_id == "C3"
    assert events[1].author == "a"
    assert events[1].message == "third"
    # Same diff mock — both insert+replace
    assert "Task/1" in events[1].inserted
    assert "Task/2" in events[1].updated


async def test_changes_since_diff_delete(client, respx_mock):
    """Diff with delete op is classified correctly."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C2", "author": "a", "message": "del"},
            {"identifier": "C1", "author": "b", "message": "base"},
        ],
    )

    respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(
        json={"patch": [{"op": "Delete", "@id": "Task/deleted"}]},
    )

    events, head = await client.changes_since("C1")
    assert head == "C2"
    assert len(events) == 1
    assert events[0].deleted == ["Task/deleted"]


async def test_changes_since_stale_commit_raises(client, respx_mock):
    """When commit_id not in log, StaleCommitError is raised."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C2", "author": "a", "message": "new"},
            {"identifier": "C1", "author": "b", "message": "old"},
        ],
    )

    # Also mock diff — it should never be called
    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(json={"patch": []})

    with pytest.raises(StaleCommitError) as exc_info:
        await client.changes_since("C0", branch="main")

    assert exc_info.value.commit_id == "C0"
    assert exc_info.value.branch == "main"
    assert not diff_route.called


async def test_changes_since_stale_commit_custom_branch(client, respx_mock):
    """Branch is stored in StaleCommitError."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/feature",
    ).respond(
        json=[
            {"identifier": "C1", "author": "b", "message": "old"},
        ],
    )

    respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(json={"patch": []})

    with pytest.raises(StaleCommitError) as exc_info:
        await client.changes_since("C0", branch="feature")

    assert exc_info.value.branch == "feature"


async def test_changes_since_limit_with_valid_old_commit(client, respx_mock):
    """limit caps returned events but does NOT cause false staleness."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C5", "author": "a", "message": "5th"},
            {"identifier": "C4", "author": "b", "message": "4th"},
            {"identifier": "C3", "author": "c", "message": "3rd"},
            {"identifier": "C2", "author": "d", "message": "2nd"},
            {"identifier": "C1", "author": "e", "message": "1st"},
        ],
    )

    respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(json={"patch": []})

    # C1 is 5 entries back; limit=3 should still find it and return 3 events
    events, head = await client.changes_since("C1", limit=3)
    assert head == "C5"
    assert len(events) == 3
    # oldest first: C2, C3, C4
    assert [e.commit_id for e in events] == ["C2", "C3", "C4"]


async def test_changes_since_truncated_log_raises_tdberror(client, respx_mock):
    """When commit not found AND entries == cap, raise TdbError (not Stale)."""
    # Simulate truncation by using a tiny cap
    client._LOG_REQUEST_CAP = 3

    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "3rd"},
            {"identifier": "C2", "author": "b", "message": "2nd"},
            {"identifier": "C1", "author": "c", "message": "1st"},
        ],
    )

    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(json={"patch": []})

    with pytest.raises(TdbError) as exc_info:
        await client.changes_since("C0")

    assert exc_info.value.status == 400
    assert "truncated" in exc_info.value.body.lower()
    assert "C0" in exc_info.value.body
    assert not isinstance(exc_info.value, StaleCommitError)
    assert not diff_route.called


async def test_changes_since_notvalidref_falls_back_to_aggregate_diff(client, respx_mock):
    """Per-commit NotValidRefError → aggregate diff succeeds → single event."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "third"},
            {"identifier": "C2", "author": "b", "message": "second"},
            {"identifier": "C1", "author": "c", "message": "first"},
        ],
    )

    # Side-effect handler: per-commit diffs fail, aggregate C1→C3 succeeds
    def _diff_side_effect(request, **kwargs):
        import json as _json

        body = _json.loads(request.content)
        before = body["before_data_version"]
        after = body["after_data_version"]
        if "C3" in after and "C1" in before:
            # Aggregate: C1 → C3
            return httpx.Response(
                200,
                json={
                    "patch": [
                        {"op": "Insert", "@id": "Task/1"},
                        {"op": "Replace", "@id": "Task/2"},
                    ]
                },
            )
        # Per-commit (C1→C2 or C2→C3): NotValidRefError
        return httpx.Response(
            400,
            text='{"api:error":"api:NotValidRefError","api:message":"Not a valid ref"}',
        )

    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
        name="diff",
    )
    diff_route.side_effect = _diff_side_effect

    with structlog.testing.capture_logs() as captured:
        events, head = await client.changes_since("C1", branch="main")

    assert head == "C3"
    assert len(events) == 1
    assert events[0].commit_id == "C3"
    assert events[0].author == "a"
    assert events[0].message == "third"
    assert "Task/1" in events[0].inserted
    assert "Task/2" in events[0].updated
    assert events[0].deleted == []

    # Warning was logged
    warnings = [e for e in captured if e.get("event") == "diff_window_aggregated"]
    assert len(warnings) == 1
    assert warnings[0]["branch"] == "main"
    assert warnings[0]["cursor"] == "C1"
    assert warnings[0]["head"] == "C3"
    assert warnings[0]["commits"] == 2


async def test_changes_since_aggregate_diff_also_stale_raises(client, respx_mock):
    """Both per-commit AND aggregate diffs fail with NotValidRefError → Stale."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "third"},
            {"identifier": "C2", "author": "b", "message": "second"},
            {"identifier": "C1", "author": "c", "message": "first"},
        ],
    )

    # Both per-commit and aggregate return NotValidRefError
    notvalid_body = '{"api:error":"api:NotValidRefError","api:message":"Not a valid ref"}'
    respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(status_code=400, text=notvalid_body)

    with pytest.raises(StaleCommitError) as exc_info:
        await client.changes_since("C1")

    assert exc_info.value.commit_id == "C1"
    assert exc_info.value.branch == "main"
    # Should be chained from the aggregate TdbError
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, TdbError)


async def test_changes_since_aggregate_diff_other_error_propagates(client, respx_mock):
    """Per-commit NotValidRefError, aggregate 500 → plain TdbError."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "third"},
            {"identifier": "C2", "author": "b", "message": "second"},
            {"identifier": "C1", "author": "c", "message": "first"},
        ],
    )

    def _diff_side_effect(request, **kwargs):
        import json as _json

        body = _json.loads(request.content)
        after = body["after_data_version"]
        if "C3" in after:
            # Aggregate: 500
            return httpx.Response(500, text="Internal Server Error")
        # Per-commit: NotValidRefError
        return httpx.Response(
            400,
            text='{"api:error":"api:NotValidRefError","api:message":"Not a valid ref"}',
        )

    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
        name="diff",
    )
    diff_route.side_effect = _diff_side_effect

    with pytest.raises(TdbError) as exc_info:
        await client.changes_since("C1")

    assert exc_info.value.status == 500
    assert not isinstance(exc_info.value, StaleCommitError)


async def test_changes_since_aggregate_empty_diff_returns_no_events(client, respx_mock):
    """Aggregate diff with empty patch returns ([], head)."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C3", "author": "a", "message": "third"},
            {"identifier": "C2", "author": "b", "message": "second"},
            {"identifier": "C1", "author": "c", "message": "first"},
        ],
    )

    def _diff_side_effect(request, **kwargs):
        import json as _json

        body = _json.loads(request.content)
        after = body["after_data_version"]
        if "C3" in after:
            # Aggregate: empty patch
            return httpx.Response(200, json={"patch": []})
        # Per-commit: NotValidRefError
        return httpx.Response(
            400,
            text='{"api:error":"api:NotValidRefError","api:message":"Not a valid ref"}',
        )

    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
        name="diff",
    )
    diff_route.side_effect = _diff_side_effect

    events, head = await client.changes_since("C1")
    assert events == []
    assert head == "C3"


async def test_changes_since_diff_other_error_propagates(client, respx_mock):
    """A non-NotValidRefError from diff propagates as plain TdbError (no aggregate)."""
    respx_mock.get(
        f"{BASE}/api/log/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"identifier": "C2", "author": "a", "message": "new"},
            {"identifier": "C1", "author": "b", "message": "old"},
        ],
    )

    diff_route = respx_mock.post(
        f"{BASE}/api/diff/{ORG}/{DB}",
    ).respond(status_code=500, text="Internal Server Error")

    with pytest.raises(TdbError) as exc_info:
        await client.changes_since("C1")

    assert exc_info.value.status == 500
    assert not isinstance(exc_info.value, StaleCommitError)
    # Only one call: per-commit fails immediately, aggregate never attempted
    assert diff_route.call_count == 1


# ---------------------------------------------------------------------------
# StaleCommitError
# ---------------------------------------------------------------------------


def test_stale_commit_error_is_tdberror():
    """StaleCommitError is a subclass of TdbError."""
    e = StaleCommitError("abc", "main")
    assert isinstance(e, TdbError)
    assert e.status == 400
    assert e.commit_id == "abc"
    assert e.branch == "main"


def test_stale_commit_error_message():
    """StaleCommitError produces a descriptive message."""
    e = StaleCommitError("deadbeef", "main")
    msg = str(e)
    assert "deadbeef" in msg
    assert "main" in msg
    assert "400" in msg


# ---------------------------------------------------------------------------
# TdbConflictError
# ---------------------------------------------------------------------------


def test_tdbconflict_error_is_tdberror():
    """TdbConflictError is a subclass of TdbError."""
    e = TdbConflictError("expected", "actual")
    assert isinstance(e, TdbError)
    assert e.status == 409
    assert "expected" in e.body
    assert "actual" in e.body


def test_tdbconflict_error_attributes():
    """TdbConflictError stores expected and actual heads."""
    e = TdbConflictError("abc", "xyz")
    assert e.expected == "abc"
    assert e.actual == "xyz"


# ---------------------------------------------------------------------------
# ChangeEvent dataclass
# ---------------------------------------------------------------------------


def test_change_event_construction():
    """ChangeEvent can be constructed with defaults."""
    ev = ChangeEvent(commit_id="abc", author="x", message="msg")
    assert ev.commit_id == "abc"
    assert ev.author == "x"
    assert ev.message == "msg"
    assert ev.timestamp is None
    assert ev.inserted == []
    assert ev.updated == []
    assert ev.deleted == []


def test_change_event_with_data():
    """ChangeEvent with all fields populated."""
    ev = ChangeEvent(
        commit_id="abc",
        author="x",
        message="msg",
        timestamp=1234567890.0,
        inserted=["Task/1"],
        updated=["Task/2"],
        deleted=["Task/3"],
    )
    assert ev.inserted == ["Task/1"]
    assert ev.updated == ["Task/2"]
    assert ev.deleted == ["Task/3"]
    assert ev.timestamp == 1234567890.0
