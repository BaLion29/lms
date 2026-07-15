"""Extraction plugin for Person, Location, and Organization proposals.

Part of the firnline-ext-address-book reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from pydantic import BaseModel

from firnline_core.models import Provenance
from firnline_core.plugins import BuildContext, EntityIndex, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_address_book.models import Affiliation, Contact, Location, Organization, Person

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Proposal models
# ---------------------------------------------------------------------------


class PersonProposal(BaseModel):
    """LLM proposes a Person when the text identifies an individual."""

    kind: Literal["ab_person"] = "ab_person"
    name: str
    aliases: list[str] | None = None
    email: str | None = None
    phone: str | None = None
    domicile_name: str | None = None  # name of a Location for Contact.domicile
    organization_name: str | None = None  # name of an Organization for Affiliation
    role: str | None = None  # role at the organization


class LocationProposal(BaseModel):
    """LLM proposes a Location when the text identifies a named place."""

    kind: Literal["ab_location"] = "ab_location"
    name: str
    aliases: list[str] | None = None
    address: str | None = None


class OrganizationProposal(BaseModel):
    """LLM proposes an Organization when the text identifies a named group or company."""

    kind: Literal["ab_organization"] = "ab_organization"
    name: str
    aliases: list[str] | None = None
    location_name: str | None = None  # name of a Location for Organization.location


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class AddressBookLinkingPlugin(ExtractorPlugin):
    """Extractor for Person, Location, and Organization entities."""

    name: str = "address_book_linking"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="address_book", range=">=0.2.0 <0.3.0"),
    ]
    produces: list[str] = ["Person", "Location", "Organization"]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [PersonProposal, LocationProposal, OrganizationProposal]

    def prompt_snippet(self) -> str:
        """Instruction text for the extraction agent.

        The kernel owns the JSON schema fence; this is guidance only.
        """
        return (
            "When the text mentions a person by name (e.g. 'Anna Meier', 'Dr. Schmidt'), "
            "propose a Person with name, and optionally email, phone, "
            "aliases, domicile_name (a location name for the person's home), and "
            "organization_name + role (for an affiliation).  "
            "When the text describes a named place (e.g. 'Rotondohütte', 'Office Zürich'), "
            "propose a Location with name, and optionally aliases or address.  "
            "When the text identifies a named group, company, or institution "
            "(e.g. 'Acme Corp', 'ETH Zürich'), propose an Organization with name, "
            "and optionally aliases or location_name (a location name for the org's site).  "
            "Only propose entities that are clearly identifiable in the text — "
            "do not invent people, places, or organisations that are not mentioned.  "
            "Prefer referencing existing known entities (see the linking context for "
            "already-known people, locations, and organizations) rather than proposing "
            "duplicates.  Use the EXACT names as listed in the linking context when the "
            "text refers to an existing entity."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Render the Person/Location/Organization context block."""
        return _build_context_block(index)

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        # ── helper: resolve a name to a context IRI ──────────────────
        async def _resolve_context(type_name: str, name: str | None, allow_create: bool = False) -> str | None:
            """Look up *name* as an existing *type_name* entity.

            When *allow_create* is True, a minimal entity is created if not found.
            Otherwise, returns the IRI if found, ``None`` otherwise.
            """
            if not name:
                return None
            if allow_create:
                return await ctx.ensure_entity(
                    type_name,
                    name,
                    lambda: _make_minimal_entity(type_name, name, now, source_iri, confidence),
                )
            return await ctx.ensure_entity(type_name, name, lambda: None)

        # ── Person ────────────────────────────────────────────────────
        if isinstance(proposal, PersonProposal):
            # Resolve cross-refs
            domicile_iri = await _resolve_context("Location", proposal.domicile_name, allow_create=True)
            org_iri = await _resolve_context("Organization", proposal.organization_name, allow_create=True)

            # Build Contact
            contact_fields: dict[str, Any] = {}
            if proposal.email is not None:
                contact_fields["email"] = proposal.email
            if proposal.phone is not None:
                contact_fields["phone"] = proposal.phone
            if domicile_iri is not None:
                contact_fields["domicile"] = domicile_iri

            contact = Contact(**contact_fields) if contact_fields else None

            # Build affiliations
            affiliations: list[Affiliation] = []
            if org_iri is not None:
                aff = Affiliation(organization=org_iri)
                if proposal.role is not None:
                    aff.role = proposal.role
                affiliations.append(aff)

            person_iri = await ctx.ensure_entity(
                "Person",
                proposal.name,
                lambda: Person(
                    name=proposal.name,
                    aliases=proposal.aliases or [],
                    contact=contact,
                    affiliations=affiliations,
                    created_at=now,
                    updated_at=now,
                    derived_from=[source_iri],
                    provenance=Provenance(
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                ).to_tdb(),
            )
            if person_iri:
                logger.info("person_linked", name=proposal.name, iri=person_iri)
            return []

        # ── Location ───────────────────────────────────────────────────
        if isinstance(proposal, LocationProposal):
            loc_iri = await ctx.ensure_entity(
                "Location",
                proposal.name,
                lambda: Location(
                    name=proposal.name,
                    aliases=proposal.aliases or [],
                    address=proposal.address,
                    created_at=now,
                    updated_at=now,
                    derived_from=[source_iri],
                    provenance=Provenance(
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                ).to_tdb(),
            )
            if loc_iri:
                logger.info("location_linked", name=proposal.name, iri=loc_iri)
            return []

        # ── Organization ───────────────────────────────────────────────
        if isinstance(proposal, OrganizationProposal):
            loc_iri = await _resolve_context("Location", proposal.location_name, allow_create=True)

            org_iri = await ctx.ensure_entity(
                "Organization",
                proposal.name,
                lambda: Organization(
                    name=proposal.name,
                    aliases=proposal.aliases or [],
                    location=loc_iri,
                    created_at=now,
                    updated_at=now,
                    derived_from=[source_iri],
                    provenance=Provenance(
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                ).to_tdb(),
            )
            if org_iri:
                logger.info("organization_linked", name=proposal.name, iri=org_iri)
            return []

        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_entity(
    type_name: str,
    name: str,
    now: Any,
    source_iri: str,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Factory for a minimal cross-reference entity (Location or Organization)."""
    base = {
        "@type": type_name,
        "name": name,
        "aliases": [],
        "created_at": now,
        "updated_at": now,
        "derived_from": [source_iri],
        "provenance": {
            "@type": "Provenance",
            "agent": "ingestd",
            "at": now,
            "method": "llm_extraction",
        },
    }
    if confidence is not None:
        base["provenance"]["confidence"] = confidence
    return base


def _build_context_block(index: EntityIndex) -> str:
    """Render a compact prompt context block listing known people, locations, and organizations."""

    def _section(label: str, entries: list[tuple[str, str]]) -> str:
        if not entries:
            return f"Known {label}: (none)"
        items = ", ".join(f"{name} <{iri}>" for name, iri in entries)
        return f"Known {label}: {items}"

    return (
        _section("people", index.names("Person"))
        + "\n"
        + _section("locations", index.names("Location"))
        + "\n"
        + _section("organizations", index.names("Organization"))
    )


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = AddressBookLinkingPlugin()
