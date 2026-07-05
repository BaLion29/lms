# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Layer 1 — project metadata (cached unless deps change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Layer 2 — source code (busts cache on code changes)
COPY src/ /app/src/
COPY README.md /app/

RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 ingestd

# Copy the application venv from builder, owned by the runtime user
COPY --from=builder --chown=ingestd:ingestd /app /app

# Put the venv on PATH so the entrypoint script is found directly
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

USER ingestd

# All configuration is supplied via environment variables (INGESTD_ prefix).
# See src/ingestd/settings.py for the full list.

# The entrypoint is the ingestd console script (service mode).
# Users pass --once / --dry-run as args to override the default polling mode.
ENTRYPOINT ["ingestd"]
