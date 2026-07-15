# ---------------------------------------------------------------------------
# Stage 1 — builder: uv-based dependency installation
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock /app/

COPY packages/firnline-core/ /app/packages/firnline-core/
COPY services/indexed/ /app/services/indexed/

WORKDIR /app/services/indexed

RUN uv sync --frozen --no-dev --package indexed

COPY extensions/ /app/extensions/
RUN mkdir -p /app/wheels && \
    for ext in /app/extensions/*/; do \
        uv build --wheel --out-dir /app/wheels/ "$ext"; \
    done

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim Python image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

RUN useradd -m -u 1000 indexed
RUN mkdir -p /var/lib/firnline/index && chown -R indexed:indexed /var/lib/firnline

COPY --from=builder --chown=indexed:indexed /app /app
COPY --from=builder --chown=indexed:indexed /app/wheels/ /extensions/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/firnline-ext-venv/lib

COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

WORKDIR /app/services/indexed

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=150s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8089/healthz',timeout=5)"]

EXPOSE 8089

USER indexed

ENTRYPOINT ["/entrypoint.sh"]
CMD ["indexed"]
