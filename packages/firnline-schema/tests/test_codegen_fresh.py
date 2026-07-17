"""CI freshness check — ensures generated code matches what compose+codegen produces.

Re-runs codegen in-memory (via ``generate()``) and compares the output against
the committed ``generated/*.py`` files.  This test NEVER writes to the working
tree — it only reads committed files and compares them to freshly-generated
source text.

If the ``build/`` directory (containing ``composed.schema.json`` and
``composed.meta.json``) is absent, the test is skipped because the compose
step has not been run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firnline_schema.codegen import generate, schema_checksum

# Resolve the workspace root from this test file's location:
#   tests/test_codegen_fresh.py  ->  parents[2]  (firnline-schema package)
#   parents[3]                     ->  packages/
#   parents[4]                     ->  workspace root
WORKSPACE_ROOT = Path(__file__).parents[4]
BUILD_DIR = WORKSPACE_ROOT / "build"
GENERATED_DIR = (
    WORKSPACE_ROOT
    / "packages"
    / "firnline-core"
    / "src"
    / "firnline_core"
    / "generated"
)


def _compose_meta() -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Load the composed schema, class-to-module mapping, and targets from build/."""
    composed = json.loads((BUILD_DIR / "composed.schema.json").read_text())
    meta = json.loads((BUILD_DIR / "composed.meta.json").read_text())
    return composed, meta.get("classes", {}), meta.get("targets", {})


def test_codegen_freshness():
    """Regenerate in-memory and assert byte-equality with committed files.

    Uses ``generate()`` (which returns source text without writing to disk)
    so committed ``generated/*.py`` files are never overwritten.
    """
    # Skip when build/ artifacts are absent (compose has not been run).
    if not (BUILD_DIR / "composed.schema.json").exists():
        pytest.skip(
            "build/composed.schema.json not found — run 'firnline-schema compose' "
            "to generate the artifacts needed for this freshness check."
        )

    composed_schema, class_id_to_module, module_to_target = _compose_meta()
    if not module_to_target:
        pytest.skip(
            "No targets in compose meta — run 'firnline-schema compose' first "
            "with updated schema."
        )

    checksum = schema_checksum(composed_schema)

    # Filter to kernel-only targets (those writing into firnline_core.generated)
    kernel_targets: dict[str, str] = {}
    kernel_classes: dict[str, str] = {}
    for mod_name, target in module_to_target.items():
        if target.startswith("firnline_core.generated."):
            kernel_targets[mod_name] = target
    for cid, mod_name in class_id_to_module.items():
        if mod_name in kernel_targets:
            kernel_classes[cid] = mod_name

    # Generate source text in-memory — NO disk writes.
    sources = generate(composed_schema, kernel_classes, kernel_targets, checksum)

    # Snapshot the committed files.
    committed_files: dict[str, bytes] = {}
    for f in sorted(GENERATED_DIR.rglob("*.py")):
        committed_files[f.name] = f.read_bytes()

    # Compare every generated file against the committed counterpart.
    for filename, source_text in sources.items():
        committed = committed_files.get(filename)
        if committed is None:
            # File was generated but is not committed — could be __init__.py
            # or a new module.  Skip files that aren't committed yet.
            if filename == "__init__.py":
                continue
            pytest.fail(
                f"Freshness check failed: generated file '{filename}' has no "
                f"committed counterpart. Run 'firnline-schema codegen' and "
                f"commit the result."
            )
        assert committed == (source_text + "\n").encode(), (
            f"Freshness check failed for {filename}. "
            "Run 'firnline-schema compose && firnline-schema codegen' and commit the result."
        )

    # Also verify the generated package imports cleanly
    import firnline_core.generated  # noqa: F401
    # Pick any currently-present class (avoid stale refs from removed modules)
    import importlib
    gen_mod = importlib.import_module("firnline_core.generated.core")
    assert gen_mod.SchemaModule is not None
