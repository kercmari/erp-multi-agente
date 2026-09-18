"""Registro de herramientas: esquemas para el LLM y despachador de ejecucion.

Desacopla "que sabe el modelo que existe" de "como se ejecuta realmente".
El modelo solo ve nombres y JSON Schema; jamas recibe acceso directo a la base.
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.models import Identity, ToolResult
from app.llm.base import ToolSpec
from app.security.guardrails import Verdict, authorize_tool

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_erp_data",
        description=(
            "Consulta los datos de una orden en el ERP (SQL Server simulado). "
            "Devuelve importe de factura, importe registrado en ERP, region, "
            "moneda y estado. Usala SIEMPRE antes de calcular nada."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Identificador numerico de la orden, ej '4402'",
                }
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="calculate_tax_discrepancy",
        description=(
            "Calcula el impuesto esperado sobre una base imponible y lo compara "
            "con el total registrado en el ERP. Devuelve la discrepancia y si "
            "queda dentro de la tolerancia. Usa las reglas sinteticas vigentes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Base imponible (importe de factura sin impuesto)",
                },
                "region": {
                    "type": "string",
                    "description": "Region fiscal: US-CA, US-TX, MX-CMX o EU-ES",
                },
                "recorded_total": {
                    "type": ["number", "null"],
                    "description": "Total registrado en el ERP, para contrastar",
                },
                "year": {
                    "type": "integer",
                    "description": "Ejercicio fiscal aplicable. Por defecto 2024",
                },
            },
            "required": ["amount", "region"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="search_policy",
        description=(
            "Busca normativa aplicable en el manual PDF mediante busqueda "
            "vectorial con filtros de metadata. Filtra por ano para excluir "
            "ediciones derogadas. Devuelve el fragmento y su pagina de origen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Que se busca en la normativa"},
                "year": {
                    "type": "integer",
                    "description": "Ejercicio a consultar, ej 2024. Excluye otros anos.",
                },
                "region": {
                    "type": "string",
                    "description": "Region para acotar la normativa",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
]


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    identity: Identity,
    settings: Settings,
) -> ToolResult:
    """Ejecuta una herramienta tras autorizarla. Punto unico de control."""
    auth = authorize_tool(name, identity)
    if auth.verdict is not Verdict.ALLOW:
        return ToolResult(
            name=name, ok=False, error_code="forbidden",
            content={"detail": auth.user_message or auth.reason},
        )

    if name == "get_erp_data":
        from app.tools.erp import get_erp_data

        return await get_erp_data(
            order_id=str(arguments.get("order_id", "")),
            identity=identity,
            settings=settings,
        )

    if name == "calculate_tax_discrepancy":
        from app.tools.tax import calculate_tax_discrepancy

        return calculate_tax_discrepancy(
            amount=arguments.get("amount", 0),
            region=str(arguments.get("region", "")),
            recorded_total=arguments.get("recorded_total"),
            year=int(arguments.get("year", 2024) or 2024),
        )

    if name == "search_policy":
        from app.tools.policy import search_policy

        return search_policy(
            query=str(arguments.get("query", "")),
            year=arguments.get("year"),
            region=arguments.get("region"),
            settings=settings,
        )

    return ToolResult(
        name=name, ok=False, error_code="unknown_tool",
        content={"detail": "La herramienta '" + name + "' no existe"},
    )
