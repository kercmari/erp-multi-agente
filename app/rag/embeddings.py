"""Generacion de embeddings.

Dos implementaciones tras la misma interfaz:

- HashingEmbedder: deterministico, local, sin red ni credenciales. Usa el
  truco de "hashing vectorizer" sobre n-gramas de caracteres. No entiende
  semantica profunda, pero recupera bien por solapamiento lexico y hace que
  la demo sea 100% reproducible y los tests estables.
- NvidiaEmbedder: embeddings reales del proveedor, mismo contrato.

La eleccion se hace por configuracion; el resto del RAG no cambia.
"""
from __future__ import annotations

import abc
import hashlib
import math
import re

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(abc.ABC):
    dim: int

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Devuelve una matriz (n_textos, dim) con vectores L2-normalizados."""


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class HashingEmbedder(Embedder):
    """Proyecta tokens y trigramas a un espacio fijo mediante hashing."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        low = text.lower()
        tokens = _TOKEN_RE.findall(low)
        feats: list[str] = list(tokens)
        # Bigramas de palabra: capturan expresiones como "tasa aplicable".
        feats += [tokens[i] + "_" + tokens[i + 1] for i in range(len(tokens) - 1)]
        # Trigramas de caracter: tolerancia a variantes morfologicas.
        compact = " ".join(tokens)
        feats += [compact[i : i + 3] for i in range(max(0, len(compact) - 2))]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            feats = self._features(text)
            if not feats:
                continue
            counts: dict[int, float] = {}
            for f in feats:
                h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "big") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                counts[idx] = counts.get(idx, 0.0) + sign
            for idx, val in counts.items():
                # Amortigua features muy frecuentes (efecto tipo sublinear TF).
                out[row, idx] = math.copysign(math.log1p(abs(val)), val)
        return _normalize(out)


class NvidiaEmbedder(Embedder):
    """Embeddings reales via endpoint OpenAI-compatible de NVIDIA NIM."""

    def __init__(self, api_key: str, base_url: str, model: str, dim: int = 1024) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        import httpx

        resp = httpx.post(
            self.base_url + "/embeddings",
            headers={"Authorization": "Bearer " + self.api_key},
            json={
                "input": texts,
                "model": self.model,
                "input_type": "passage",
                "encoding_format": "float",
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        vectors = np.array([d["embedding"] for d in data], dtype=np.float32)
        self.dim = vectors.shape[1]
        return _normalize(vectors)


def build_embedder(settings=None) -> Embedder:
    from app.core.config import get_settings

    s = settings or get_settings()
    if s.embedding_provider == "nvidia" and s.llm_api_key:
        return NvidiaEmbedder(s.llm_api_key, s.llm_base_url, s.embedding_model)
    return HashingEmbedder()
