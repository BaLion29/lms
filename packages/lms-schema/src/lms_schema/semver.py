"""Re-export of semver types from lms-core (canonical location).

This module exists for backward compatibility. New code should import
from ``lms_core.semver`` directly.
"""

from lms_core.semver import Range, RangeError, Version, VersionError  # noqa: F401

__all__ = ["Version", "VersionError", "Range", "RangeError"]
