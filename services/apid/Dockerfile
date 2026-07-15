# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy workspace root so uv can discover the workspace members.
COPY pyproject.toml uv.lock /app/

# Copy the workspace members needed for this service.
COPY packages/firnline-core/ /app/packages/firnline-core/
COPY services/captured/ /app/services/captured/
COPY services/queryd/ /app/services/queryd/
COPY services/indexed/ /app/services/indexed/
COPY services/mcpd/ /app/services/mcpd/
COPY services/apid/ /app/services/apid/

WORKDIR /app/services/apid

# --package apid ensures uv only syncs this member; other workspace
# directories (extensions/*, other services/*) are absent from the build
# context and would cause discovery errors otherwise.
RUN uv sync --frozen --no-dev --package apid

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
RUN useradd -m -u 1000 apid

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=apid:apid /app /app

# Baked-in first-party extension wheels (FIRNLINE_EXTENSIONS picks from here).
COPY --from=builder --chown=apid:apid /app/wheels/ /extensions/

# Pre-create data directories for captured (blobs) and indexed (search index).
RUN mkdir -p /var/lib/firnline/blobs /var/lib/firnline/index \
    && chown -R apid:apid /var/lib/firnline

# Put the workspace venv on PATH so the apid console script is found directly.
# PYTHONPATH makes the extension overlay visible to importlib.metadata.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/firnline-ext-venv/lib

# Shared extension-installer entrypoint
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/services/apid

EXPOSE 8080

USER apid

# All configuration is supplied via environment variables (APID_, CAPTURED_,
# QUERYD_, INDEXED_, MCPD_ prefixes).  See individual service settings for details.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["apid"]
