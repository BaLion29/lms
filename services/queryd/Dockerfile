# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy lms-core and lms-queryd preserving the ../lms-core relative layout
# so that the editable path dependency resolves.
COPY lms-core/ /app/lms-core/
COPY lms-queryd/ /app/lms-queryd/

WORKDIR /app/lms-queryd

RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 queryd

# Copy the application venv + source from builder, owned by the runtime user.
# Keeping the same paths (/app/lms-core, /app/lms-queryd) ensures uv's
# editable installs (which record absolute paths) remain valid.
COPY --from=builder --chown=queryd:queryd /app /app

# Put the venv on PATH so the entrypoint script is found directly
ENV PATH="/app/lms-queryd/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/lms-queryd

EXPOSE 8087

USER queryd

# All configuration is supplied via environment variables (QUERYD_ prefix).
# See src/queryd/settings.py for the full list.

ENTRYPOINT ["queryd"]
