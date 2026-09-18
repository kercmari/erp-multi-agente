"""LLM simulado y determinista.

No es una respuesta pregrabada: interpreta el estado real de la conversacion,
decide que herramienta pedir y redacta la respuesta con los datos que las
herramientas devolvieron. Permite reproducir la demo sin credenciales y hace
que los tests sean deterministas.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import LLMClient, LLMResponse, ToolSpec

ORDER_RE = re.compile(r"#?\s*(\d{3,10})")


def _find_order_id(messages: list[dict[str, Any]]) -> str | None:
    for m in messages:
        if m.get("role") != "user":
            continue
        found = ORDER_RE.search(str(m.get("content") or ""))
        if found:
            return found.group(1)
    return None


def _tool_outputs(messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recoge los resultados de herramienta ya presentes en la conversacion."""
    out: dict[str, dict[str, Any]] = {}
    for m in messages:
        if m.get("role") != "tool":
            continue
        name = m.get("name") or ""
        try:
            out[name] = json.loads(m.get("content") or "{}")
        except json.JSONDecodeError:
            out[name] = {}
    return out


class MockLLMClient(LLMClient):
    """Emula el ciclo ReAct: observa, decide herramienta, concluye."""

    provider_name = "mock"

    def __init__(self, token_delay_s: float = 0.012) -> None:
        self._delay = token_delay_s

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        names = {t.name for t in (tools or [])}
        done = _tool_outputs(messages)
        order_id = _find_order_id(messages)

        # Paso 1: sin datos del ERP todavia -> pedirlos.
        if "get_erp_data" in names and "get_erp_data" not in done and order_id:
            return LLMResponse(
                tool_calls=[
                    {
                        "id": "call_erp_1",
                        "name": "get_erp_data",
                        "arguments": {"order_id": order_id},
                    }
                ],
                finish_reason="tool_calls",
            )

        erp = done.get("get_erp_data") or {}

        # Paso 2: con datos del ERP y sin calculo -> encadenar el calculo.
        # El argumento sale del resultado del ERP: encadenamiento real.
        if (
            "calculate_tax_discrepancy" in names
            and "calculate_tax_discrepancy" not in done
            and erp.get("invoice_amount") is not None
        ):
            return LLMResponse(
                tool_calls=[
                    {
                        "id": "call_tax_1",
                        "name": "calculate_tax_discrepancy",
                        "arguments": {
                            "amount": float(erp["invoice_amount"]),
                            "region": erp.get("region", "US-CA"),
                            "recorded_total": (
                                float(erp["erp_amount"])
                                if erp.get("erp_amount") is not None
                                else None
                            ),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

        # Paso 3: buscar normativa que respalde la conclusion.
        if "search_policy" in names and "search_policy" not in done:
            region = erp.get("region", "US-CA")
            return LLMResponse(
                tool_calls=[
                    {
                        "id": "call_rag_1",
                        "name": "search_policy",
                        "arguments": {
                            "query": f"tolerancia y tasa impositiva {region} conciliacion",
                            "year": 2024,
                            "region": region,
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

        return LLMResponse(text=self._compose(done, order_id), finish_reason="stop")

    def _compose(self, done: dict[str, dict[str, Any]], order_id: str | None) -> str:
        """Redacta la respuesta usando SOLO datos observados."""
        erp = done.get("get_erp_data") or {}
        tax = done.get("calculate_tax_discrepancy") or {}
        pol = done.get("search_policy") or {}

        if not erp:
            return (
                "No pude recuperar datos del ERP para esa consulta, por lo que no "
                "puedo concluir. Verifica el numero de orden o reintenta cuando el "
                "sistema este disponible."
            )

        parts: list[str] = []
        oid = erp.get("order_id", order_id or "desconocido")
        parts.append(f"Analisis de la orden #{oid} (region {erp.get('region','n/d')}).")
        parts.append(
            f"La factura registra {erp.get('invoice_amount')} {erp.get('currency','USD')} "
            f"y el ERP tiene {erp.get('erp_amount')} {erp.get('currency','USD')}."
        )
        if tax:
            parts.append(
                f"Aplicando la tasa {tax.get('tax_rate')} de la regla "
                f"{tax.get('rule_id','n/d')}, el total esperado es "
                f"{tax.get('expected_total')}."
            )
            disc = tax.get("discrepancy")
            if disc is not None:
                if tax.get("within_tolerance"):
                    parts.append(
                        f"La diferencia de {disc} queda dentro de la tolerancia "
                        f"de {tax.get('tolerance')}, por lo que se considera redondeo."
                    )
                else:
                    parts.append(
                        f"La diferencia de {disc} excede la tolerancia de "
                        f"{tax.get('tolerance')}, lo que explica la discrepancia."
                    )
        if pol.get("results"):
            first = pol["results"][0]
            parts.append(
                f"Fundamento normativo: {first.get('source')} pagina "
                f"{first.get('page')} (ano {first.get('year')})."
            )
        else:
            parts.append(
                "No se hallo normativa vigente aplicable, por lo que la conclusion "
                "queda sujeta a revision humana."
            )
        return " ".join(parts)

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        """Emite el texto por fragmentos, imitando tokens reales."""
        resp = await self.complete(messages, tools)
        for piece in re.findall(r"\S+\s*", resp.text):
            await asyncio.sleep(self._delay)
            yield piece
