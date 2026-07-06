"""Minimal zero-dependency semver: Version parsing, ordering, and Range comparison.

Used by the composer for dependency-range checks and will be reused
for runtime plugin-requirement verification.
"""

from __future__ import annotations

import re
from functools import total_ordering


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_COMPARATOR_RE = re.compile(r"^(>=|>|<=|<|==)?(\d+\.\d+\.\d+)$")


class VersionError(Exception):
    """Raised when a version string cannot be parsed."""


class RangeError(Exception):
    """Raised when a range specifier string cannot be parsed."""


@total_ordering
class Version:
    """A semver 3-component version (X.Y.Z)."""

    __slots__ = ("major", "minor", "patch")

    def __init__(self, major: int, minor: int, patch: int) -> None:
        self.major = major
        self.minor = minor
        self.patch = patch

    @classmethod
    def parse(cls, s: str) -> "Version":
        """Parse a "X.Y.Z" string into a Version."""
        m = _VERSION_RE.fullmatch(s.strip())
        if not m:
            raise VersionError(f"Invalid version string: {s!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __lt__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        return f"Version({self})"


class Range:
    """A semver range: space-separated comparators.

    Each comparator is one of ``>=``, ``>``, ``<=``, ``<``, ``==``, or
    a bare version (treated as ``==``). All comparators must be satisfied
    for ``contains`` to return True.
    """

    def __init__(self, spec: str) -> None:
        self.parts: list[tuple[str, Version]] = []
        for part in spec.strip().split():
            if not part:
                continue
            m = _COMPARATOR_RE.fullmatch(part)
            if not m:
                raise RangeError(f"Invalid range spec: {spec!r}")
            op: str = m.group(1) or "=="
            v = Version.parse(m.group(2))
            self.parts.append((op, v))

    def contains(self, version: Version) -> bool:
        """Return True if *version* satisfies all comparators in this range."""
        return all(self._check(op, constraint, version) for op, constraint in self.parts)

    @staticmethod
    def _check(op: str, constraint: Version, version: Version) -> bool:
        if op == ">=":
            return version >= constraint
        if op == ">":
            return version > constraint
        if op == "<=":
            return version <= constraint
        if op == "<":
            return version < constraint
        if op == "==":
            return version == constraint
        return False

    def __repr__(self) -> str:
        return f"Range({self.parts!r})"
