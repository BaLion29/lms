"""Unit tests for the zero-dependency semver module."""

from __future__ import annotations

import pytest

from lms_schema.semver import Version, VersionError, Range, RangeError


class TestVersion:
    def test_parse_valid(self) -> None:
        v = Version.parse("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_zero_version(self) -> None:
        v = Version.parse("0.0.0")
        assert (v.major, v.minor, v.patch) == (0, 0, 0)

    def test_parse_large(self) -> None:
        v = Version.parse("999.888.777")
        assert str(v) == "999.888.777"

    def test_parse_invalid(self) -> None:
        with pytest.raises(VersionError):
            Version.parse("1.2")
        with pytest.raises(VersionError):
            Version.parse("1.2.3.4")
        with pytest.raises(VersionError):
            Version.parse("v1.2.3")
        with pytest.raises(VersionError):
            Version.parse("abc")
        with pytest.raises(VersionError):
            Version.parse("")

    def test_parse_strips_whitespace(self) -> None:
        v = Version.parse("  1.2.3  ")
        assert str(v) == "1.2.3"

    def test_equality(self) -> None:
        v1 = Version.parse("1.2.3")
        v2 = Version.parse("1.2.3")
        v3 = Version.parse("1.2.4")
        assert v1 == v2
        assert v1 != v3

    def test_ordering(self) -> None:
        # major
        assert Version.parse("1.0.0") < Version.parse("2.0.0")
        assert Version.parse("2.0.0") > Version.parse("1.0.0")
        # minor
        assert Version.parse("1.1.0") < Version.parse("1.2.0")
        # patch
        assert Version.parse("1.1.1") < Version.parse("1.1.2")
        # equal
        assert Version.parse("1.0.0") <= Version.parse("1.0.0")
        assert Version.parse("1.0.0") >= Version.parse("1.0.0")

    def test_str_repr(self) -> None:
        v = Version.parse("3.2.1")
        assert str(v) == "3.2.1"
        assert "3.2.1" in repr(v)

    def test_hashable(self) -> None:
        s = {Version.parse("1.0.0"), Version.parse("1.0.0"), Version.parse("2.0.0")}
        assert len(s) == 2


class TestRange:
    def test_bare_version_equals(self) -> None:
        r = Range("1.0.0")
        assert r.contains(Version.parse("1.0.0"))
        assert not r.contains(Version.parse("1.0.1"))
        assert not r.contains(Version.parse("0.9.9"))

    def test_gte(self) -> None:
        r = Range(">=1.0.0")
        assert r.contains(Version.parse("1.0.0"))
        assert r.contains(Version.parse("1.0.1"))
        assert r.contains(Version.parse("2.0.0"))
        assert not r.contains(Version.parse("0.9.9"))

    def test_gt(self) -> None:
        r = Range(">1.0.0")
        assert not r.contains(Version.parse("1.0.0"))
        assert r.contains(Version.parse("1.0.1"))
        assert r.contains(Version.parse("2.0.0"))

    def test_lte(self) -> None:
        r = Range("<=1.0.0")
        assert r.contains(Version.parse("1.0.0"))
        assert r.contains(Version.parse("0.9.9"))
        assert not r.contains(Version.parse("1.0.1"))

    def test_lt(self) -> None:
        r = Range("<1.0.0")
        assert r.contains(Version.parse("0.9.9"))
        assert not r.contains(Version.parse("1.0.0"))

    def test_explicit_eq(self) -> None:
        r = Range("==1.0.0")
        assert r.contains(Version.parse("1.0.0"))
        assert not r.contains(Version.parse("1.0.1"))

    def test_range_combination_all_must_satisfy(self) -> None:
        r = Range(">=1.0.0 <2.0.0")
        assert r.contains(Version.parse("1.0.0"))
        assert r.contains(Version.parse("1.5.0"))
        assert r.contains(Version.parse("1.999.999"))
        assert not r.contains(Version.parse("0.9.0"))
        assert not r.contains(Version.parse("2.0.0"))
        assert not r.contains(Version.parse("2.0.1"))

    def test_unsupported_operator_raises(self) -> None:
        with pytest.raises(RangeError):
            Range("!=1.0.0")

    def test_invalid_range_raises(self) -> None:
        with pytest.raises(RangeError):
            Range(">=1.0.0 <")
        with pytest.raises(RangeError):
            Range("~1.0.0")  # tilde not supported
        with pytest.raises(RangeError):
            Range("^1.0.0")  # caret not supported
        with pytest.raises(RangeError):
            Range("1.0")  # incomplete version
