"""Construye el indice vectorial a partir del PDF normativo sintetico."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.rag.embeddings import build_embedder  # noqa: E402
from app.rag.index import VectorIndex  # noqa: E402
from app.rag.ingest import build_chunks  # noqa: E402


def main() -> None:
    s = get_settings()
    print("Leyendo PDF: " + s.policy_pdf_path)
    chunks = build_chunks(s.policy_pdf_path, s.rag_chunk_chars, s.rag_chunk_overlap)
    print("Fragmentos generados: " + str(len(chunks)))

    embedder = build_embedder(s)
    print("Embedder: " + type(embedder).__name__)

    index = VectorIndex(embedder)
    index.add(chunks)
    index.save(s.vector_index_path)

    st = index.stats()
    print("\n[ok] Indice guardado en " + s.vector_index_path)
    print("  fragmentos : " + str(st["chunks"]))
    print("  dimension  : " + str(st["dim"]))
    print("  por ano    : " + str(st["by_year"]))
    print("  por region : " + str(st["by_region"]))
    print("\nEl indice contiene 2023 y 2024: eso permite demostrar el filtro.")


if __name__ == "__main__":
    main()
