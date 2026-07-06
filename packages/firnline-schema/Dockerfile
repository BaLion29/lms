# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy workspace root so uv can discover the workspace members.
COPY pyproject.toml uv.lock /app/

# Copy the two workspace members needed for this package.
COPY packages/firnline-core/ /app/packages/firnline-core/
COPY packages/firnline-schema/ /app/packages/firnline-schema/

WORKDIR /app/packages/firnline-schema

# --package firnline-schema ensures uv only syncs this member.
RUN uv sync --frozen --no-dev --package firnline-schema

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
RUN useradd -m -u 1000 firnlineschema

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=firnlineschema:firnlineschema /app /app

# Baked-in first-party extension wheels (FIRNLINE_EXTENSIONS picks from here).
COPY --from=builder --chown=firnlineschema:firnlineschema /app/wheels/ /extensions/

# Put the workspace venv on PATH so the firnline-schema CLI is found directly.
# PYTHONPATH makes the extension overlay visible to importlib.metadata.
# FIRNLINE_EXTENSIONS_INSTALL=true because this is the bootstrap image that
# installs extensions into the shared overlay volume.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/firnline-ext-venv/lib \
    FIRNLINE_EXTENSIONS_INSTALL=true

# Pre-create overlay directory with non-root ownership so Docker does not
# seed the named volume as root-owned (named volumes inherit image ownership).
RUN mkdir -p /opt/firnline-ext-venv/lib && chown -R firnlineschema:firnlineschema /opt/firnline-ext-venv

# Shared extension-installer entrypoint
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/packages/firnline-schema

USER firnlineschema

# The entrypoint script installs extensions, then execs CMD.
# Default CMD is the firnline-schema help; compose overrides this.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["firnline-schema", "--help"]
