"""Stable public facade — re-exports generated models and base utilities.

This module is hand-maintained.  Kernel-only: core base types, generated
kernel models (core, triggers, inbox), and trigger-related enums.
Extension domain models (Task, Person, Location, Event, Reminder, etc.)
live in their respective extension packages.
"""

# flake8: noqa: F401

# Base utilities
from firnline_core.base import TdbDateTime, TdbDocument, _format_datetime

# Core generated models
from firnline_core.generated.core import ExternalRef, Provenance, SchemaMigration, SchemaModule

# Trigger generated models (concrete triggers + enums + TriggerFiring)
from firnline_core.generated.triggers import (
    CompositeMode,
    CompositeTrigger,
    EventKind,
    EventTrigger,
    FiringStatus,
    OneShotTrigger,
    RelativeTrigger,
    ScheduleTrigger,
    TriggerFiring,
)

# Inbox generated models
from firnline_core.generated.inbox import (
    InboxAudio,
    InboxAudioStatus,
    InboxNote,
    InboxNoteStatus,
)

__all__ = [
    # base
    "TdbDateTime",
    "TdbDocument",
    "_format_datetime",
    # core
    "ExternalRef",
    "Provenance",
    "SchemaMigration",
    "SchemaModule",
    # triggers
    "CompositeMode",
    "CompositeTrigger",
    "EventKind",
    "EventTrigger",
    "FiringStatus",
    "OneShotTrigger",
    "RelativeTrigger",
    "ScheduleTrigger",
    "TriggerFiring",
    # inbox
    "InboxAudio",
    "InboxAudioStatus",
    "InboxNote",
    "InboxNoteStatus",
]
