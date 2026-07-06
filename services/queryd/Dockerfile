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
COPY services/queryd/ /app/services/queryd/

WORKDIR /app/services/queryd

RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 queryd

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=queryd:queryd /app /app

# Put the workspace venv on PATH so the entrypoint script is found directly
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/queryd

EXPOSE 8087

USER queryd

# All configuration is supplied via environment variables (QUERYD_ prefix).
# See src/queryd/settings.py for the full list.

ENTRYPOINT ["queryd"]
