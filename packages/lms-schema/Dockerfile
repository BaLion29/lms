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
COPY packages/lms-core/ /app/packages/lms-core/
COPY packages/lms-schema/ /app/packages/lms-schema/

WORKDIR /app/packages/lms-schema

# --package lms-schema ensures uv only syncs this member.
RUN uv sync --frozen --no-dev --package lms-schema

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 lmsschema

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=lmsschema:lmsschema /app /app

# Put the workspace venv on PATH so the lms-schema CLI is found directly.
# PYTHONPATH makes the extension overlay visible to importlib.metadata.
# LMS_EXTENSIONS_INSTALL=true because this is the bootstrap image that
# installs extensions into the shared overlay volume.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/lms-ext-venv/lib \
    LMS_EXTENSIONS_INSTALL=true

# Pre-create overlay directory with non-root ownership so Docker does not
# seed the named volume as root-owned (named volumes inherit image ownership).
RUN mkdir -p /opt/lms-ext-venv/lib && chown -R lmsschema:lmsschema /opt/lms-ext-venv

# Shared extension-installer entrypoint
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/packages/lms-schema

USER lmsschema

# The entrypoint script installs extensions, then execs CMD.
# Default CMD is the lms-schema help; compose overrides this.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["lms-schema", "--help"]
