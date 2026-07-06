"""Re-export of semver types from firnline-core (canonical location).

This module exists for backward compatibility. New code should import
from ``firnline_core.semver`` directly.
"""

from firnline_core.semver import Range, RangeError, Version, VersionError  # noqa: F401

__all__ = ["Version", "VersionError", "Range", "RangeError"]
