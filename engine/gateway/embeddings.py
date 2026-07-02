"""Embedding client. Probes the endpoint once to detect its API shape
(OpenAI /v1/embeddings vs llama.cpp-native /embedding, whose response shapes differ),
caches the detection, asserts the expected dimension, L2-normalizes.

FakeEmbedder: deterministic hashed bag-of-tokens — cosine similarity correlates with
token overlap, so the uniqueness gate is meaningfully exercised without a live server.
"""

import hashlib
import re

import httpx
import numpy as np

from engine.config import settings


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class FakeEmbedder:
    def __init__(self, dim: int = 768):
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 64) % 2 else -1.0
        return _normalize(v)


class HttpEmbedder:
    def __init__(self, base_url: str | None = None, dim: int | None = None, timeout: float = 120.0):
        self.base_url = (base_url or settings().embed_base).rstrip("/")
        self.dim = dim or settings().embed_dim
        self.timeout = timeout
        self._mode: str | None = None  # openai | native

    def _probe(self) -> str:
        if self._mode:
            return self._mode
        try:
            r = httpx.post(
                f"{self.base_url}/v1/embeddings",
                json={"input": "probe", "model": "default"},
                timeout=self.timeout,
            )
            if r.status_code == 200 and "data" in r.json():
                self._mode = "openai"
                return self._mode
        except httpx.HTTPError:
            pass
        r = httpx.post(f"{self.base_url}/embedding", json={"content": "probe"}, timeout=self.timeout)
        r.raise_for_status()
        self._mode = "native"
        return self._mode

    def embed(self, text: str) -> np.ndarray:
        mode = self._probe()
        if mode == "openai":
            r = httpx.post(
                f"{self.base_url}/v1/embeddings",
                json={"input": text, "model": "default"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            vec = r.json()["data"][0]["embedding"]
        else:
            r = httpx.post(
                f"{self.base_url}/embedding", json={"content": text}, timeout=self.timeout
            )
            r.raise_for_status()
            data = r.json()
            # llama.cpp native returns {"embedding": [...]} or [{"embedding": [[...]]}]
            if isinstance(data, list):
                data = data[0]
            vec = data["embedding"]
            if vec and isinstance(vec[0], list):
                vec = vec[0]
        arr = np.asarray(vec, dtype=np.float32)
        if arr.shape[0] != self.dim:
            raise ValueError(f"embedding dim {arr.shape[0]} != expected {self.dim}")
        return _normalize(arr)


def get_embedder(provider_override: str | None = None):
    if provider_override == "mock":
        return FakeEmbedder()
    return HttpEmbedder()
