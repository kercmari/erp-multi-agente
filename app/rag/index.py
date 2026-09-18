"""Indice vectorial con filtrado de metadata.

Decision de diseno: el filtro por metadata se aplica ANTES del calculo de
similitud (pre-filtrado), no despues. Esto importa:

  - Post-filtrado (buscar top-k global y luego descartar) puede devolver cero
    resultados utiles si los k mejores eran todos del ano equivocado.
  - Pre-filtrado garantiza que los k devueltos cumplen SIEMPRE el filtro.

Filtrar por ano evita que normativa derogada contamine la recuperacion:
dos ediciones del mismo manual son casi identicas semanticamente, y solo
el metadato las distingue.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.rag.embeddings import Embedder


@dataclass
class Chunk:
    """Fragmento indexado con su metadata de procedencia."""

    chunk_id: str
    text: str
    source: str
    page: int
    year: int
    region: str | None = None
    doc_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source": self.source,
            "page": self.page,
            "year": self.year,
            "region": self.region,
            "doc_id": self.doc_id,
            "extra": self.extra,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Chunk":
        return Chunk(
            chunk_id=d["chunk_id"], text=d["text"], source=d["source"],
            page=d["page"], year=d["year"], region=d.get("region"),
            doc_id=d.get("doc_id"), extra=d.get("extra") or {},
        )


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class VectorIndex:
    """Indice denso en memoria, persistido en disco (vectores .npy + meta .json)."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    # --- construccion -----------------------------------------------------
    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vecs = self.embedder.embed([c.text for c in chunks])
        self.chunks.extend(chunks)
        self.vectors = vecs if self.vectors is None else np.vstack([self.vectors, vecs])

    def save(self, directory: str | Path) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        if self.vectors is None:
            raise ValueError("No hay vectores que guardar")
        np.save(d / "vectors.npy", self.vectors)
        (d / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in self.chunks], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path, embedder: Embedder) -> "VectorIndex":
        d = Path(directory)
        vec_path, meta_path = d / "vectors.npy", d / "chunks.json"
        if not vec_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                "Indice no encontrado en " + str(d) + ". Ejecuta scripts/build_index.py"
            )
        idx = cls(embedder)
        idx.vectors = np.load(vec_path)
        idx.chunks = [
            Chunk.from_dict(c) for c in json.loads(meta_path.read_text(encoding="utf-8"))
        ]
        return idx

    # --- recuperacion -----------------------------------------------------
    def _candidate_ids(
        self,
        year: int | None,
        region: str | None,
        source: str | None,
        year_max: int | None,
    ) -> list[int]:
        """Pre-filtrado por metadata: decide QUE se puede recuperar."""
        ids: list[int] = []
        for i, c in enumerate(self.chunks):
            if year is not None and c.year != year:
                continue
            if year_max is not None and c.year > year_max:
                continue
            if region is not None and c.region is not None and c.region != region:
                continue
            if source is not None and c.source != source:
                continue
            ids.append(i)
        return ids

    def search(
        self,
        query: str,
        top_k: int = 4,
        year: int | None = None,
        region: str | None = None,
        source: str | None = None,
        year_max: int | None = None,
        min_score: float = 0.0,
    ) -> list[SearchHit]:
        if self.vectors is None or not self.chunks:
            return []

        candidates = self._candidate_ids(year, region, source, year_max)
        if not candidates:
            return []  # sin evidencia aplicable: el agente debe decirlo.

        qvec = self.embedder.embed([query])[0]
        sub = self.vectors[candidates]
        sims = sub @ qvec  # vectores normalizados -> producto punto = coseno

        order = np.argsort(-sims)[:top_k]
        hits = []
        for pos in order:
            score = float(sims[pos])
            if score < min_score:
                continue
            hits.append(SearchHit(chunk=self.chunks[candidates[pos]], score=score))
        return hits

    def stats(self) -> dict[str, Any]:
        years: dict[int, int] = {}
        regions: dict[str, int] = {}
        for c in self.chunks:
            years[c.year] = years.get(c.year, 0) + 1
            if c.region:
                regions[c.region] = regions.get(c.region, 0) + 1
        return {
            "chunks": len(self.chunks),
            "dim": int(self.vectors.shape[1]) if self.vectors is not None else 0,
            "by_year": dict(sorted(years.items())),
            "by_region": dict(sorted(regions.items())),
        }
