# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy workspace root so uv can discover the workspace members.
COPY pyproject.toml uv.lock /app/

# Copy the two workspace members needed for this service.
COPY packages/firnline-core/ /app/packages/firnline-core/
COPY services/captured/ /app/services/captured/

WORKDIR /app/services/captured

# --package captured ensures uv only syncs this member; other workspace
# directories (extensions/*, other services/*) are absent from the build
# context and would cause discovery errors otherwise.
RUN uv sync --frozen --no-dev --package captured

# Build first-party extension wheels so they are baked into the image.
# This avoids requiring a host-side ./dist bind mount.
COPY extensions/ /app/extensions/
RUN mkdir -p /app/wheels && \
    for ext in /app/extensions/*/; do \
        uv build --wheel --out-dir /app/wheels/ "$ext"; \
    done

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 captured

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=captured:captured /app /app

# Baked-in first-party extension wheels (FIRNLINE_EXTENSIONS picks from here).
COPY --from=builder --chown=captured:captured /app/wheels/ /extensions/

# Put the workspace venv on PATH so uv-generated scripts are found directly.
# PYTHONPATH makes the extension overlay visible to importlib.metadata.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/firnline-ext-venv/lib

# Pre-create blob root with non-root ownership so Docker does not
# seed the named volume as root-owned (named volumes inherit image ownership).
RUN mkdir -p /var/lib/firnline/blobs && chown captured:captured /var/lib/firnline/blobs

# Shared extension-installer entrypoint
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/services/captured

EXPOSE 8088

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8088/healthz',timeout=5)"]

USER captured

# All configuration is supplied via environment variables (CAPTURED_ prefix).
# See src/captured/settings.py for the full list.
#
# Launch via console script entrypoint (captured = captured.main:main).
ENTRYPOINT ["/entrypoint.sh"]
CMD ["captured"]
