"""Queryd ToolSpec plugin for address-book operations (lookup, CRUD, geocode)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from firnline_core.generated.core import Provenance
from firnline_core.plugins import ModuleRequirement
from firnline_core.toolspec import ToolContext, ToolSpec
from firnline_core.toolspec_helpers import (
    error_envelope,
    make_repo,
    not_found_envelope,
    ok_envelope,
    type_mismatch_error,
    write_error_envelope,
)

from firnline_ext_address_book.geocode import GeocodingClient
from firnline_ext_address_book.models import (
    Contact,
    Location,
    Organization,
    Person,
)

_UTC = timezone.utc
_AGENT = "ext:address-book"

# ---------------------------------------------------------------------------
# Args models
# ---------------------------------------------------------------------------


class LookupArgs(BaseModel):
    """Search address-book entities by name/alias substring."""

    query: str = Field(description="Substring to match (case-insensitive)")
    limit: int = Field(default=10, description="Maximum number of results")
    kind: str | None = Field(
        default=None,
        description="Optional filter: 'person', 'location', or 'organization'",
    )


class GetArgs(BaseModel):
    """Fetch a single address-book entity by IRI."""

    id: str = Field(description="The document IRI (e.g. 'Person/abc123')")


class CreatePersonArgs(BaseModel):
    """Create a new Person document."""

    name: str = Field(description="Full name of the person")
    aliases: list[str] = Field(default_factory=list, description="Optional aliases")
    email: str | None = Field(default=None, description="Optional email address")
    phone: str | None = Field(default=None, description="Optional phone number")
    domicile_id: str | None = Field(default=None, description="Optional Location IRI for domicile")


class CreateLocationArgs(BaseModel):
    """Create a new Location document."""

    name: str = Field(description="Location name")
    aliases: list[str] = Field(default_factory=list, description="Optional aliases")
    address: str | None = Field(default=None, description="Optional street address")
    lat: float | None = Field(default=None, description="Optional latitude")
    lon: float | None = Field(default=None, description="Optional longitude")


class CreateOrganizationArgs(BaseModel):
    """Create a new Organization document."""

    name: str = Field(description="Organization name")
    aliases: list[str] = Field(default_factory=list, description="Optional aliases")
    location_id: str | None = Field(default=None, description="Optional Location IRI for headquarters")


class GeocodeArgs(BaseModel):
    """Geocode a query string or a stored Location by IRI (exactly one required)."""

    query: str | None = Field(default=None, description="Address/place name to geocode")
    location_id: str | None = Field(default=None, description="Location IRI to geocode and persist")


# ---------------------------------------------------------------------------
# Core business logic (_do_ functions)
# ---------------------------------------------------------------------------


async def _do_lookup(
    query: str,
    limit: int,
    kind: str | None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Case-insensitive substring match on name + aliases across entity types."""
    lowered = query.casefold()

    classes: list[tuple[str, str]] = []
    if kind is None:
        classes = [
            ("Person", "person"),
            ("Location", "location"),
            ("Organization", "organization"),
        ]
    elif kind == "person":
        classes = [("Person", "person")]
    elif kind == "location":
        classes = [("Location", "location")]
    elif kind == "organization":
        classes = [("Organization", "organization")]
    else:
        return error_envelope(f"invalid kind filter: {kind!r}")

    hits: list[dict[str, object]] = []

    for cls_name, cls_type in classes:
        try:
            docs = await tdb.get_documents(cls_name, branch=branch)
        except Exception:
            continue  # skip classes that may not exist

        for doc in docs:
            name: str = doc.get("name", "")
            aliases: list[str] = doc.get("aliases", [])
            searchable = [name, *aliases]
            if any(lowered in s.casefold() for s in searchable):
                hits.append(
                    {
                        "id": doc.get("@id", ""),
                        "type": cls_type,
                        "name": name,
                        "aliases": aliases,
                    }
                )
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break

    return ok_envelope(hits=hits[:limit])


async def _do_get(
    id_: str,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Fetch a single document by IRI."""
    try:
        doc = await tdb.get_document(id_, branch=branch)
    except Exception as exc:
        return not_found_envelope(id_, exc)

    return ok_envelope(doc=doc)


async def _validate_location(
    location_id: str,
    *,
    tdb: Any,
    branch: str,
) -> str | None:
    """Validate *location_id* exists and is a Location. Returns error string or None."""
    try:
        doc = await tdb.get_document(location_id, branch=branch)
    except Exception as exc:
        return f"location not found: {location_id}: {exc}"

    if doc.get("@type") != "Location":
        type_err = type_mismatch_error(location_id, doc, "Location")
        if type_err is not None:
            return type_err

    return None


async def _do_create_person(
    name: str,
    aliases: list[str],
    email: str | None,
    phone: str | None,
    domicile_id: str | None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Person document."""
    repo = make_repo(tdb, transitions={})

    if domicile_id is not None:
        err = await _validate_location(domicile_id, tdb=tdb, branch=branch)
        if err is not None:
            return {"ok": False, "error": err}

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    person = Person(
        name=name,
        aliases=aliases,
        contact=(
            Contact(email=email, phone=phone, domicile=domicile_id)
            if (email is not None or phone is not None or domicile_id is not None)
            else None
        ),
        provenance=prov,
    ).to_tdb()

    try:
        iri = await repo.create(person, agent=_AGENT, method="tool_call", branch=branch)
    except Exception as exc:
        return write_error_envelope(exc)

    return ok_envelope(iri=iri)


async def _do_create_location(
    name: str,
    aliases: list[str],
    address: str | None,
    lat: float | None,
    lon: float | None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Location document."""
    repo = make_repo(tdb, transitions={})

    coordinates: tuple[float, float] | None = None
    if lat is not None and lon is not None:
        coordinates = (lat, lon)

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    loc = Location(
        name=name,
        aliases=aliases,
        address=address,
        coordinates=coordinates,
        provenance=prov,
    ).to_tdb()

    try:
        iri = await repo.create(loc, agent=_AGENT, method="tool_call", branch=branch)
    except Exception as exc:
        return write_error_envelope(exc)

    return ok_envelope(iri=iri)


async def _do_create_organization(
    name: str,
    aliases: list[str],
    location_id: str | None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Organization document."""
    repo = make_repo(tdb, transitions={})

    if location_id is not None:
        err = await _validate_location(location_id, tdb=tdb, branch=branch)
        if err is not None:
            return {"ok": False, "error": err}

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    org = Organization(
        name=name,
        aliases=aliases,
        location=location_id,
        provenance=prov,
    ).to_tdb()

    try:
        iri = await repo.create(org, agent=_AGENT, method="tool_call", branch=branch)
    except Exception as exc:
        return write_error_envelope(exc)

    return ok_envelope(iri=iri)


async def _do_geocode(
    query: str | None,
    location_id: str | None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Geocode a query string or a stored Location by IRI."""
    if query is not None and location_id is not None:
        return error_envelope("provide exactly one of 'query' or 'location_id', not both")
    if query is None and location_id is None:
        return error_envelope("provide exactly one of 'query' or 'location_id'")

    client = GeocodingClient()

    if query is not None:
        try:
            coords = await client.geocode(query)
        except Exception:
            return error_envelope("geocoding failed unexpectedly")

        if coords is None:
            return error_envelope(f"no geocoding result for query: {query}")

        return ok_envelope(coordinates=list(coords))

    # location_id path
    try:
        doc = await tdb.get_document(location_id, branch=branch)
    except Exception as exc:
        return not_found_envelope(location_id, exc, noun="location")

    type_err = type_mismatch_error(location_id, doc, "Location")
    if type_err is not None:
        return error_envelope(type_err)

    # Already has coordinates — no need to geocode
    existing = doc.get("coordinates")
    if existing is not None:
        return ok_envelope(coordinates=list(existing), already_set=True)

    geocode_query = doc.get("address") or doc.get("name", "")
    if not geocode_query:
        return error_envelope("Location has no address and no name to geocode")

    try:
        coords = await client.geocode(geocode_query)
    except Exception:
        return error_envelope("geocoding failed unexpectedly")

    if coords is None:
        return error_envelope(f"no geocoding result for location: {geocode_query}")

    # Persist coordinates
    doc["coordinates"] = list(coords)
    try:
        await tdb.replace_document(doc, branch=branch, message=f"queryd: geocode {location_id}")
    except Exception as exc:
        return error_envelope(f"failed to persist coordinates: {exc}")

    return ok_envelope(coordinates=list(coords))


# ---------------------------------------------------------------------------
# ToolSpec handlers
# ---------------------------------------------------------------------------


async def _handle_lookup(args: LookupArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_lookup(
        args.query,
        args.limit,
        args.kind,
        tdb=ctx.tdb,
        branch=ctx.branch,
    )


async def _handle_get(args: GetArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_get(args.id, tdb=ctx.tdb, branch=ctx.branch)


async def _handle_create_person(args: CreatePersonArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_person(
        args.name,
        args.aliases,
        args.email,
        args.phone,
        args.domicile_id,
        tdb=ctx.tdb,
        branch=ctx.branch,
    )


async def _handle_create_location(args: CreateLocationArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_location(
        args.name,
        args.aliases,
        args.address,
        args.lat,
        args.lon,
        tdb=ctx.tdb,
        branch=ctx.branch,
    )


async def _handle_create_organization(args: CreateOrganizationArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_organization(
        args.name,
        args.aliases,
        args.location_id,
        tdb=ctx.tdb,
        branch=ctx.branch,
    )


async def _handle_geocode(args: GeocodeArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_geocode(
        args.query,
        args.location_id,
        tdb=ctx.tdb,
        branch=ctx.branch,
    )


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class AddressBookToolsPlugin:
    """Queryd ToolSpec plugin for address-book operations."""

    name: str = "address_book_tools"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="address_book", range=">=0.1.0 <0.2.0")]

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="address_book_lookup",
                description="Search address-book entities by name/alias substring (case-insensitive)",
                args_model=LookupArgs,
                handler=_handle_lookup,
            ),
            ToolSpec(
                name="address_book_get",
                description="Fetch a single address-book entity by IRI",
                args_model=GetArgs,
                handler=_handle_get,
            ),
            ToolSpec(
                name="address_book_create_person",
                description="Create a new Person document with optional Contact and domicile",
                args_model=CreatePersonArgs,
                handler=_handle_create_person,
            ),
            ToolSpec(
                name="address_book_create_location",
                description="Create a new Location document with optional address and coordinates",
                args_model=CreateLocationArgs,
                handler=_handle_create_location,
            ),
            ToolSpec(
                name="address_book_create_organization",
                description="Create a new Organization document with optional headquarters Location",
                args_model=CreateOrganizationArgs,
                handler=_handle_create_organization,
            ),
            ToolSpec(
                name="address_book_geocode",
                description="Geocode an address/place name or a stored Location (persists coordinates on success)",
                args_model=GeocodeArgs,
                handler=_handle_geocode,
            ),
        ]


plugin = AddressBookToolsPlugin()
