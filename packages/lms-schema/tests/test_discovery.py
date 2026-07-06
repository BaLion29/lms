"""Tests for entry-point schema module discovery and composition integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lms_schema.composer import (
    ComposerError,
    L2Error,
    compose,
)
from lms_schema.discovery import (
    DiscoveryError,
    ModuleSource,
    discover_module_dirs,
)
from lms_schema import SchemaError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module(
    base: Path,
    name: str,
    version: str = "1.0.0",
    depends_on: list[dict[str, str]] | None = None,
    exports: list[str] | None = None,
    description: str = "Test module",
    classes: list[dict] | None = None,
    context: dict | None = None,
) -> Path:
    """Create a minimal schema module directory tree under *base*."""
    mod_dir = base / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "depends_on": depends_on if depends_on is not None else [],
        "exports": exports if exports is not None else [],
        "description": description,
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    if classes is not None:
        (mod_dir / "schema.json").write_text(json.dumps(classes))
    if context is not None:
        (mod_dir / "context.json").write_text(json.dumps(context))
    return mod_dir


def _core_context() -> dict:
    return {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}


def _core_classes() -> list[dict]:
    return [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {"@abstract": [], "@id": "Context", "@type": "Class"},
    ]


def _make_core(base: Path, version: str = "1.0.0") -> Path:
    return _make_module(
        base,
        "core",
        version=version,
        exports=["Source", "Context"],
        classes=_core_classes(),
        context=_core_context(),
    )


# Fake entry point matching importlib.metadata.EntryPoint protocol
class FakeEntryPoint:
    """Minimal fake matching the importlib.metadata.EntryPoint protocol."""

    def __init__(
        self,
        name: str,
        load_fn,
        *,
        dist_name: str | None = None,
        dist_version: str | None = None,
    ) -> None:
        self.name = name
        self._load_fn = load_fn
        self._dist_name = dist_name
        self._dist_version = dist_version
        # Provide a .dist attribute (None or a fake)
        self.dist = None
        if dist_name is not None:
            self.dist = _FakeDist(dist_name, dist_version)

    def load(self):
        return self._load_fn()


class _FakeDist:
    """Minimal fake distribution for ep.dist."""

    def __init__(self, name: str, version: str | None) -> None:
        self.name = name
        self.version = version


# ---------------------------------------------------------------------------
# discover_module_dirs tests
# ---------------------------------------------------------------------------


class TestDiscoverModuleDirs:
    """Unit tests for discover_module_dirs via monkeypatching entry_points."""

    def test_successful_discovery(self, tmp_path: Path) -> None:
        """A valid entry point produces a ModuleSource with pkg: origin."""
        mod_dir = _make_module(
            tmp_path, "ext1",
            version="2.0.0",
            exports=["Z"],
            classes=[{"@id": "Z", "@type": "Class"}],
        )
        eps = [
            FakeEntryPoint(
                "ext1",
                lambda md=mod_dir: md,
                dist_name="lms-ext-test",
                dist_version="2.0.0",
            ),
        ]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            result = discover_module_dirs()
        assert "ext1" in result
        ms = result["ext1"]
        assert ms.name == "ext1"
        assert ms.path == mod_dir
        assert ms.origin == "pkg:lms-ext-test==2.0.0"

    def test_name_mismatch_error(self, tmp_path: Path) -> None:
        """Entry point name != manifest name → collected as error."""
        mod_dir = _make_module(
            tmp_path, "actual_name",
            exports=["Z"],
            classes=[{"@id": "Z", "@type": "Class"}],
        )
        eps = [
            FakeEntryPoint(
                "wrong_name",
                lambda md=mod_dir: md,
                dist_name="lms-ext-test",
                dist_version="1.0.0",
            ),
        ]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            with pytest.raises(DiscoveryError) as exc:
                discover_module_dirs()
        msg = str(exc.value)
        assert "wrong_name" in msg
        assert "actual_name" in msg
        assert "does not match" in msg.lower()

    def test_load_failure(self) -> None:
        """Entry point that fails to load → collected as error."""
        def _fail() -> None:
            raise ImportError("cannot import")

        eps = [FakeEntryPoint("broken", _fail)]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            with pytest.raises(DiscoveryError) as exc:
                discover_module_dirs()
        msg = str(exc.value)
        assert "broken" in msg
        assert "ImportError" in msg

    def test_missing_manifest(self, tmp_path: Path) -> None:
        """Directory without manifest.json → error."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        eps = [FakeEntryPoint("ghost", lambda d=empty_dir: d)]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            with pytest.raises(DiscoveryError):
                discover_module_dirs()

    def test_str_pathlike_resolution(self, tmp_path: Path) -> None:
        """str/PathLike entries are resolved to Path."""
        mod_dir = _make_module(
            tmp_path, "ext_str",
            exports=["Z"],
            classes=[{"@id": "Z", "@type": "Class"}],
        )
        eps = [
            FakeEntryPoint(
                "ext_str",
                lambda md=mod_dir: str(md),
                dist_name="lms-ext-str",
                dist_version="3.0.0",
            ),
        ]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            result = discover_module_dirs()
        assert "ext_str" in result
        assert result["ext_str"].path == mod_dir

    def test_no_dist_uses_entry_point_name(self, tmp_path: Path) -> None:
        """When ep.dist is None, origin falls back to pkg:<ep.name>."""
        mod_dir = _make_module(
            tmp_path, "nodist",
            exports=["Z"],
            classes=[{"@id": "Z", "@type": "Class"}],
        )
        eps = [
            FakeEntryPoint("nodist", lambda md=mod_dir: md),
        ]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            result = discover_module_dirs()
        assert result["nodist"].origin == "pkg:nodist"

    def test_all_errors_collected(self, tmp_path: Path) -> None:
        """Multiple broken entry points → all errors collected, not just first."""
        def _fail() -> None:
            raise RuntimeError("fail")

        mod_dir = _make_module(
            tmp_path, "actual",
            exports=["Z"],
            classes=[{"@id": "Z", "@type": "Class"}],
        )
        eps = [
            FakeEntryPoint("broken1", _fail),
            FakeEntryPoint("broken2", lambda md=mod_dir: md),  # name mismatch
        ]
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=eps):
            with pytest.raises(DiscoveryError) as exc:
                discover_module_dirs()
        msg = str(exc.value)
        assert "broken1" in msg
        assert "broken2" in msg
        assert "actual" in msg  # from the name mismatch


# ---------------------------------------------------------------------------
# compose() integration tests
# ---------------------------------------------------------------------------


class TestComposeWithEntryPoints:
    """Integration: compose() merges repo + entry-point modules."""

    def test_pkg_only_module_composes(self, tmp_path: Path) -> None:
        """A pkg-only module (no repo dir, only via entry point) composes."""
        repo = tmp_path / "repo"
        _make_core(repo)

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "extmod",
            version="2.0.0",
            depends_on=[{"name": "core", "range": ">=1.0.0"}],
            exports=["Ext"],
            classes=[{"@id": "Ext", "@type": "Class", "@inherits": "Source", "label": "xsd:string"}],
        )

        ep_source = ModuleSource(
            name="extmod",
            path=pkg_dir / "extmod",
            origin="pkg:lms-ext-test==2.0.0",
        )
        result = compose(repo, entry_point_modules={"extmod": ep_source})
        names = [m.name for m in result.modules]
        assert "core" in names
        assert "extmod" in names
        # Verify source is recorded
        ext_info = next(m for m in result.modules if m.name == "extmod")
        assert ext_info.source == "pkg:lms-ext-test==2.0.0"

    def test_duplicate_name_across_sources(self, tmp_path: Path) -> None:
        """Same module name in repo AND pkg → hard error naming both origins."""
        repo = tmp_path / "repo"
        _make_core(repo)
        _make_module(
            repo, "dupe",
            exports=["A"],
            classes=[{"@id": "A", "@type": "Class"}],
        )

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "dupe",
            exports=["B"],
            classes=[{"@id": "B", "@type": "Class"}],
        )

        ep_source = ModuleSource(
            name="dupe",
            path=pkg_dir / "dupe",
            origin="pkg:lms-ext-dupe==1.0.0",
        )
        with pytest.raises(ComposerError) as exc:
            compose(repo, entry_point_modules={"dupe": ep_source})
        msg = str(exc.value)
        assert "dupe" in msg
        assert "repo:dupe" in msg
        assert "pkg:lms-ext-dupe==1.0.0" in msg

    def test_merged_topo_and_l2_works(self, tmp_path: Path) -> None:
        """Pkg module depends on repo module → topo sort correct, L2 passes."""
        repo = tmp_path / "repo"
        _make_core(repo)
        _make_module(
            repo, "m1",
            version="1.0.0",
            exports=["Foo"],
            classes=[{"@id": "Foo", "@type": "Class"}],
        )

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "extmod",
            version="2.0.0",
            depends_on=[{"name": "core", "range": ">=1.0.0"}, {"name": "m1", "range": ">=1.0.0"}],
            exports=["Bar"],
            classes=[{"@id": "Bar", "@type": "Class", "ref": "Foo"}],
        )

        ep_source = ModuleSource(name="extmod", path=pkg_dir / "extmod", origin="pkg:lms-ext-test==2.0.0")
        result = compose(repo, entry_point_modules={"extmod": ep_source})
        names = [m.name for m in result.modules]
        assert names[0] == "core"
        # m1 must come before extmod (extmod depends on m1)
        assert names.index("m1") < names.index("extmod")

    def test_entry_point_l2_violation(self, tmp_path: Path) -> None:
        """Pkg module references non-exported class of repo module → L2 error."""
        repo = tmp_path / "repo"
        _make_core(repo)
        _make_module(
            repo, "m1",
            version="1.0.0",
            exports=["Exported"],
            classes=[
                {"@id": "Exported", "@type": "Class"},
                {"@id": "Internal", "@type": "Class"},
            ],
        )

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "extmod",
            version="2.0.0",
            depends_on=[{"name": "core", "range": ">=1.0.0"}, {"name": "m1", "range": ">=1.0.0"}],
            exports=["Bar"],
            classes=[{"@id": "Bar", "@type": "Class", "ref": "Internal"}],
        )

        ep_source = ModuleSource(name="extmod", path=pkg_dir / "extmod", origin="pkg:lms-ext-test==2.0.0")
        with pytest.raises(L2Error) as exc:
            compose(repo, entry_point_modules={"extmod": ep_source})
        assert "Internal" in str(exc.value)

    def test_broken_entry_point_fails_loudly(self, tmp_path: Path) -> None:
        """A broken entry point that can't load manifest → ComposerError."""
        repo = tmp_path / "repo"
        _make_core(repo)

        # Put a malformed manifest in the pkg dir
        pkg_dir = tmp_path / "pkg"
        malformed_dir = _make_module(pkg_dir, "malformed", exports=["Z"], classes=[{"@id": "Z", "@type": "Class"}])
        # Corrupt the manifest
        (malformed_dir / "manifest.json").write_text("{invalid")

        ep_source = ModuleSource(name="malformed", path=malformed_dir, origin="pkg:bad==1.0.0")
        with pytest.raises(SchemaError):
            compose(repo, entry_point_modules={"malformed": ep_source})

    def test_no_entry_points_empty_disables(self, tmp_path: Path) -> None:
        """entry_point_modules={} disables discovery (via injection seam)."""
        repo = tmp_path / "repo"
        _make_core(repo)

        result = compose(repo, entry_point_modules={})
        names = [m.name for m in result.modules]
        assert names == ["core"]

    def test_include_entry_points_false_skips(self, tmp_path: Path) -> None:
        """include_entry_points=False skips discovery entirely."""
        repo = tmp_path / "repo"
        _make_core(repo)

        result = compose(repo, include_entry_points=False)
        names = [m.name for m in result.modules]
        assert names == ["core"]


# ---------------------------------------------------------------------------
# Lock file source recording
# ---------------------------------------------------------------------------


class TestLockSourceRecording:
    """Verify ModuleInfo.source flows into compose result correctly."""

    def test_repo_module_has_repo_source(self, tmp_path: Path) -> None:
        """Repo-tree modules get source = repo:<name>."""
        _make_core(tmp_path)
        result = compose(tmp_path)
        core_info = next(m for m in result.modules if m.name == "core")
        assert core_info.source == "repo:core"

    def test_pkg_module_has_pkg_source(self, tmp_path: Path) -> None:
        """Entry-point modules get source = pkg:<dist>==<version>."""
        repo = tmp_path / "repo"
        _make_core(repo)

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "extmod",
            exports=["E"],
            classes=[{"@id": "E", "@type": "Class"}],
        )

        ep_source = ModuleSource(name="extmod", path=pkg_dir / "extmod", origin="pkg:lms-ext-test==3.2.1")
        result = compose(repo, entry_point_modules={"extmod": ep_source})
        ext_info = next(m for m in result.modules if m.name == "extmod")
        assert ext_info.source == "pkg:lms-ext-test==3.2.1"

    def test_source_present_in_compose_result(self, tmp_path: Path) -> None:
        """Both repo and pkg modules have distinct source values."""
        repo = tmp_path / "repo"
        _make_core(repo)
        _make_module(
            repo, "repo_mod",
            exports=["R"],
            classes=[{"@id": "R", "@type": "Class"}],
        )

        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "pkg_mod",
            exports=["P"],
            classes=[{"@id": "P", "@type": "Class"}],
        )

        ep_source = ModuleSource(name="pkg_mod", path=pkg_dir / "pkg_mod", origin="pkg:lms-ext-pkg==1.0.0")
        result = compose(repo, entry_point_modules={"pkg_mod": ep_source})

        sources = {m.name: m.source for m in result.modules}
        assert sources["core"] == "repo:core"
        assert sources["repo_mod"] == "repo:repo_mod"
        assert sources["pkg_mod"] == "pkg:lms-ext-pkg==1.0.0"


# ---------------------------------------------------------------------------
# CLI --no-entry-points flag
# ---------------------------------------------------------------------------


class TestComposeCliNoEntryPoints:
    """Verify --no-entry-points flag via direct compose() call."""

    def test_flag_skips_entry_points(self, tmp_path: Path) -> None:
        """--no-entry-points excludes entry-point modules from composition."""
        repo = tmp_path / "repo"
        _make_core(repo)

        # Create a pkg module that would be discovered via entry points
        pkg_dir = tmp_path / "pkg"
        _make_module(
            pkg_dir, "extmod",
            exports=["E"],
            classes=[{"@id": "E", "@type": "Class"}],
        )

        ep_source = ModuleSource(name="extmod", path=pkg_dir / "extmod", origin="pkg:lms-ext==1.0.0")

        # With entry points → extmod included
        result_with = compose(repo, entry_point_modules={"extmod": ep_source})
        names_with = [m.name for m in result_with.modules]
        assert "extmod" in names_with

        # Without entry points → extmod excluded
        result_without = compose(repo, include_entry_points=False)
        names_without = [m.name for m in result_without.modules]
        assert "extmod" not in names_without


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestDiscoveryEdgeCases:
    """Edge-case behavior of discovery layer."""

    def test_no_entry_points_registered(self) -> None:
        """No lms.schema_modules entry points → empty result, no error."""
        with patch("lms_schema.discovery.importlib.metadata.entry_points", return_value=[]):
            result = discover_module_dirs()
        assert result == {}

    def test_compose_no_modules_anywhere(self, tmp_path: Path) -> None:
        """Neither repo nor entry points have modules → ComposerError."""
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ComposerError, match="No modules found"):
            compose(empty, entry_point_modules={})
