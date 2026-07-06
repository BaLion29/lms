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
COPY packages/lms-core/ /app/packages/lms-core/
COPY services/ingestd/ /app/services/ingestd/

WORKDIR /app/services/ingestd

RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 ingestd

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=ingestd:ingestd /app /app

# Put the workspace venv on PATH so the entrypoint script is found directly
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/services/ingestd

USER ingestd

# All configuration is supplied via environment variables (INGESTD_ prefix).
# See src/ingestd/settings.py for the full list.

# The entrypoint is the ingestd console script (service mode).
# Users pass --once / --dry-run as args to override the default polling mode.
ENTRYPOINT ["ingestd"]
