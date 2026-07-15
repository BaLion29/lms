# Testing

All of firnline's test conventions, commands, and patterns. There is **no CI** —
tests run locally and are gated by `scripts/validate-release.sh` before
releases.

## Framework

- **pytest** with **pytest-asyncio** in `asyncio_mode = "auto"` — async test
  functions and fixtures require no `@pytest.mark.asyncio` decorator.
- **respx** for HTTP mocking (`respx_mock: respx.MockRouter` fixture) —
  used extensively in service tests to mock TerminusDB API calls. No real
  network requests in unit tests.
- **pydantic-ai `FunctionModel`** for LLM-free extraction tests in ingestd
  (tests provide canned model responses without calling an actual LLM).

Default pytest invocation (set in root `pyproject.toml`):

```
addopts = --import-mode=importlib -m 'not integration'
```

This imports tests via `importlib` (consistent with the src-layout) and
excludes integration tests.

## Running tests

```bash
uv run pytest                                  # all non-integration tests
uv run pytest -m "not integration"             # equivalent (the default)
uv run pytest -m integration                   # integration tests ONLY
uv run pytest packages/firnline-core           # single package
uv run pytest services/queryd/tests            # single service test dir
uv run pytest -k "test_healthz"                # keyword match
```

## Integration tests

Marked with `@pytest.mark.integration` or a module-level
`pytestmark = pytest.mark.integration`. Excluded from the default suite
because they require a running TerminusDB dev instance at
`localhost:6363` (admin/root).

There is exactly **one** integration test file in the repo:
`packages/firnline-schema/tests/test_integration_apply.py`. It validates the
real schema apply/validate/promote workflow against a live TerminusDB.

To run it:

```bash
# Start a dev TerminusDB first
docker run -d --name tdb-dev -p 6363:6363 terminusdb/terminusdb-server:v12.0.6
# Run the integration tests
uv run pytest -m integration
```

## Test layout

77 test files across all 16 workspace packages:

| Location | Test files | Coverage |
|---|---|---|
| `packages/firnline-core/tests/` | 9 | Plugin system, TDB client, semver, settings, durations, templates, conventions, generated models |
| `packages/firnline-schema/tests/` | 10 | Composer, differ, applier, codegen (fresh + incremental), CLI diff |
| `services/queryd/tests/` | 8 | App, endpoints, post-documents API, operations, plugins, schema briefing, settings, tools API |
| `services/ingestd/tests/` | 7 | Extraction agent, linking, pipeline, sources, plugin host, settings, liveness |
| `services/triggerd/tests/` | 6 | Engine, evaluators, plugin host, settings, liveness, smoke |
| `services/webui/tests/` | 11 | Introspect, introspection graph, health state, clients, automations, auth, feedback, calendar, settings, shell, states cleanup |
| `services/effectd/tests/` | 4 | Engine, legacy notify, settings, smoke |
| `services/mcpd/tests/` | 3 | Tools, dynamic tools, settings |
| `services/captured/tests/` | 2 | App, handlers |
| `services/indexed/tests/` | 2 | Poller, store |
| `extensions/firnline-ext-time-management/tests/` | 5 | Discovery, extractor, indexer, tools, tool specs |
| `extensions/firnline-ext-reminders/tests/` | 4 | Discovery, extractor, tools, tool specs |
| `extensions/firnline-ext-people/tests/` | 2 | Discovery, extractor |
| `extensions/firnline-ext-gotify/tests/` | 2 | Channel, executor |
| `extensions/firnline-ext-webhook/tests/` | 1 | Executor |
| `extensions/firnline-ext-places/tests/` | 1 | Discovery |

The `scripts/melt_test/` directory also contains a pytest suite (run by the
melt test script, not part of the main collection) that verifies the kernel
composes and imports correctly with zero extensions.

## Mocking patterns

### TerminusDB endpoints with respx

The standard pattern for services (example from `queryd/tests/test_app.py`):

```python
import respx
from fastapi.testclient import TestClient

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"

def test_healthz_up(respx_mock: respx.MockRouter):
    respx_mock.get(f"{TDB_URL}/api/db/admin/{TDB_DB}").respond(200)
    with _client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
```

respx routes are registered per test function via the `respx_mock` fixture.

### LLM-free extraction tests

ingestd extraction tests use `pydantic_ai.models.function.FunctionModel` to
provide deterministic model responses:

```python
from pydantic_ai.models.function import FunctionModel

model = FunctionModel(
    function=lambda _messages, _info: ModelResponse(
        parts=[TextPart(content='{"kind": "task", "title": "Buy milk"}')]
    )
)
```

### Async tests

pytest-asyncio `asyncio_mode = "auto"` means async test functions and async
fixtures work without any marker:

```python
async def test_something(tdb: AsyncMock) -> None:
    result = await my_async_function(tdb)
    assert result == expected
```

## Testing plugins and extensions

Plugin validation tests (e.g., in `firnline-core/tests/test_plugins.py`)
use `AsyncMock` for the TDB client and assert on requirement-checking,
plugin discovery, and selection logic — no real network.

Extension discovery tests (e.g., `firnline-ext-time-management/tests/test_discovery.py`)
verify package structure: that `manifest.json` and `schema.json` exist, have
the correct `name`, `version`, and `exports`, and that entry points resolve.
These are pure Python tests with no fixtures.

Service-level plugin host tests (e.g., `queryd/tests/test_plugins.py`,
`triggerd/tests/test_plugin_host.py`) wire up the full `PluginHost` lifecycle
against a mocked TerminusDB, exercising strict vs. non-strict host policies.

## Related documents

- [local-development.md](local-development.md) — dev environment setup
- [release-process.md](release-process.md) — how tests are gated at release
- [extension-development.md](extension-development.md) — testing your extensions
