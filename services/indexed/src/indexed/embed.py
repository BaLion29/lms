"""Embedding client — calls LiteLLM proxy's /v1/embeddings endpoint."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


def _build_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


async def _embed_batch(
    base_url: str,
    api_key: str,
    model: str,
    texts: list[str],
    client: httpx.AsyncClient,
) -> list[list[float]]:
    """Send a batch of texts to the embedding endpoint."""

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = _build_url(base_url)

    response = await client.post(
        url,
        json={"input": texts, "model": model},
        headers=headers,
        timeout=60.0,
    )

    if response.status_code != 200:
        body = response.text[:500]
        raise EmbeddingError(f"Embedding API returned {response.status_code}: {body}")

    data = response.json()
    items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    return [item["embedding"] for item in items]


async def embed_texts(
    base_url: str,
    api_key: str,
    model: str,
    texts: list[str],
    *,
    batch_size: int = 20,
) -> list[list[float]]:
    """Generate embeddings for *texts* via LiteLLM, batched.

    Returns one embedding vector per input text, in order.
    """
    if not texts:
        return []

    async with httpx.AsyncClient() as client:
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                batch_results = await _embed_batch(base_url, api_key, model, batch, client)
                results.extend(batch_results)
            except Exception:
                logger.warning(
                    "embed_batch_failed",
                    batch_start=i,
                    batch_size=len(batch),
                    exc_info=True,
                )
                raise

        return results
