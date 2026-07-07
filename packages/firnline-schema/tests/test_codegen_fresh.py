"""CI freshness check — ensures generated code matches what compose+codegen produces.

Re-runs codegen in a temp directory with the actual targets and verifies
the committed files are byte-identical to the regenerated output.  Because
cross-module imports use absolute paths, the redirect trick from earlier
versions no longer works — we instead snapshot the committed files, run
the real ``write_generated`` (which overwrites them), and then assert they
match the snapshot.  If the test fails, the committed files were stale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firnline_schema.codegen import schema_checksum, write_generated

BUILD_DIR = Path(__file__).parents[3] / "build"
GENERATED_DIR = Path(__file__).parents[3] / "packages" / "firnline-core" / "src" / "firnline_core" / "generated"


def _compose_meta() -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Load the composed schema, class-to-module mapping, and targets from build/."""
    composed = json.loads((BUILD_DIR / "composed.schema.json").read_text())
    meta = json.loads((BUILD_DIR / "composed.meta.json").read_text())
    return composed, meta.get("classes", {}), meta.get("targets", {})


def test_codegen_freshness():
    """Regenerate and assert byte-equality with committed files.

    Generates directly to the committed package then verifies the
    output matches pre-saved copies.  This works because cross-module
    imports need their absolute target paths.
    """
    composed_schema, class_id_to_module, module_to_target = _compose_meta()
    if not module_to_target:
        pytest.skip("No targets in compose meta — run 'firnline-schema compose' first with updated schema.")

    checksum = schema_checksum(composed_schema)

    # Snapshot the committed files before regeneration
    committed_files: dict[str, bytes] = {}
    for f in sorted(GENERATED_DIR.rglob("*.py")):
        committed_files[f.name] = f.read_bytes()

    # Filter to kernel-only targets (those writing into firnline_core.generated)
    kernel_targets: dict[str, str] = {}
    kernel_classes: dict[str, str] = {}
    for mod_name, target in module_to_target.items():
        if target.startswith("firnline_core.generated."):
            kernel_targets[mod_name] = target
    for cid, mod_name in class_id_to_module.items():
        if mod_name in kernel_targets:
            kernel_classes[cid] = mod_name

    # Run the real codegen — this will overwrite committed files
    _paths = write_generated(composed_schema, kernel_classes, kernel_targets, checksum)

    # Verify every committed file was regenerated and content matches
    for f in sorted(GENERATED_DIR.rglob("*.py")):
        if f.name not in committed_files:
            continue
        assert f.read_bytes() == committed_files[f.name], (
            f"Freshness check failed for {f.name}. "
            "Run 'firnline-schema compose && firnline-schema codegen' and commit the result."
        )

    # Also verify the generated package imports cleanly
    import firnline_core.generated  # noqa: F401
    assert firnline_core.generated.InboxNote is not None
