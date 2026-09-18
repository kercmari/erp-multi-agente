"""Configuracion comun de las pruebas.

Aisla la suite del archivo .env local: los tests SIEMPRE usan el LLM simulado,
sin importar que proveedor tenga configurado quien las ejecuta.

Por que importa: si los tests leyeran el .env, su resultado dependeria de tener
credenciales validas, de la red y del comportamiento no determinista de un
modelo real. Una suite de pruebas debe dar el mismo resultado en cualquier
maquina, sin credenciales y sin conexion.

La verificacion del LLM real se hace aparte, con scripts/verificar_llm.py.
"""
from __future__ import annotations

import os

import pytest

# Debe aplicarse ANTES de que cualquier modulo lea la configuracion.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["ERP_FAIL_RATE"] = "0.0"
os.environ["ERP_LATENCY_MS"] = "0"


@pytest.fixture(autouse=True, scope="session")
def _forzar_modo_mock():
    """Garantiza el modo mock durante toda la sesion de pruebas."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.llm_is_mock, (
        "Las pruebas deben ejecutarse con el LLM simulado. "
        "Proveedor detectado: " + s.llm_provider
    )
    yield
    get_settings.cache_clear()
