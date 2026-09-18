"""Adaptador OpenAI-compatible: NVIDIA NIM, OpenAI y Azure OpenAI.

Los tres hablan el mismo dialecto de /chat/completions, asi que un solo
adaptador cubre los tres cambiando base_url y cabeceras.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.base import LLMClient, LLMError, LLMResponse, LLMTimeout, ToolSpec


class OpenAICompatClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider_name = settings.llm_provider
        self._model = settings.llm_model

    # --- construccion de la peticion -------------------------------------
    def _url(self) -> str:
        base = self.settings.llm_base_url.rstrip("/")
        if self.settings.llm_provider == "azure":
            # Azure enruta por deployment y exige api-version.
            return (
                f"{base}/openai/deployments/{self._model}/chat/completions"
                f"?api-version={self.settings.azure_api_version}"
            )
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        if self.settings.llm_provider == "azure":
            return {"api-key": self.settings.llm_api_key}
        return {"Authorization": f"Bearer {self.settings.llm_api_key}"}

    def _payload(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None, stream: bool
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "stream": stream,
        }
        if self.settings.llm_provider != "azure":
            body["model"] = self._model
        if tools:
            body["tools"] = [t.to_openai() for t in tools]
            body["tool_choice"] = "auto"
        return body

    # --- no streaming -----------------------------------------------------
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as c:
                r = await c.post(
                    self._url(),
                    headers=self._headers(),
                    json=self._payload(messages, tools, stream=False),
                )
        except httpx.TimeoutException as e:
            raise LLMTimeout() from e
        except httpx.HTTPError as e:
            raise LLMError(f"Fallo de red hacia el proveedor: {type(e).__name__}") from e

        if r.status_code == 429:
            raise LLMError("Limite de tasa del proveedor", code="llm_rate_limited")
        if r.status_code in (401, 403):
            raise LLMError("Credenciales invalidas", code="llm_unauthorized")
        if r.status_code >= 500:
            raise LLMError("Error del proveedor", code="llm_upstream_error")
        if r.status_code >= 400:
            raise LLMError(f"Peticion rechazada ({r.status_code})", code="llm_bad_request")

        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": args})
        return LLMResponse(
            text=msg.get("content") or "",
            tool_calls=calls,
            finish_reason=choice.get("finish_reason", "stop"),
        )

    # --- streaming real de tokens ----------------------------------------
    async def stream(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, tools, stream=True)
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as c:
                async with c.stream(
                    "POST", self._url(), headers=self._headers(), json=payload
                ) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        raise LLMError(
                            f"Proveedor rechazo el stream ({r.status_code})",
                            code="llm_stream_rejected",
                        )
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        chunk = line[6:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            obj = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        delta = ((obj.get("choices") or [{}])[0]).get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            yield piece
        except httpx.TimeoutException as e:
            raise LLMTimeout() from e
        except httpx.HTTPError as e:
            raise LLMError(f"Fallo de red en streaming: {type(e).__name__}") from e
