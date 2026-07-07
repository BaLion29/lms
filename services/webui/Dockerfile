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
COPY services/webui/ /app/services/webui/

WORKDIR /app/services/webui

RUN uv sync --frozen --no-dev --package firnline-webui

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Create non-root user (uid 1000)
RUN useradd -m -u 1000 webui

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=webui:webui /app /app

# Install bun (required by reflex for frontend compilation at startup).
# Reflex 0.9 compiles the Next.js frontend at container boot (~30-60s).
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl unzip && \
    curl -fsSL https://bun.sh/install | bash && \
    mv /root/.bun/bin/bun /usr/local/bin/ && \
    apt-get purge -y curl unzip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Put the workspace venv on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/webui

EXPOSE 3000

USER webui

# All configuration is supplied via environment variables (WEBUI_ prefix + REFLEX_*).
# See src/firnline_webui/settings.py for the full list of WEBUI_ vars.
#
# Startup: reflex compiles the frontend at boot (~30-60s), then serves backend
# + compiled frontend on a single port (default 3000).
CMD ["reflex", "run", "--env", "prod", "--backend-host", "0.0.0.0"]
