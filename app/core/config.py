"""Configuracion central. Toda la app lee de aqui; nada hardcodea proveedores."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["mock", "nvidia", "openai", "azure", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Proveedor de LLM -------------------------------------------------
    # "mock" permite ejecutar la demo completa sin credenciales.
    llm_provider: Provider = Field(default="mock")
    llm_model: str = Field(default="nvidia/llama-3.1-nemotron-70b-instruct")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://integrate.api.nvidia.com/v1")
    llm_temperature: float = Field(default=0.0)
    llm_timeout_s: float = Field(default=30.0)
    llm_max_retries: int = Field(default=1)

    # Azure usa un esquema de URL distinto al resto.
    azure_api_version: str = Field(default="2024-10-21")

    # --- Agente -----------------------------------------------------------
    agent_max_iterations: int = Field(default=6)
    agent_deadline_s: float = Field(default=90.0)

    # --- Datos ------------------------------------------------------------
    erp_db_path: str = Field(default="app/data/erp_mock.sqlite3")
    audit_db_path: str = Field(default="app/data/audit.sqlite3")
    vector_index_path: str = Field(default="app/data/chroma")
    policy_pdf_path: str = Field(default="app/data/normativa_sintetica.pdf")

    # --- RAG --------------------------------------------------------------
    embedding_provider: Literal["hashing", "nvidia"] = Field(default="hashing")
    embedding_model: str = Field(default="nvidia/nv-embedqa-e5-v5")
    rag_top_k: int = Field(default=4)
    rag_chunk_chars: int = Field(default=900)
    rag_chunk_overlap: int = Field(default=150)

    # --- Simulacion de fallos (para demostrar manejo de errores) ----------
    erp_fail_rate: float = Field(default=0.0)
    erp_latency_ms: int = Field(default=0)

    @property
    def llm_is_mock(self) -> bool:
        return self.llm_provider == "mock" or not self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
