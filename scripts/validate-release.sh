#!/usr/bin/env bash
set -uo pipefail

# ── Resolve repo root ──────────────────────────────────────────────────────
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ── Counters ───────────────────────────────────────────────────────────────
PASS=0
FAIL=0

# ── Helper ─────────────────────────────────────────────────────────────────
check() {
    local desc="$1"
    shift
    printf "  %s ... " "$desc"
    if "$@" >/dev/null 2>&1; then
        printf "✅\n"
        PASS=$((PASS + 1))
    else
        printf "❌\n"
        FAIL=$((FAIL + 1))
    fi
}

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

# ── 1. No residual "lms" identity in tracked files ────────────────────────
check "No 'lms' in git ls-files names" \
    bash -c '! git ls-files | grep -qi lms'

# git grep for old repo-name patterns (not "LLMs" etc.)
# Excludes binary lock files and this script itself.
check "No old repo-name references (lms/davidsouther) in tracked files" \
    bash -c '! git grep -nE "(BaLion29/lms|/lms\.git|davidsouther/lms|davidsouther/firnline)" -- . \
        ":!scripts/validate-release.sh" \
        ":!services/webui/reflex.lock/bun.lock" \
        | grep -q .'

# ── 2. No secrets ──────────────────────────────────────────────────────────
check "No API keys in working tree" \
    bash -c '! git grep -nE "sk-[A-Za-z0-9]{16,}" -- . | grep -q .'

check "No API keys in git history" \
    bash -c '! git log --all -p -S '\''sk-'\'' -- . | grep -qE "^\+.*sk-[A-Za-z0-9]{16,}"'

# ── 3. No tracked junk ─────────────────────────────────────────────────────
check "No tracked __pycache__ / .pyc / .pytest_cache / node_modules" \
    bash -c '! git ls-files | grep -qE "__pycache__|\.pyc$|\.pytest_cache|node_modules"'

# ── 4. LICENSE exists and contains "Apache License" ────────────────────────
check "LICENSE exists and contains 'Apache License'" \
    bash -c 'test -f LICENSE && grep -q "Apache License" LICENSE'

# ── 5. All pyproject.toml versions are 0.1.0 (except extensions) ─────────
# packages/ and services/ must all match the release version.
# extensions/*/pyproject.toml may version independently.
check "All pyproject.toml versions are 0.1.0" \
    bash -c '
        all_ok=true
        while IFS= read -r f; do
            if [ ! -f "$f" ]; then continue; fi
            # Skip extensions — they version independently
            case "$f" in extensions/*) continue ;; esac
            ver=$(grep -E "^version\s*=\s*\"[^\"]+\"" "$f" | head -1 | grep -oP "\"[^\"]+\"" | tr -d "\"")
            if [ "$ver" != "0.1.0" ]; then
                echo "FAIL: $f has version=$ver" >&2
                all_ok=false
            fi
        done < <(git ls-files "**/pyproject.toml")
        $all_ok
    '

# ── 6. CHANGELOG.md contains ## [0.1.0-alpha] section ──────────────────────
check "CHANGELOG.md has [0.1.0-alpha] section" \
    bash -c 'grep -q "## \[0.1.0-alpha\]" CHANGELOG.md'

# ── 7. Lockfile consistency ────────────────────────────────────────────────
check "uv lock --check" \
    _uv lock --check

# ── 8. Sync ────────────────────────────────────────────────────────────────
check "uv sync --all-packages" \
    _uv sync --all-packages

# ── 9. Unit tests ──────────────────────────────────────────────────────────
echo "  Unit tests (pytest -m 'not integration' -q) ... "
if _uv run pytest -m "not integration" -q >/tmp/firnline-pytest.out 2>&1; then
    echo "    ✅"
    PASS=$((PASS + 1))
    # Print the summary tail (last 5 lines)
    tail -5 /tmp/firnline-pytest.out | sed 's/^/    /'
else
    echo "    ❌"
    FAIL=$((FAIL + 1))
    tail -10 /tmp/firnline-pytest.out | sed 's/^/    /'
fi

# ── 10. CLI smoke ──────────────────────────────────────────────────────────
check "firnline-schema --help exits 0" \
    _uv run firnline-schema --help

# ── 11. Import smoke ───────────────────────────────────────────────────────
check "import firnline_core, firnline_schema, captured, ingestd, queryd, triggerd" \
    _uv run python -c "import firnline_core, firnline_schema; from captured.main import main; from ingestd.main import main; from queryd.main import main; from triggerd.main import main"

# ── 12. Schema compose smoke (temp dir, no DB required) ────────────────────
check "firnline-schema compose (temp dir)" \
    _uv run firnline-schema compose --modules-dir schema/modules --out-dir /tmp/firnline-schema-validate

# ── 13. Melt test (kernel-purity check) ────────────────────────────────────
echo "  Melt test (kernel-purity) ... "
if bash "$REPO_ROOT/scripts/melt-test.sh" >/tmp/firnline-melt.out 2>&1; then
    echo "    ✅"
    PASS=$((PASS + 1))
    tail -3 /tmp/firnline-melt.out | sed 's/^/    /'
else
    echo "    ❌"
    FAIL=$((FAIL + 1))
    tail -10 /tmp/firnline-melt.out | sed 's/^/    /'
fi

# ── 14. Docker compose config valid ────────────────────────────────────────
if command -v docker &>/dev/null; then
    check "docker compose config -q" \
        bash -c 'TDB_PASSWORD=test CAPTURED_API_TOKEN=test QUERYD_API_TOKEN=test FIRNLINE_LLM_BASE_URL=http://x docker compose config -q'
else
    echo "  docker compose config check: SKIPPED (docker not installed)"
fi

# ── 15. Docs link check ────────────────────────────────────────────────────
check "All relative markdown links point to existing files" \
    bash -c '
        all_ok=true
        for md_file in README.md docs/*.md; do
            dir="$(dirname "$md_file")"
            # Extract relative links (not http/https)
            links=$(grep -oP "\[[^\]]*\]\(\K[^)]+(?=\))" "$md_file" | grep -v "^https\?://" || true)
            for link in $links; do
                # Resolve anchor-less path
                target="$dir/${link%%#*}"
                if [ ! -f "$target" ] && [ ! -d "${target}" ]; then
                    echo "BROKEN: $md_file → $link" >&2
                    all_ok=false
                fi
            done
        done
        $all_ok
    '

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
printf "  %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
