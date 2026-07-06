"""CI freshness check — ensures generated code matches what compose+codegen produces.

Regenerates into a temp directory and asserts byte-equality with the
committed files in ``packages/firnline-core/src/firnline_core/generated/``.
"""

from __future__ import annotations

import json
from pathlib import Path

from firnline_schema.codegen import schema_checksum, write_generated

MODULES_DIR = Path(__file__).parents[3] / "schema" / "modules"
GENERATED_DIR = Path(__file__).parents[3] / "packages" / "firnline-core" / "src" / "firnline_core" / "generated"


def _compose_meta() -> tuple[list[dict], dict[str, str]]:
    """Load the composed schema and class-to-module mapping from build/."""
    build_dir = Path(__file__).parents[3] / "build"
    composed = json.loads((build_dir / "composed.schema.json").read_text())
    meta = json.loads((build_dir / "composed.meta.json").read_text())
    return composed, meta.get("classes", {})


def test_codegen_freshness(tmp_path: Path):
    """Regenerate into a tmp dir and assert byte-equality with committed files."""
    composed_schema, class_id_to_module = _compose_meta()
    checksum = schema_checksum(composed_schema)

    write_generated(tmp_path, composed_schema, class_id_to_module, checksum)

    # Compare each generated file
    committed_files = sorted(GENERATED_DIR.rglob("*.py"))
    tmp_files = sorted(tmp_path.rglob("*.py"))

    committed_names = {f.name for f in committed_files}
    tmp_names = {f.name for f in tmp_files}

    assert committed_names == tmp_names, (
        f"File set mismatch:\n"
        f"  only in committed: {committed_names - tmp_names}\n"
        f"  only in generated: {tmp_names - committed_names}"
    )

    for cf in committed_files:
        tf = tmp_path / cf.name
        assert cf.read_bytes() == tf.read_bytes(), (
            f"Freshness check failed for {cf.name}. "
            f"Run 'firnline-schema compose && firnline-schema codegen' and commit the result."
        )

    # Also verify the generated package imports cleanly
    import firnline_core.generated  # noqa: F401 — ensures __init__.py works
    assert firnline_core.generated.InboxNote is not None
