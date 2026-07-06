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

# --package queryd ensures uv only syncs this member; other workspace
# directories (extensions/*, other services/*) are absent from the build
# context and would cause discovery errors otherwise.
RUN uv sync --frozen --no-dev --package queryd

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
RUN useradd -m -u 1000 queryd

# Copy the application venv + source from builder, owned by the runtime user.
COPY --from=builder --chown=queryd:queryd /app /app

# Baked-in first-party extension wheels (LMS_EXTENSIONS picks from here).
COPY --from=builder --chown=queryd:queryd /app/wheels/ /extensions/

# Put the workspace venv on PATH so the queryd console script is found directly.
# PYTHONPATH makes the extension overlay visible to importlib.metadata.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/lms-ext-venv/lib

# Shared extension-installer entrypoint
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/services/queryd

EXPOSE 8087

USER queryd

# All configuration is supplied via environment variables (QUERYD_ prefix).
# See src/queryd/settings.py for the full list.

# The entrypoint script handles extension installation, then execs CMD.
# NOTE: With ENTRYPOINT + CMD, additional docker-run args REPLACE CMD.
# To pass extra args:  docker run lms/queryd queryd <extra-args>
ENTRYPOINT ["/entrypoint.sh"]
CMD ["queryd"]
