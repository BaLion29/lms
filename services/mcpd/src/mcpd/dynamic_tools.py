"""Dynamic tool discovery: fetch write-tool specs from queryd and build
wrapping functions whose signatures reproduce the original JSON schema so
that FastMCP's func_metadata can derive the correct input model."""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Optional

import httpx
import structlog
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import create_model
from typing_extensions import Literal

from mcpd._http import build_client, raise_for_status
from mcpd.settings import McpdSettings

logger = structlog.get_logger(__name__)


# ── JSON schema → Python type mapping ────────────────────────────────────────


def _json_type_to_python(prop_schema: dict[str, Any]) -> Any:
    """Map a JSON schema property to a Python type annotation."""
    # Handle nullable: anyOf with null → Optional[inner]
    if "anyOf" in prop_schema:
        non_null = [s for s in prop_schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            inner = _json_type_to_python(non_null[0])
            return Optional[inner]
        return Optional[Any]

    json_type: str = prop_schema.get("type", "string")

    # Enum on string → Literal[...]
    if "enum" in prop_schema:
        values: list[str] = prop_schema["enum"]
        # Must unpack to get `Literal["a","b"]` not `Literal[("a","b")]`
        return Literal.__getitem__(tuple(values))

    if json_type == "string":
        return str
    elif json_type == "integer":
        return int
    elif json_type == "number":
        return float
    elif json_type == "boolean":
        return bool
    elif json_type == "array":
        items = prop_schema.get("items", {})
        if isinstance(items, dict) and items.get("type") == "object":
            return list[dict[str, Any]]
        return list[Any]
    elif json_type == "object":
        return dict[str, Any]
    else:
        return Any


# ── Tool-spec fetching ───────────────────────────────────────────────────────


async def fetch_tool_specs(settings: McpdSettings) -> list[dict[str, Any]]:
    """GET /v1/tools from queryd; return the tools list.

    On any error (connection refused, timeout, non-2xx response, writes
    disabled → empty list) we log a warning and return [], so mcpd always
    starts even when queryd is unreachable.
    """
    if not settings.queryd_url:
        return []
    try:
        async with build_client(
            settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds
        ) as client:
            resp = await client.get("/v1/tools")
            raise_for_status(resp)
            data: dict[str, Any] = resp.json()
            tools: list[dict[str, Any]] = data.get("tools", [])
            return tools
    except (httpx.ConnectError, httpx.TimeoutException, ToolError) as exc:
        logger.warning("Failed to fetch tool specs from queryd", error=str(exc))
        return []
    except Exception as exc:
        logger.warning("Unexpected error fetching tool specs from queryd", error=str(exc))
        return []


# ── Function builder ─────────────────────────────────────────────────────────


def _ensure_optional(annotation: Any) -> Any:
    """If *annotation* does not already include ``None`` in its Union args,
    wrap it in ``Optional[...]`` so that func_metadata produces a nullable
    JSON schema."""
    args = typing.get_args(annotation)
    if type(None) in args:
        return annotation  # already nullable
    return Optional[annotation]


def build_tool_function(spec: dict[str, Any], settings: McpdSettings) -> Callable[..., Any]:
    """From a tool spec, build an async function whose signature reproduces
    the input_schema so FastMCP can derive the correct JSON schema.

    Steps:
    1. Parse `input_schema` properties → Python types + required/optional.
    2. Build a Pydantic model to validate the mapping (task requirement).
    3. Extract field annotations & defaults from the model.
    4. Synthesize a wrapper with __signature__, __annotations__, __name__,
       and __doc__; the body POSTs to /v1/tools/{name}.
    """
    name: str = spec["name"]
    input_schema: dict[str, Any] = spec.get("input_schema", {})
    properties: dict[str, Any] = input_schema.get("properties", {})
    required: set[str] = set(input_schema.get("required", []))

    # ── Build pydantic model fields ──────────────────────────────────────
    model_fields: dict[str, Any] = {}
    for field_name, prop_schema in properties.items():
        py_type = _json_type_to_python(prop_schema)
        if field_name not in required:
            default_val = prop_schema.get("default", None)
            model_fields[field_name] = (py_type, default_val)
        else:
            model_fields[field_name] = (py_type, ...)

    # Create the model (task requires using pydantic.create_model)
    model_name = f"{name}Args"
    try:
        _model = create_model(model_name, **model_fields)
    except Exception:
        logger.warning("Failed to create pydantic model for tool %s", name)
        raise

    # ── Extract field annotations & defaults from model ─────────────────
    field_annotations: dict[str, Any] = {}
    for fn, fi in _model.model_fields.items():
        ann = fi.annotation
        if not fi.is_required():
            ann = _ensure_optional(ann)
        field_annotations[fn] = ann

    # ── Build function parameters ───────────────────────────────────────
    params: list[inspect.Parameter] = []
    for field_name, field_info in _model.model_fields.items():
        annotation = field_info.annotation
        if not field_info.is_required():
            annotation = _ensure_optional(annotation)
            default = field_info.default if field_info.default is not None else None
        else:
            default = inspect.Parameter.empty
        params.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )

    # ── Synthesize the wrapper function ──────────────────────────────────
    async def _impl(**kwargs: Any) -> dict[str, Any]:
        """Proxy a write-tool call to queryd."""
        payload = {k: v for k, v in kwargs.items() if v is not None}
        async with build_client(
            settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds
        ) as client:
            try:
                resp = await client.post(f"/v1/tools/{name}", json=payload)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                raise ToolError(str(exc)) from None
            raise_for_status(resp)
            return resp.json()

    wrapper_name = name
    # Ensure the name is a valid Python identifier (replace hyphens etc.)
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in wrapper_name)

    wrapper = _impl
    annotations: dict[str, Any] = {**field_annotations, "return": dict[str, Any]}
    wrapper.__signature__ = inspect.Signature(params, return_annotation=dict[str, Any])
    wrapper.__annotations__ = annotations
    wrapper.__name__ = safe_name
    wrapper.__doc__ = spec.get("description", f"Write tool: {name}")
    wrapper.__qualname__ = safe_name
    wrapper.__module__ = __name__

    return wrapper
