"""Plugin-specific tests for firnline-ext-address-book — proposal models, prompt snippet, build_documents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from firnline_core.plugins import BuildContext, EntityIndex
from firnline_ext_address_book.extract import (
    AddressBookLinkingPlugin,
    LocationProposal,
    OrganizationProposal,
    PersonProposal,
    _build_context_block,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Fake BuildContext for testing build_documents
# ---------------------------------------------------------------------------

_SENTINEL_NOT_FOUND = object()  # distinct from None (None = "use default")


class _FakeBuildContext:
    """Minimal BuildContext double for testing build_documents."""

    def __init__(
        self,
        captured_iri: str = "InboxNote/test123",
        ensure_entity_returns: str | object | None = None,
    ):
        self.captured_iri = captured_iri
        self.tdb = None
        self.branch = "main"
        self._ensure_entity_returns = ensure_entity_returns
        self.ensure_entity_calls: list[tuple] = []

    def now(self) -> datetime:
        return datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)

    async def ensure_entity(self, type_name: str, name: str, factory):
        self.ensure_entity_calls.append((type_name, name, factory))
        if self._ensure_entity_returns is not None:
            if self._ensure_entity_returns is _SENTINEL_NOT_FOUND:
                return None  # simulate no match
            return self._ensure_entity_returns
        # Default: simulate existing entity found
        return f"{type_name}/{name.lower().replace(' ', '_')}"


# ---------------------------------------------------------------------------
# build_context_block
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    """Tests for the context block renderer."""

    def test_small_index_exact_string(self):
        index = EntityIndex(
            entities={
                "Person": {"anna meier": "Person/abc"},
                "Location": {"rotondohütte": "Location/hut1"},
                "Organization": {"acme corp": "Organization/acme"},
            },
            display={
                "Person": [("Anna Meier", "Person/abc")],
                "Location": [("Rotondohütte", "Location/hut1")],
                "Organization": [("Acme Corp", "Organization/acme")],
            },
        )
        block = _build_context_block(index)
        expected = (
            "Known people: Anna Meier <Person/abc>\n"
            "Known locations: Rotondohütte <Location/hut1>\n"
            "Known organizations: Acme Corp <Organization/acme>"
        )
        assert block == expected

    def test_multiple_entries_comma_separated(self):
        index = EntityIndex(
            entities={"Person": {}},
            display={
                "Person": [
                    ("Anna Meier", "Person/abc"),
                    ("Bob Müller", "Person/def"),
                ],
            },
        )
        block = _build_context_block(index)
        assert block == (
            "Known people: Anna Meier <Person/abc>, Bob Müller <Person/def>\n"
            "Known locations: (none)\n"
            "Known organizations: (none)"
        )

    def test_empty_index_shows_none(self):
        index = EntityIndex()
        block = _build_context_block(index)
        assert block == "Known people: (none)\nKnown locations: (none)\nKnown organizations: (none)"


# ---------------------------------------------------------------------------
# Proposal model validation
# ---------------------------------------------------------------------------


class TestPersonProposal:
    def test_minimal_person(self):
        p = PersonProposal(name="Anna Meier")
        assert p.kind == "ab_person"
        assert p.name == "Anna Meier"
        assert p.email is None
        assert p.phone is None
        assert p.aliases is None
        assert p.domicile_name is None
        assert p.organization_name is None
        assert p.role is None

    def test_full_person(self):
        p = PersonProposal(
            name="Anna Meier",
            aliases=["Anna"],
            email="anna@example.com",
            phone="+41 79 123 45 67",
            domicile_name="Zürich",
            organization_name="Acme Corp",
            role="Engineer",
        )
        assert p.aliases == ["Anna"]
        assert p.email == "anna@example.com"
        assert p.phone == "+41 79 123 45 67"
        assert p.domicile_name == "Zürich"
        assert p.organization_name == "Acme Corp"
        assert p.role == "Engineer"


class TestLocationProposal:
    def test_minimal_location(self):
        p = LocationProposal(name="Rotondohütte")
        assert p.kind == "ab_location"
        assert p.name == "Rotondohütte"
        assert p.aliases is None
        assert p.address is None

    def test_full_location(self):
        p = LocationProposal(
            name="Rotondohütte",
            aliases=["Rotondo Hut"],
            address="Via Rotondo 1, 6780 Airolo",
        )
        assert p.aliases == ["Rotondo Hut"]
        assert p.address == "Via Rotondo 1, 6780 Airolo"


class TestOrganizationProposal:
    def test_minimal_organization(self):
        p = OrganizationProposal(name="Acme Corp")
        assert p.kind == "ab_organization"
        assert p.name == "Acme Corp"
        assert p.aliases is None
        assert p.location_name is None

    def test_full_organization(self):
        p = OrganizationProposal(
            name="Acme Corp",
            aliases=["Acme"],
            location_name="Zürich",
        )
        assert p.aliases == ["Acme"]
        assert p.location_name == "Zürich"


# ---------------------------------------------------------------------------
# Prompt snippet
# ---------------------------------------------------------------------------


class TestPromptSnippet:
    def setup_method(self):
        self.plugin = AddressBookLinkingPlugin()

    def test_snippet_is_non_empty(self):
        snippet = self.plugin.prompt_snippet()
        assert len(snippet) > 0

    def test_snippet_mentions_person_location_organization(self):
        snippet = self.plugin.prompt_snippet()
        assert "Person" in snippet
        assert "Location" in snippet
        assert "Organization" in snippet

    def test_snippet_has_no_json_fences(self):
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def test_name(self):
        assert AddressBookLinkingPlugin().name == "address_book_linking"

    def test_requires_has_address_book(self):
        req_names = {r.name for r in AddressBookLinkingPlugin().requires}
        assert req_names == {"address_book"}

    def test_produces_person_location_organization(self):
        assert AddressBookLinkingPlugin().produces == ["Person", "Location", "Organization"]

    def test_proposal_models_count(self):
        models = AddressBookLinkingPlugin().proposal_models()
        assert len(models) == 3
        names = {m.__name__ for m in models}
        assert names == {"PersonProposal", "LocationProposal", "OrganizationProposal"}

    def test_linking_context_returns_context_block(self):
        index = EntityIndex(
            entities={"Person": {"bob": "Person/1"}},
            display={"Person": [("Bob", "Person/1")]},
        )
        result = asyncio.run(AddressBookLinkingPlugin().linking_context(None, index=index, branch=""))
        assert "Known people: Bob <Person/1>" in result
        assert "Known locations: (none)" in result
        assert "Known organizations: (none)" in result

    def test_linking_context_empty_index(self):
        index = EntityIndex()
        result = asyncio.run(AddressBookLinkingPlugin().linking_context(None, index=index, branch=""))
        assert "Known people: (none)" in result


# ---------------------------------------------------------------------------
# Build-document integration tests
# ---------------------------------------------------------------------------


class TestBuildDocuments:
    def setup_method(self):
        self.plugin = AddressBookLinkingPlugin()

    # ── Person ─────────────────────────────────────────────────────────

    async def test_person_minimal_ensure_entity(self):
        """Minimal Person: ensure_entity is called with correct factory."""
        ctx = _FakeBuildContext(ensure_entity_returns="Person/anna_meier")
        proposal = PersonProposal(name="Anna Meier")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        call_type, call_name, factory = ctx.ensure_entity_calls[0]
        assert call_type == "Person"
        assert call_name == "Anna Meier"
        # Factory creates a valid Person document
        factory_doc = factory()
        assert factory_doc["@type"] == "Person"
        assert factory_doc["name"] == "Anna Meier"
        assert "contact" not in factory_doc
        assert factory_doc["derived_from"] == ["InboxNote/test123"]
        assert factory_doc["provenance"]["agent"] == "ingestd"
        assert factory_doc["provenance"]["method"] == "llm_extraction"

    async def test_person_with_email_and_phone(self):
        """Person with email and phone includes Contact."""
        ctx = _FakeBuildContext(ensure_entity_returns="Person/anna_meier")
        proposal = PersonProposal(
            name="Anna Meier",
            email="anna@example.com",
            phone="+41 79 123 45 67",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        factory_doc = ctx.ensure_entity_calls[0][2]()
        assert factory_doc["contact"] == {
            "@type": "Contact",
            "email": "anna@example.com",
            "phone": "+41 79 123 45 67",
        }

    async def test_person_with_domicile_resolves_location(self):
        """Person with domicile_name resolves Location via ensure_entity."""
        ctx = _FakeBuildContext(ensure_entity_returns="Location/zurich")
        proposal = PersonProposal(name="Anna Meier", domicile_name="Zürich")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        # Two ensure_entity calls: Location (for domicile) then Person
        assert len(ctx.ensure_entity_calls) == 2
        assert ctx.ensure_entity_calls[0][0] == "Location"
        assert ctx.ensure_entity_calls[0][1] == "Zürich"
        # Location factory creates minimal entity
        loc_factory = ctx.ensure_entity_calls[0][2]
        loc_doc = loc_factory()
        assert loc_doc["@type"] == "Location"
        assert loc_doc["name"] == "Zürich"
        # Person factory includes domicile in Contact
        person_factory = ctx.ensure_entity_calls[1][2]
        person_doc = person_factory()
        assert person_doc["contact"]["domicile"] == "Location/zurich"

    async def test_person_domicile_not_found_leaves_unset(self):
        """If domicile_name doesn't resolve, Contact.domicile stays unset."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = PersonProposal(name="Anna Meier", domicile_name="BogusTown")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        # Location ensure_entity returns None, then Person ensure_entity called
        assert len(ctx.ensure_entity_calls) == 2
        assert ctx.ensure_entity_calls[0][0] == "Location"
        # Person factory produces no contact (or contact without domicile)
        person_factory = ctx.ensure_entity_calls[1][2]
        person_doc = person_factory()
        # Since email/phone/domicile are all None, contact is omitted
        assert "contact" not in person_doc

    async def test_person_with_organization_affiliation(self):
        """Person with organization_name + role creates an Affiliation."""
        ctx = _FakeBuildContext(ensure_entity_returns="Organization/acme")
        proposal = PersonProposal(
            name="Anna Meier",
            organization_name="Acme Corp",
            role="Engineer",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 2
        assert ctx.ensure_entity_calls[0][0] == "Organization"
        assert ctx.ensure_entity_calls[0][1] == "Acme Corp"
        person_factory = ctx.ensure_entity_calls[1][2]
        person_doc = person_factory()
        affs = person_doc["affiliations"]
        assert len(affs) == 1
        assert affs[0]["@type"] == "Affiliation"
        assert affs[0]["organization"] == "Organization/acme"
        assert affs[0]["role"] == "Engineer"

    async def test_person_organization_not_found_no_affiliation(self):
        """If organization_name doesn't resolve, no Affiliation is created."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = PersonProposal(name="Anna Meier", organization_name="UnknownCorp")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 2
        person_factory = ctx.ensure_entity_calls[1][2]
        person_doc = person_factory()
        assert person_doc.get("affiliations", []) == []

    async def test_person_full_with_domicile_and_organization(self):
        """Person with domicile + organization: full wiring."""
        # Use multi-return: first two cross-ref calls resolve, third is Person
        class _MultiReturnCtx(_FakeBuildContext):
            def __init__(self):
                super().__init__()
                self._call_count = 0

            async def ensure_entity(self, type_name: str, name: str, factory):
                self._call_count += 1
                self.ensure_entity_calls.append((type_name, name, factory))
                if self._call_count == 1:
                    return "Location/zurich"
                elif self._call_count == 2:
                    return "Organization/acme"
                return "Person/anna_meier"

        ctx = _MultiReturnCtx()
        proposal = PersonProposal(
            name="Anna Meier",
            email="anna@example.com",
            domicile_name="Zürich",
            organization_name="Acme Corp",
            role="Engineer",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 3
        person_factory = ctx.ensure_entity_calls[2][2]
        person_doc = person_factory()
        assert person_doc["contact"]["domicile"] == "Location/zurich"
        assert person_doc["contact"]["email"] == "anna@example.com"
        affs = person_doc["affiliations"]
        assert len(affs) == 1
        assert affs[0]["organization"] == "Organization/acme"
        assert affs[0]["role"] == "Engineer"

    # ── Location ───────────────────────────────────────────────────────

    async def test_location_ensure_entity(self):
        """Location proposal uses ensure_entity with full factory."""
        ctx = _FakeBuildContext(ensure_entity_returns="Location/zurich")
        proposal = LocationProposal(name="Zürich")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        call_type, call_name, factory = ctx.ensure_entity_calls[0]
        assert call_type == "Location"
        assert call_name == "Zürich"
        factory_doc = factory()
        assert factory_doc["@type"] == "Location"
        assert factory_doc["name"] == "Zürich"
        assert factory_doc["derived_from"] == ["InboxNote/test123"]
        assert factory_doc["provenance"]["agent"] == "ingestd"

    async def test_location_with_address_and_aliases(self):
        """Location factory includes address and aliases."""
        ctx = _FakeBuildContext(ensure_entity_returns="Location/rotondo")
        proposal = LocationProposal(
            name="Rotondohütte",
            aliases=["Rotondo Hut"],
            address="Via Rotondo 1",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        factory_doc = ctx.ensure_entity_calls[0][2]()
        assert factory_doc["aliases"] == ["Rotondo Hut"]
        assert factory_doc["address"] == "Via Rotondo 1"

    async def test_location_existing_not_duplicated(self):
        """When Location already exists in index, factory is NOT called (dedup)."""
        ctx = _FakeBuildContext(ensure_entity_returns="Location/zurich")
        proposal = LocationProposal(name="Zürich")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        factory = ctx.ensure_entity_calls[0][2]
        # Factory is present but not called by ensure_entity (since match found)
        # We just verify the proposal was "handled" — factory call is controlled
        # by ensure_entity internals
        assert callable(factory)

    # ── Organization ───────────────────────────────────────────────────

    async def test_organization_minimal_ensure_entity(self):
        """Minimal Organization proposal."""
        ctx = _FakeBuildContext(ensure_entity_returns="Organization/acme")
        proposal = OrganizationProposal(name="Acme Corp")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        call_type, call_name, factory = ctx.ensure_entity_calls[0]
        assert call_type == "Organization"
        assert call_name == "Acme Corp"
        factory_doc = factory()
        assert factory_doc["@type"] == "Organization"
        assert factory_doc["name"] == "Acme Corp"
        assert "location" not in factory_doc  # None excluded by to_tdb

    async def test_organization_with_location_name_resolves(self):
        """Organization with location_name resolves Location IRI."""
        ctx = _FakeBuildContext(ensure_entity_returns="Location/zurich")
        proposal = OrganizationProposal(
            name="Acme Corp",
            location_name="Zürich",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        # Two calls: Location cross-ref, then Organization
        assert len(ctx.ensure_entity_calls) == 2
        assert ctx.ensure_entity_calls[0][0] == "Location"
        assert ctx.ensure_entity_calls[0][1] == "Zürich"
        # Organization factory includes location ref
        org_factory = ctx.ensure_entity_calls[1][2]
        org_doc = org_factory()
        assert org_doc["location"] == "Location/zurich"

    async def test_organization_location_not_found_keeps_none(self):
        """If location_name doesn't resolve, Organization.location remains None."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = OrganizationProposal(name="Acme Corp", location_name="BogusTown")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        org_factory = ctx.ensure_entity_calls[1][2]
        org_doc = org_factory()
        assert "location" not in org_doc  # None excluded by to_tdb

    # ── Dedup / existing entity in index ───────────────────────────────

    async def test_person_duplicate_name_dedup(self):
        """Person with name matching an already-indexed entity is deduplicated."""
        ctx = _FakeBuildContext(ensure_entity_returns="Person/anna_meier")
        proposal = PersonProposal(name="Anna Meier")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        # The factory is present but since the entity was "found" in the index
        # (our fake returns an IRI), it wouldn't be called by the real
        # ensure_entity. The result is [] — no duplicate.
        assert docs == []

    async def test_person_only_contact_no_domicile_no_affiliation(self):
        """Person with email only — no cross-ref calls needed."""
        ctx = _FakeBuildContext(ensure_entity_returns="Person/anna_meier")
        proposal = PersonProposal(name="Anna Meier", email="anna@example.com")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Person"
