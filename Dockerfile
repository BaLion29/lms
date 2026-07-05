# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy lms-core and lms-ingestd preserving the ../lms-core relative layout
# so that the editable path dependency resolves.
COPY lms-core/ /app/lms-core/
COPY lms-ingestd/ /app/lms-ingestd/

WORKDIR /app/lms-ingestd

RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 ingestd

# Copy the application venv + source from builder, owned by the runtime user.
# Keeping the same paths (/app/lms-core, /app/lms-ingestd) ensures uv's
# editable installs (which record absolute paths) remain valid.
COPY --from=builder --chown=ingestd:ingestd /app /app

# Put the venv on PATH so the entrypoint script is found directly
ENV PATH="/app/lms-ingestd/.venv/bin:$PATH"

WORKDIR /app/lms-ingestd

USER ingestd

# All configuration is supplied via environment variables (INGESTD_ prefix).
# See src/ingestd/settings.py for the full list.

# The entrypoint is the ingestd console script (service mode).
# Users pass --once / --dry-run as args to override the default polling mode.
ENTRYPOINT ["ingestd"]
