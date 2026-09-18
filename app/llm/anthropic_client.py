"""Adaptador Anthropic (Claude). Dialecto distinto: tool_use y content blocks."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.base import LLMClient, LLMError, LLMResponse, LLMTimeout, ToolSpec


class AnthropicClient(LLMClient):
    provider_name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._url = "https://api.anthropic.com/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.settings.llm_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _split(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Anthropic lleva el system fuera del array de mensajes."""
        system = ""
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                system += str(m.get("content") or "") + "\n"
            elif m.get("role") == "tool":
                rest.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id") or "",
                                "content": str(m.get("content") or ""),
                            }
                        ],
                    }
                )
            else:
                rest.append({"role": m["role"], "content": m.get("content") or ""})
        return system.strip(), rest

    def _payload(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None, stream: bool
    ) -> dict[str, Any]:
        system, msgs = self._split(messages)
        body: dict[str, Any] = {
            "model": self.settings.llm_model,
            "max_tokens": 1500,
            "temperature": self.settings.llm_temperature,
            "messages": msgs,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [t.to_anthropic() for t in tools]
        return body

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as c:
                r = await c.post(
                    self._url, headers=self._headers(),
                    json=self._payload(messages, tools, stream=False),
                )
        except httpx.TimeoutException as e:
            raise LLMTimeout() from e
        except httpx.HTTPError as e:
            raise LLMError(f"Fallo de red: {type(e).__name__}") from e

        if r.status_code == 429:
            raise LLMError("Limite de tasa", code="llm_rate_limited")
        if r.status_code in (401, 403):
            raise LLMError("Credenciales invalidas", code="llm_unauthorized")
        if r.status_code >= 400:
            raise LLMError(f"Peticion rechazada ({r.status_code})", code="llm_bad_request")

        data = r.json()
        text, calls = "", []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                calls.append(
                    {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input") or {},
                    }
                )
        return LLMResponse(
            text=text, tool_calls=calls, finish_reason=data.get("stop_reason", "stop")
        )

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as c:
                async with c.stream(
                    "POST", self._url, headers=self._headers(),
                    json=self._payload(messages, tools, stream=True),
                ) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        raise LLMError(
                            f"Stream rechazado ({r.status_code})", code="llm_stream_rejected"
                        )
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            obj = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        if obj.get("type") == "content_block_delta":
                            piece = (obj.get("delta") or {}).get("text")
                            if piece:
                                yield piece
        except httpx.TimeoutException as e:
            raise LLMTimeout() from e
        except httpx.HTTPError as e:
            raise LLMError(f"Fallo de red en streaming: {type(e).__name__}") from e
