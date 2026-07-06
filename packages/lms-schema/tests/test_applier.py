"""Unit tests for applier.py pure decision logic (no network)."""

from __future__ import annotations

from pathlib import Path

from lms_schema.applier import (
    PendingMigration,
    build_action_plan,
    _schema_eq,
)
from lms_schema.composer import ComposeResult, ModuleInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_compose_result(
    modules: list[ModuleInfo] | None = None,
    schema: list[dict] | None = None,
) -> ComposeResult:
    if modules is None:
        modules = []
    if schema is None:
        schema = [{"@type": "@context"}]
    return ComposeResult(
        modules=modules,
        composed_schema=schema,
        class_id_to_module={},
    )


def _core_classes() -> list[dict]:
    return [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {"@abstract": [], "@id": "Context", "@type": "Class"},
    ]


def _context() -> dict:
    return {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}


# ---------------------------------------------------------------------------
# _schema_eq tests
# ---------------------------------------------------------------------------


class TestSchemaEq:
    def test_identical(self):
        s = [_context(), {"@id": "Foo", "@type": "Class", "name": "xsd:string"}]
        assert _schema_eq(s, s)

    def test_different(self):
        s1 = [_context(), {"@id": "Foo", "@type": "Class", "name": "xsd:string"}]
        s2 = [_context(), {"@id": "Foo", "@type": "Class", "name": "xsd:integer"}]
        assert not _schema_eq(s1, s2)

    def test_extra_class(self):
        s1 = [_context(), {"@id": "Foo", "@type": "Class"}]
        s2 = [_context(), {"@id": "Foo", "@type": "Class"}, {"@id": "Bar", "@type": "Class"}]
        assert not _schema_eq(s1, s2)

    def test_same_classes_different_order(self):
        """Different array order should still be equal (indexed by @id)."""
        s1 = [_context(), {"@id": "Foo", "@type": "Class"}, {"@id": "Bar", "@type": "Class"}]
        s2 = [_context(), {"@id": "Bar", "@type": "Class"}, {"@id": "Foo", "@type": "Class"}]
        assert _schema_eq(s1, s2)


# ---------------------------------------------------------------------------
# build_action_plan tests
# ---------------------------------------------------------------------------


class TestBuildActionPlan:

    def test_fresh_db_bootstrap(self):
        """Empty live schema, no registry → schema push needed, bootstrap."""
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
            ],
            schema=[_context()] + _core_classes(),
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[],  # fresh DB
            registry_modules=[],
            registry_migrations=[],
            disk_migrations_by_module={},
            is_bootstrap=True,
        )
        assert plan.schema_push_needed
        assert plan.is_bootstrap
        assert len(plan.registry_module_upserts) == 1
        assert plan.registry_module_upserts[0].name == "core"
        assert plan.has_actions
        assert not plan.has_errors
        assert len(plan.pending_migrations) == 0

    def test_up_to_date_noop(self):
        """Live schema matches, registry matches, no migrations → nothing to do."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,  # matches
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc123"},
            ],
            registry_migrations=[],
            disk_migrations_by_module={},
            is_bootstrap=False,
        )
        assert not plan.schema_push_needed
        assert len(plan.registry_module_upserts) == 0
        assert len(plan.pending_migrations) == 0
        assert not plan.has_actions
        assert not plan.has_errors

    def test_pending_migration(self):
        """A migration on disk not in registry → pending."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc123"},
            ],
            registry_migrations=[],  # empty
            disk_migrations_by_module={
                "core": [
                    PendingMigration(
                        module="core",
                        filename="0001_backfill.py",
                        checksum="mig123",
                        path=Path("/fake/core/migrations/0001_backfill.py"),
                    ),
                ],
            },
            is_bootstrap=False,
        )
        assert len(plan.pending_migrations) == 1
        assert plan.pending_migrations[0].filename == "0001_backfill.py"
        assert not plan.schema_push_needed
        assert plan.has_actions
        assert not plan.has_errors

    def test_pending_migration_already_recorded(self):
        """A migration already in registry → not pending."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc123"},
            ],
            registry_migrations=[
                {"@type": "SchemaMigration", "module": "core", "filename": "0001_backfill.py", "checksum": "mig123"},
            ],
            disk_migrations_by_module={
                "core": [
                    PendingMigration(
                        module="core",
                        filename="0001_backfill.py",
                        checksum="mig123",
                        path=Path("/fake/core/migrations/0001_backfill.py"),
                    ),
                ],
            },
            is_bootstrap=False,
        )
        assert len(plan.pending_migrations) == 0
        assert not plan.has_actions
        assert not plan.has_errors

    def test_checksum_drift_error(self):
        """Recorded migration checksum differs from disk → error."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc123"},
            ],
            registry_migrations=[
                {"@type": "SchemaMigration", "module": "core", "filename": "0001_backfill.py", "checksum": "old_checksum"},
            ],
            disk_migrations_by_module={
                "core": [
                    PendingMigration(
                        module="core",
                        filename="0001_backfill.py",
                        checksum="new_checksum_different",
                        path=Path("/fake/core/migrations/0001_backfill.py"),
                    ),
                ],
            },
            is_bootstrap=False,
        )
        assert plan.has_errors
        assert "checksum drift" in plan.errors[0].lower()
        assert len(plan.pending_migrations) == 0  # not pending since already recorded

    def test_registry_mismatch(self):
        """Registry module version/checksum differs from compose → upsert needed."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="new_checksum"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.0.0", "checksum": "old_checksum"},
            ],
            registry_migrations=[],
            disk_migrations_by_module={},
            is_bootstrap=False,
        )
        assert len(plan.registry_module_upserts) == 1
        assert plan.registry_module_upserts[0].checksum == "new_checksum"
        assert not plan.schema_push_needed  # schema matches

    def test_new_module_registry_entry(self):
        """Module in compose result but not in registry → upsert needed."""
        classes = _core_classes()
        cr = _make_compose_result(
            modules=[
                ModuleInfo(name="core", version="1.1.0", checksum="abc123"),
                ModuleInfo(name="inbox", version="2.0.0", checksum="def456"),
            ],
            schema=[_context()] + classes,
        )
        plan = build_action_plan(
            compose_result=cr,
            live_schema=[_context()] + classes,
            registry_modules=[
                {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc123"},
                # inbox NOT in registry
            ],
            registry_migrations=[],
            disk_migrations_by_module={},
            is_bootstrap=False,
        )
        assert len(plan.registry_module_upserts) == 1
        assert plan.registry_module_upserts[0].name == "inbox"
