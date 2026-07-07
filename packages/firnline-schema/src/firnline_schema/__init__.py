"""Firnline Schema Module System — compose, diff, plan, apply, validate, promote, codegen."""


class SchemaError(Exception):
    """Common base for all firnline-schema errors (manifest, compose, diff, migration)."""


from .composer import fragment_checksum, DocumentationError  # noqa: E402

__all__ = ["SchemaError", "fragment_checksum", "DocumentationError"]
