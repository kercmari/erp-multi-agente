"""Interfaz de LLM independiente del proveedor (criterio: model-agnostic).

La logica de negocio depende SOLO de esta interfaz. Cambiar de NVIDIA a Azure
OpenAI o Anthropic no toca ni una linea de los agentes.
"""
from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    """Fallo del proveedor: timeout, rate limit, credenciales, 5xx."""

    def __init__(self, message: str, *, code: str = "llm_error") -> None:
        super().__init__(message)
        self.code = code


class LLMTimeout(LLMError):
    def __init__(self, message: str = "El modelo no respondio a tiempo") -> None:
        super().__init__(message, code="llm_timeout")


@dataclass
class ToolSpec:
    """Definicion de herramienta expuesta al modelo (JSON Schema)."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class LLMResponse:
    """Respuesta no-streaming: texto y/o peticiones de herramienta."""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"


class LLMClient(abc.ABC):
    """Contrato minimo que debe cumplir cualquier proveedor."""

    provider_name: str = "base"

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        """Una pasada de razonamiento; puede pedir herramientas."""

    @abc.abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming de tokens reales de generacion."""
