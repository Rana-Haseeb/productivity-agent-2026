"""
Embedding service for semantic note search.

Wraps ``sentence-transformers`` (all-MiniLM-L6-v2, 384-d, cached locally). The model
is loaded lazily and cached so the ~90 MB load happens at most once per process.
Vectors are L2-normalized so cosine distance in pgvector behaves as expected.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from app.config import settings


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so importing this module doesn't pull torch until needed.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed(text: str) -> np.ndarray:
    """Return a normalized float32 embedding for a single string."""
    vec = _model().encode(text, normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def embed_many(texts: list[str]) -> list[np.ndarray]:
    """Batch-embed several strings (more efficient than repeated ``embed``)."""
    vecs = _model().encode(list(texts), normalize_embeddings=True)
    return [np.asarray(v, dtype=np.float32) for v in vecs]
