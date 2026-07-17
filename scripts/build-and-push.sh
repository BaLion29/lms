#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build-and-push.sh — multi-arch Docker build + push for all Firnline images
#
# Usage examples:
#
#   # Set your Docker Hub namespace
#   export REGISTRY=yourdockerhubusername
#
#   # Build and push all images (multi-arch)
#   bash scripts/build-and-push.sh
#
#   # Override version
#   VERSION=0.1.0-alpha bash scripts/build-and-push.sh
#
#   # Single platform (faster for testing)
#   PLATFORMS=linux/amd64 bash scripts/build-and-push.sh
#
#   # Skip :latest tag
#   TAG_LATEST=false bash scripts/build-and-push.sh
# ---------------------------------------------------------------------------
set -euo pipefail

# ── Configuration (override via environment) ────────────────────────────────
# For CI (GitHub Actions), this is provided via the DOCKERHUB_NAMESPACE secret.
# For local runs, set this to your Docker Hub username.
REGISTRY="${REGISTRY:-firnline}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
TAG_LATEST="${TAG_LATEST:-true}"
BUILDER_NAME="${BUILDER_NAME:-firnline-builder}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ── Determine version ──────────────────────────────────────────────────────
if [ -n "${VERSION:-}" ]; then
    echo ">>> Using VERSION from environment: $VERSION"
else
    VERSION="$(grep -E '^version\s*=\s*"[^"]+"' pyproject.toml | head -1 | grep -oP '"[^"]+"' | tr -d '"')"
    echo ">>> Extracted VERSION from pyproject.toml: $VERSION"
fi

# Strip leading 'v' if present (e.g. v0.1.0-alpha → 0.1.0-alpha) to match
# the CI workflow convention and Docker Hub tagging best practices.
VERSION="${VERSION#v}"

# ── Image definitions (name → Dockerfile path) ─────────────────────────────
declare -A IMAGES=(
    ["firnline-schema"]="packages/firnline-schema/Dockerfile"
    ["apid"]="services/apid/Dockerfile"
    ["ingestd"]="services/ingestd/Dockerfile"
    ["triggerd"]="services/triggerd/Dockerfile"
    ["effectd"]="services/effectd/Dockerfile"
    ["webui"]="services/webui/Dockerfile"
)

# ── Pre-flight checks ──────────────────────────────────────────────────────
echo ""
echo "=== Pre-flight checks ==="

echo "  Checking Docker Hub login ..."
if ! docker info 2>/dev/null | grep -q Username; then
    echo "ERROR: Not logged in to Docker Hub. Run: docker login"
    exit 1
fi
echo "  ✅  Logged in to Docker Hub"

# ── Set up buildx builder ──────────────────────────────────────────────────
echo ""
echo "=== Setting up buildx builder '$BUILDER_NAME' ==="
if docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    echo "  Builder '$BUILDER_NAME' already exists, using it."
    docker buildx use "$BUILDER_NAME"
else
    echo "  Creating new builder '$BUILDER_NAME' ..."
    docker buildx create --name "$BUILDER_NAME" --use
fi
docker buildx inspect --bootstrap
echo "  ✅  Buildx builder '$BUILDER_NAME' ready"

# ── Build and push each image ──────────────────────────────────────────────
echo ""
echo "=== Building and pushing images ==="
echo "  Registry:  $REGISTRY"
echo "  Version:   $VERSION"
echo "  Platforms: $PLATFORMS"
echo "  Tag latest:$TAG_LATEST"
echo ""

push_summary=""

for name in "${!IMAGES[@]}"; do
    dockerfile="${IMAGES[$name]}"

    echo "────────────────────────────────────────"
    echo "  Building: $REGISTRY/$name:$VERSION"
    echo "  Dockerfile: $dockerfile"
    echo ""

    args=(
        buildx build
        --platform "$PLATFORMS"
        --file "$dockerfile"
        --tag "$REGISTRY/$name:$VERSION"
        --push
        .
    )

    if [ "$TAG_LATEST" = "true" ]; then
        args+=(--tag "$REGISTRY/$name:latest")
    fi

    docker "${args[@]}"

    push_summary+="  $REGISTRY/$name:$VERSION"$'\n'
    if [ "$TAG_LATEST" = "true" ]; then
        push_summary+="  $REGISTRY/$name:latest"$'\n'
    fi

    echo ""
    echo "  ✅  Pushed $REGISTRY/$name:$VERSION"
done

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Build complete — pushed image tags:"
echo "========================================"
echo "$push_summary"
echo "========================================"
