"""Herramienta get_erp_data: simula la consulta a SQL Server sobre SQLite.

La consulta usa placeholders y nunca concatena la entrada del usuario ni
acepta SQL generado por el modelo. La sentencia objetivo contra SQL Server
esta documentada en el README.
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.models import Identity, ToolResult

# Consulta parametrizada. El ?/@ marca el unico punto de entrada de datos.
ERP_QUERY = """
SELECT order_id, invoice_amount, erp_amount, region, currency, status,
       issued_at, carrier
FROM orders
WHERE order_id = ?
"""

# Campos que el agente puede ver. Lista blanca: nada fuera de aqui sale.
ALLOWED_FIELDS = (
    "order_id", "invoice_amount", "erp_amount", "region",
    "currency", "status", "issued_at", "carrier",
)


class ERPUnavailable(RuntimeError):
    pass


def _connect(settings: Settings) -> sqlite3.Connection:
    path = Path(settings.erp_db_path)
    if not path.exists():
        raise ERPUnavailable(f"Base ERP simulada no encontrada en {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


async def get_erp_data(
    order_id: str, identity: Identity, settings: Settings | None = None
) -> ToolResult:
    """Recupera una orden del ERP simulado.

    Falla de forma controlada: nunca inventa datos si el sistema no responde.
    """
    s = settings or get_settings()
    started = time.perf_counter()

    # Validacion de argumento antes de tocar la base.
    oid = str(order_id or "").strip().lstrip("#")
    if not oid.isdigit() or not (3 <= len(oid) <= 10):
        return ToolResult(
            name="get_erp_data", ok=False, error_code="invalid_argument",
            content={"detail": "order_id debe ser numerico de 3 a 10 digitos"},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    # Simulacion opcional de latencia e indisponibilidad (demo de errores).
    if s.erp_latency_ms:
        await asyncio.sleep(s.erp_latency_ms / 1000)
    if s.erp_fail_rate and random.random() < s.erp_fail_rate:
        return ToolResult(
            name="get_erp_data", ok=False, error_code="erp_unavailable",
            content={"detail": "El ERP no respondio (simulado)"},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        conn = _connect(s)
    except ERPUnavailable as e:
        return ToolResult(
            name="get_erp_data", ok=False, error_code="erp_unavailable",
            content={"detail": str(e)},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        row = conn.execute(ERP_QUERY, (oid,)).fetchone()  # parametrizado
    except sqlite3.Error as e:
        return ToolResult(
            name="get_erp_data", ok=False, error_code="erp_query_failed",
            content={"detail": f"Error de consulta: {type(e).__name__}"},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        conn.close()

    if row is None:
        return ToolResult(
            name="get_erp_data", ok=False, error_code="not_found",
            content={"detail": f"No existe la orden {oid}"},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    data: dict[str, Any] = {k: row[k] for k in ALLOWED_FIELDS}

    # Autorizacion por region: el alcance del rol limita lo que puede leer.
    scope = identity.region_scope
    if scope and data["region"] not in scope:
        return ToolResult(
            name="get_erp_data", ok=False, error_code="forbidden_region",
            content={"detail": "La orden pertenece a una region fuera de tu alcance"},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    return ToolResult(
        name="get_erp_data", ok=True, content=data,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
