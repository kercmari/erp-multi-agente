"""Pruebas del RAG: filtrado de metadata y ausencia de evidencia."""
from __future__ import annotations

import pytest

from app.rag.embeddings import HashingEmbedder
from app.rag.index import Chunk, VectorIndex
from app.rag.ingest import chunk_text, infer_region, infer_year
from app.tools.policy import search_policy


@pytest.fixture
def indice():
    idx = VectorIndex(HashingEmbedder(dim=256))
    idx.add(
        [
            Chunk("a", "La tasa de logistica en US-CA es 7.25 por ciento", "man.pdf", 1, 2023, "US-CA"),
            Chunk("b", "La tasa de logistica en US-CA es 8.75 por ciento", "man.pdf", 2, 2024, "US-CA"),
            Chunk("c", "La tasa de logistica en MX-CMX es 16.00 por ciento", "man.pdf", 3, 2024, "MX-CMX"),
        ]
    )
    return idx


def test_filtro_por_ano_excluye_otros_anos(indice):
    hits = indice.search("tasa de logistica", year=2024)
    assert hits
    assert all(h.chunk.year == 2024 for h in hits)


def test_filtro_2023_devuelve_solo_2023(indice):
    hits = indice.search("tasa de logistica", year=2023)
    assert len(hits) == 1
    assert hits[0].chunk.year == 2023


def test_sin_filtro_mezcla_anos(indice):
    """Justifica el filtro: sin el, entra contenido derogado."""
    anos = {h.chunk.year for h in indice.search("tasa de logistica")}
    assert anos == {2023, 2024}


def test_filtro_por_region(indice):
    hits = indice.search("tasa", year=2024, region="MX-CMX")
    assert all(h.chunk.region == "MX-CMX" for h in hits)


def test_ano_sin_documentos_devuelve_vacio(indice):
    assert indice.search("tasa", year=2019) == []


def test_prefiltrado_garantiza_k_validos(indice):
    """Pre-filtrado: los k devueltos SIEMPRE cumplen el filtro."""
    hits = indice.search("cualquier cosa", top_k=10, year=2024)
    assert hits and all(h.chunk.year == 2024 for h in hits)


def test_troceado_respeta_tamano():
    texto = "Frase de prueba. " * 200
    trozos = chunk_text(texto, max_chars=300, overlap=50)
    assert len(trozos) > 1
    assert all(len(t) <= 320 for t in trozos)


def test_troceado_texto_corto_no_divide():
    assert len(chunk_text("Texto breve.", max_chars=900)) == 1


def test_inferencia_de_metadata():
    assert infer_year("Para el ejercicio 2023 la tasa es") == 2023
    assert infer_year("Edicion 2024 del manual") == 2024
    assert infer_region("La region US-CA aplica") == "US-CA"
    assert infer_region("Sin region mencionada") is None


def test_herramienta_sin_evidencia_lo_declara():
    """Requisito: si no hay evidencia, se dice; no se inventa."""
    r = search_policy("tasa aplicable", year=1999)
    assert r.ok
    assert r.content["results"] == []
    assert "No hay normativa" in r.content["note"]


def test_herramienta_devuelve_referencia_de_origen():
    r = search_policy("tasa impositiva US-CA", year=2024, region="US-CA")
    assert r.ok and r.content["results"]
    primero = r.content["results"][0]
    assert primero["source"] and primero["page"] and primero["year"] == 2024


def test_herramienta_valida_argumentos():
    assert not search_policy("", year=2024).ok
    assert not search_policy("consulta", year=1700).ok
