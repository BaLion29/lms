"""IndexerPlugin for Person, Location, and Organization documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class AddressBookIndexerPlugin(IndexerPlugin):
    """Indexer for address-book entities: Person, Location, Organization."""

    name: str = "address_book_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="address_book", range=">=0.2.0 <0.3.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Person", "Location", "Organization"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        type_ = doc.get("@type", "")
        name = doc.get("name", "")

        if type_ == "Person":
            parts = [name]
            contact = doc.get("contact")
            if isinstance(contact, dict):
                phone = contact.get("phone")
                email = contact.get("email")
                if phone:
                    parts.append(phone)
                if email:
                    parts.append(email)
            return " — ".join(parts)

        if type_ == "Location":
            parts = [name]
            address = doc.get("address")
            if address:
                parts.append(address)
            return " — ".join(parts)

        # Organization
        parts = [name]
        location = doc.get("location")
        if isinstance(location, dict) and location.get("name"):
            parts.append(location["name"])
        return " — ".join(parts)

    def entity_name(self, doc: dict[str, Any]) -> str:
        return str(doc.get("name", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        aliases: list[str] = []
        name = doc.get("name", "")
        if name:
            aliases.append(name)
        for alias in doc.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip():
                aliases.append(alias.strip())
        return aliases


plugin = AddressBookIndexerPlugin()
