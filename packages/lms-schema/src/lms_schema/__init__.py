"""LMS Schema Module System — compose, diff, plan, apply, validate, promote, codegen."""


class SchemaError(Exception):
    """Common base for all lms-schema errors (manifest, compose, diff, migration)."""


from .composer import fragment_checksum  # noqa: E402

__all__ = ["SchemaError", "fragment_checksum"]
