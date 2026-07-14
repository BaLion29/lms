"""Template rendering helpers for action executors.

Uses ONLY ``string.Template`` for variable substitution — no Jinja, no eval,
no attribute traversal.  Variables are passed as a flat dict so executors
never introspect document internals.

This module lives in firnline_core so that extension executors (M4/M5)
can reuse it without importing effectd internals.
"""

from __future__ import annotations

import string
from typing import Any


def render(
    template: str | None,
    *,
    firing: dict[str, Any],
    subject: dict[str, Any] | None,
    action: dict[str, Any],
    idempotency_key: str,
) -> str | None:
    """Substitute ``$var`` placeholders in *template* using ``string.Template.safe_substitute``.

    Variables supplied:
        firing_id, firing_status, scheduled_for, trigger_name,
        subject_label, subject_id, action_name, idempotency_key.

    ``subject_label`` resolves via fallback chain:
        1. ``subject["name"]``
        2. ``subject["title"]``
        3. ``subject["@type"]``
        4. ``subject["@id"]``
    (Schema ``label_field`` resolution is not attempted against TDB metadata;
    this fallback chain mirrors the gotify title logic.)

    Unknown ``$vars`` are left intact (safe_substitute behaviour).
    Returns ``None`` when *template* is ``None``.
    """
    if template is None:
        return None

    subject_label = _subject_label(subject)
    subject_id = subject["@id"] if (subject and subject.get("@id")) else ""

    variables: dict[str, str] = {
        "firing_id": firing.get("@id", ""),
        "firing_status": firing.get("status", ""),
        "scheduled_for": firing.get("scheduled_for", ""),
        "trigger_name": _trigger_name(firing),
        "subject_label": subject_label,
        "subject_id": subject_id,
        "action_name": action.get("name", ""),
        "idempotency_key": idempotency_key,
    }

    return string.Template(template).safe_substitute(variables)


def default_webhook_payload(
    firing: dict[str, Any],
    subject: dict[str, Any] | None,
    action: dict[str, Any],
    idempotency_key: str,
    scheduled_for: str,
) -> dict[str, Any]:
    """Canonical JSON body used when ``payload_template`` is absent.

    Produces::

        {
            "firing": { ... (full firing doc) ... },
            "subject": { ... (full subject doc, or null) ... },
            "action_name": "...",
            "idempotency_key": "...",
            "scheduled_for": "..."
        }
    """
    return {
        "firing": firing,
        "subject": subject,
        "action_name": action.get("name", ""),
        "idempotency_key": idempotency_key,
        "scheduled_for": scheduled_for,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subject_label(subject: dict[str, Any] | None) -> str:
    """Fallback chain: name → title → @type → @id."""
    if subject is None:
        return ""
    for key in ("name", "title", "@type", "@id"):
        val = subject.get(key)
        if val:
            return str(val)
    return ""


def _trigger_name(firing: dict[str, Any]) -> str:
    """Best-effort trigger name: last segment of the trigger IRI."""
    trigger_iri = firing.get("trigger", "")
    if "/" in trigger_iri:
        return trigger_iri.rsplit("/", 1)[-1]
    return trigger_iri
