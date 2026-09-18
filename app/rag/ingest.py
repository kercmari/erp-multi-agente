"""Ingesta del PDF normativo: extraccion, troceado y metadata.

El ano y la region se derivan del propio texto de cada pagina. En un sistema
real vendrian del sistema documental; aqui se extraen con reglas explicitas y
se dejan trazables.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.rag.index import Chunk

YEAR_RE = re.compile(r"(?:ejercicio|edicion)\s+(20\d{2})", re.IGNORECASE)
REGION_RE = re.compile(r"\b(US-CA|US-TX|MX-CMX|EU-ES)\b", re.IGNORECASE)


def extract_pages(pdf_path: str | Path) -> list[tuple[int, str]]:
    """Devuelve [(numero_de_pagina, texto)] empezando en 1."""
    from pypdf import PdfReader

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(
            "PDF no encontrado en " + str(path) + ". Ejecuta scripts/seed_data.py"
        )
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((i, text))
    return pages


def chunk_text(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Trocea respetando limites de parrafo cuando es posible.

    El solapamiento evita que una frase relevante quede partida entre dos
    fragmentos y se pierda en la recuperacion.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Retrocede hasta el final de oracion mas cercano.
            window = text[start:end]
            cut = max(window.rfind(". "), window.rfind("; "))
            if cut > max_chars * 0.5:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def infer_year(text: str, default: int = 2024) -> int:
    m = YEAR_RE.search(text)
    return int(m.group(1)) if m else default


def infer_region(text: str) -> str | None:
    m = REGION_RE.search(text)
    return m.group(1).upper() if m else None


def build_chunks(
    pdf_path: str | Path, max_chars: int = 900, overlap: int = 150
) -> list[Chunk]:
    source = Path(pdf_path).name
    out: list[Chunk] = []
    for page_no, page_text in extract_pages(pdf_path):
        year = infer_year(page_text)
        region = infer_region(page_text)
        for j, piece in enumerate(chunk_text(page_text, max_chars, overlap)):
            out.append(
                Chunk(
                    chunk_id=source + ":p" + str(page_no) + ":c" + str(j),
                    text=piece,
                    source=source,
                    page=page_no,
                    year=year,
                    region=region,
                    doc_id=source + "-" + str(year),
                )
            )
    return out
