"""Embedding generation via the local Ollama daemon.

Single source of inference (both chat and embeddings) stays on-box —
see docs/architecture.md.
"""

import httpx

from router.config import EMBED_MODEL, OLLAMA_BASE_URL


def embed(texts: list[str]) -> list[list[float]]:
    """Embed one or more strings using the local Ollama embedding model."""
    if not texts:
        return []
    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data["embeddings"]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
