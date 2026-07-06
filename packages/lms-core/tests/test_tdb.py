"""Tests for lms_core.tdb – TerminusDB HTTP client (respx-mocked, async)."""

from __future__ import annotations

import json

import httpx
import pytest
from lms_core.tdb import TdbClient, TdbError, full_iri, short_iri

BASE = "http://test.example.com:6363"
ORG = "admin"
DB = "testdb"


# ---------------------------------------------------------------------------
# Unit tests for IRI helpers
# ---------------------------------------------------------------------------


class TestShortIri:
    def test_full_to_short(self):
        assert short_iri("terminusdb:///data/InboxNote/abc123") == "InboxNote/abc123"

    def test_already_short_passthrough(self):
        assert short_iri("InboxNote/abc123") == "InboxNote/abc123"

    def test_arbitrary_already_short(self):
        assert short_iri("Foo/bar") == "Foo/bar"


class TestFullIri:
    def test_short_to_full(self):
        assert full_iri("InboxNote/abc123") == "terminusdb:///data/InboxNote/abc123"

    def test_already_full_passthrough(self):
        assert (
            full_iri("terminusdb:///data/InboxNote/abc123")
            == "terminusdb:///data/InboxNote/abc123"
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
    c = TdbClient(base_url=BASE, org=ORG, db=DB, user="admin", password="root")
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
            {"@id": "InboxNote/abc", "status": "new"},
            {"@id": "InboxNote/def", "status": "processed"},
        ],
    )

    result = await client.get_documents("InboxNote")

    assert route.called
    req = route.calls.last.request
    assert req.url.params["graph_type"] == "instance"
    assert req.url.params["type"] == "InboxNote"
    assert req.url.params["as_list"] == "true"
    assert "authorization" in req.headers  # basic auth present

    assert len(result) == 2
    assert result[0]["@id"] == "InboxNote/abc"


async def test_get_documents_custom_branch(client, respx_mock):
    route = respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/develop",
    ).respond(json=[])

    await client.get_documents("Task", branch="develop")
    assert route.called


# ---------------------------------------------------------------------------
# insert_documents
# ---------------------------------------------------------------------------


async def test_insert_documents(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=["terminusdb:///data/InboxNote/C29bUs1tzWpLMioB"],
    )

    docs = [{"@type": "InboxNote", "content": "hello", "status": "new"}]
    result = await client.insert_documents(docs)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "ingestd"
    assert req.url.params["message"] == "ingestd"
    assert req.url.params["graph_type"] == "instance"

    # Body must be the docs array
    body = req.read()
    parsed = json.loads(body)
    assert parsed == docs

    assert result == ["terminusdb:///data/InboxNote/C29bUs1tzWpLMioB"]


async def test_insert_documents_custom_message(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    await client.insert_documents([], message="custom commit")
    req = route.calls.last.request
    assert req.url.params["message"] == "custom commit"


async def test_insert_documents_custom_author(client, respx_mock):
    """The *author* keyword-only parameter controls the commit author."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    await client.insert_documents([], author="queryd")
    req = route.calls.last.request
    assert req.url.params["author"] == "queryd"
    # Default message still works
    assert req.url.params["message"] == "ingestd"


# ---------------------------------------------------------------------------
# replace_document
# ---------------------------------------------------------------------------


async def test_replace_document(client, respx_mock):
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=["terminusdb:///data/InboxNote/abc123"])

    doc = {"@id": "InboxNote/abc123", "@type": "InboxNote", "status": "processed"}
    await client.replace_document(doc)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "ingestd"
    assert req.url.params["graph_type"] == "instance"

    sent = json.loads(req.read())
    assert sent["@id"] == "InboxNote/abc123"
    assert sent["status"] == "processed"


async def test_replace_document_missing_at_id_raises_valueerror(client, respx_mock):
    """ValueError before any HTTP call when @id is missing."""
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=[])

    with pytest.raises(ValueError, match="@id"):
        await client.replace_document({"@type": "InboxNote", "status": "new"})

    assert not route.called


async def test_replace_document_custom_author(client, respx_mock):
    """The *author* keyword-only parameter controls the commit author."""
    route = respx_mock.put(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(json=["terminusdb:///data/Task/abc"])

    doc = {"@id": "Task/abc", "@type": "Task", "status": "open"}
    await client.replace_document(doc, author="queryd", message="status change")
    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "queryd"
    assert req.url.params["message"] == "status change"


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
        await client.get_documents("InboxNote")

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
    respx_mock.get(
        f"{BASE}/api/document/{ORG}/{DB}/local/branch/main",
    ).respond(
        json=[
            {"@id": "InboxNote/a", "status": "new"},
            {"@id": "InboxNote/b", "status": "processed"},
            {"@id": "InboxNote/c", "status": "new"},
        ],
    )

    result = await client.get_documents_by_status("InboxNote", "new")
    assert len(result) == 2
    assert all(d["status"] == "new" for d in result)
    assert result[0]["@id"] == "InboxNote/a"
    assert result[1]["@id"] == "InboxNote/c"


# ---------------------------------------------------------------------------
# graphql
# ---------------------------------------------------------------------------


async def test_graphql_returns_data(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        json={"data": {"InboxNote": [{"_id": "InboxNote/abc", "status": "new"}]}},
    )

    result = await client.graphql("{ InboxNote { _id status } }")
    assert route.called
    assert result == {
        "InboxNote": [{"_id": "InboxNote/abc", "status": "new"}],
    }


async def test_graphql_with_variables(client, respx_mock):
    route = respx_mock.post(f"{BASE}/api/graphql/{ORG}/{DB}").respond(
        json={"data": {"InboxNote": []}},
    )

    result = await client.graphql(
        "query($s: String) { InboxNote(filter:{status:{eq:$s}}){_id} }",
        variables={"s": "new"},
    )

    assert route.called
    req = route.calls.last.request
    body = json.loads(req.read())
    assert body["variables"] == {"s": "new"}
    assert result == {"InboxNote": []}


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
        await client.graphql("{ InboxNote { _id } }")

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
    assert req.url.params["author"] == "ingestd"
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


async def test_push_schema_custom_author_message(client, respx_mock):
    """Keyword-only author and message are forwarded."""
    route = respx_mock.post(
        f"{BASE}/api/document/{ORG}/{DB}",
    ).respond(status_code=200, json=[])

    await client.push_schema(
        [], author="schema-bot", message="v2 migration"
    )
    assert route.called
    req = route.calls.last.request
    assert req.url.params["author"] == "schema-bot"
    assert req.url.params["message"] == "v2 migration"


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
# graphql with branch
# ---------------------------------------------------------------------------


async def test_graphql_branch_scoped(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/graphql/{ORG}/{DB}/local/branch/feature",
    ).respond(json={"data": {"InboxNote": [{"_id": "a", "content": "branch"}]}})

    result = await client.graphql(
        "{ InboxNote { _id content } }", branch="feature"
    )
    assert route.called
    assert result == {"InboxNote": [{"_id": "a", "content": "branch"}]}


async def test_graphql_branch_none_uses_default(client, respx_mock):
    route = respx_mock.post(
        f"{BASE}/api/graphql/{ORG}/{DB}",
    ).respond(json={"data": {"InboxNote": []}})

    await client.graphql("{ InboxNote { _id } }")
    assert route.called


# ---------------------------------------------------------------------------
# async context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager():
    async with TdbClient(base_url=BASE, org=ORG, db=DB, user="u", password="p") as c:
        assert isinstance(c._client, httpx.AsyncClient)
        assert not c._client.is_closed
    # After exit the client is closed
    assert c._client.is_closed
