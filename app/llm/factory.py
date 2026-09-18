"""Seleccion de proveedor en un solo punto. El resto de la app no lo conoce."""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.llm.base import LLMClient


def build_llm(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()

    # Sin credenciales caemos al mock: la demo siempre es reproducible.
    if s.llm_is_mock:
        from app.llm.mock import MockLLMClient

        return MockLLMClient()

    if s.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicClient

        return AnthropicClient(s)

    # nvidia | openai | azure comparten dialecto OpenAI.
    from app.llm.openai_compat import OpenAICompatClient

    return OpenAICompatClient(s)
