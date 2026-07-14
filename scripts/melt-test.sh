#!/usr/bin/env bash
set -euo pipefail

# ── melt test: machine-enforced kernel-purity check ────────────────────────
# The kernel is what remains when all seasonal snow melts.
# Kernel must compose, generate, import, and idle gracefully with
# ZERO extensions installed.
#
# Run from the repo root via:  bash scripts/melt-test.sh
# (Also invoked by scripts/validate-release.sh)

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ── uv wrapper (NixOS compat) ──────────────────────────────────────────────
_uv() {
    if command -v uv &>/dev/null && uv --version &>/dev/null 2>&1; then
        uv "$@"
    else
        local cmd="uv"
        for a in "$@"; do
            cmd="$cmd $(printf '%q' "$a")"
        done
        nix-shell -p uv --run "$cmd"
    fi
}

PASS=0
FAIL=0

fail() {
    echo "  ❌  $*"
    FAIL=$((FAIL + 1))
}

pass() {
    echo "  ✅  $*"
    PASS=$((PASS + 1))
}

# ── Temp dir with cleanup ──────────────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

GEN_DIR="packages/firnline-core/src/firnline_core/generated"

echo "=== Melt Test ==="
echo ""

# ── Step 1: Kernel-only compose ────────────────────────────────────────────
echo "--- 1. Kernel-only compose ---"
if _uv run --package firnline-schema firnline-schema compose \
    --modules-dir schema/modules \
    --out-dir "$TMP" \
    --no-entry-points 2>/dev/null; then
    pass "compose completed (4 kernel modules)"
else
    fail "compose failed"
fi
echo ""

# ── Step 2: Capture untracked baseline before codegen ──────────────────────
# We snapshot untracked files under packages/ and extensions/ BEFORE codegen,
# then check that codegen does not create any NEW ones.
BASELINE_UNTRACKED="$(git status --porcelain -- packages/ extensions/ | grep '^?? ' || true)"

# ── Step 3: Codegen from kernel-only compose ───────────────────────────────
echo "--- 2. Codegen ---"
if _uv run --package firnline-schema firnline-schema codegen \
    --composed "$TMP/composed.schema.json" \
    --meta "$TMP/composed.meta.json" 2>/dev/null; then
    pass "codegen completed"
else
    fail "codegen failed"
fi
echo ""

# ── Step 4: Check that codegen only affected kernel model files ────────────
# The checksum-tolerant diff logic:
#   Codegen always rewrites the "Source lock checksum" header line.
#   If the kernel-only checksum differs from the committed full-compose
#   checksum, that line changes.  Treat checksum-only diffs as tolerable.
#   If any other content differs, report it.
#
#   Approach: compare each file with the checksum line filtered out.
#   If the filtered files match, the diff is checksum-only → restore.
#   If they differ, the melt test found real drift.
echo "--- 3. Diff check (checksum-tolerant) ---"

CHANGED_FILES=""
# Collect all generated .py files that git tracks in the gen dir
for f in $(git ls-files -- "$GEN_DIR"/*.py); do
    base="$(basename "$f")"
    # Compare committed vs working-tree content with checksum line stripped
    committed_clean="$(git show "HEAD:$f" 2>/dev/null | grep -v "lock checksum" || true)"
    worktree_clean="$(cat "$f" 2>/dev/null | grep -v "lock checksum" || true)"
    if [ "$committed_clean" != "$worktree_clean" ]; then
        CHANGED_FILES="$CHANGED_FILES $base"
    fi
done

if [ -n "$CHANGED_FILES" ]; then
    fail "Non-checksum changes in generated files:$CHANGED_FILES"
    echo "      (tip: run codegen from full compose to update committed generated files)"
    echo "      Current diff stat:"
    git diff --stat -- "$GEN_DIR/" | sed 's/^/        /'
else
    # Checksum-only diff — restore and continue
    echo "  ℹ️  checksum-only differences (tolerated)"
    git checkout -- "$GEN_DIR/"
    pass "Generated files match kernel-only codegen (modulo checksum)"
fi
echo ""

# ── Step 5: Assert codegen created no NEW untracked files ──────────────────
echo "--- 4. Untracked file check ---"
# Kernel-only codegen must not introduce new untracked files under
# packages/ or extensions/.  Compare against the pre-codegen baseline.
POST_UNTRACKED="$(git status --porcelain -- packages/ extensions/ | grep '^?? ' || true)"
NEW_UNTRACKED="$(comm -13 <(echo "$BASELINE_UNTRACKED" | sort) <(echo "$POST_UNTRACKED" | sort) || true)"
if [ -n "$NEW_UNTRACKED" ]; then
    fail "Codegen introduced new untracked files:"
    echo "$NEW_UNTRACKED" | sed 's/^/        /'
else
    pass "No new untracked files introduced by kernel-only codegen"
fi
echo ""

# ── Step 6: Kernel import melt ─────────────────────────────────────────────
echo "--- 5. Kernel import melt ---"
if _uv run python -c "
import firnline_core
import firnline_core.models
import firnline_core.tooling
import firnline_core.plugins
import firnline_core.tdb
" 2>/dev/null; then
    pass "All kernel modules import successfully"
else
    fail "Kernel import failed"
fi
echo ""

# ── Step 7: Kernel-mode pytest ─────────────────────────────────────────────
echo "--- 6. Kernel melt pytest ---"
if _uv run pytest scripts/melt_test -q 2>&1; then
    pass "Kernel melt pytest suite passed"
else
    fail "Kernel melt pytest suite failed"
fi
echo ""

# ── Cleanup: restore generated files if they were only checksum-different ──
# (If the diff check failed, generated files hold the correct kernel codegen
#  output and should NOT be reverted, since models.py expects them.)
if [ -z "${CHANGED_FILES:-}" ]; then
    git checkout -- "$GEN_DIR/" 2>/dev/null || true
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo "========================================"
if [ "$FAIL" -eq 0 ]; then
    echo "  Melt test: PASSED (kernel is pure)"
    echo "  $PASS checks passed"
    echo "========================================"
    exit 0
else
    echo "  Melt test: FAILED ($FAIL check(s) failed, $PASS passed)"
    echo "========================================"
    exit 1
fi
