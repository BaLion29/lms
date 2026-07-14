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
COPY services/mcpd/ /app/services/mcpd/

WORKDIR /app/services/mcpd

# --package mcpd ensures uv only syncs this member; other workspace
# directories (extensions/*, other services/*) are absent from the build
# context and would cause discovery errors otherwise.
RUN uv sync --frozen --no-dev --package mcpd

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 mcpd

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=mcpd:mcpd /app /app

# Put the workspace venv on PATH so the mcpd console script is found directly.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/mcpd

EXPOSE 8090

USER mcpd

# All configuration is supplied via environment variables (MCPD_ prefix).
# See src/mcpd/settings.py for the full list.

CMD ["mcpd"]
