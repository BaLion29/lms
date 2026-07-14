"""Stable public facade — re-exports generated models and base utilities.

This module is hand-maintained.  Kernel-only: core base types, generated
kernel models (core, triggers, capture), and trigger/capture enums.
Extension domain models live in their respective extension packages.
"""

# flake8: noqa: F401

# Base utilities
from firnline_core.base import TdbDateTime, TdbDocument, _format_datetime

# Core generated models
from firnline_core.generated.core import ExternalRef, Provenance, SchemaMigration, SchemaModule, Tag

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

# Capture generated models
from firnline_core.generated.capture import (
    Captured,
    CapturedStatus,
)

# Actions generated models
from firnline_core.generated.actions import (
    ActionExecution,
    ActionMode,
    ExecutionStatus,
    NotifyAction,
    WebhookAction,
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
    "Tag",
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
    # capture
    "Captured",
    "CapturedStatus",
    # actions
    "ActionExecution",
    "ActionMode",
    "ExecutionStatus",
    "NotifyAction",
    "WebhookAction",
]
