"""Herramienta calculate_tax_discrepancy: logica de negocio en Python puro.

Supuestos de negocio documentados:
  - `amount` = base imponible de la factura de logistica, sin impuesto.
  - Las tasas son SINTETICAS e inventadas para la demo. No son tasas reales
    de ninguna jurisdiccion y asi se declara en la respuesta y en el README.
  - Todo el calculo monetario usa Decimal con redondeo ROUND_HALF_UP
    explicito. Nunca float: 0.1 + 0.2 != 0.3 en binario y en finanzas eso
    genera descuadres.
  - Las reglas estan versionadas por ano para que el filtro de metadata del
    RAG (ej. 2024) y el calculo hablen del mismo periodo.
"""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.core.models import TaxDiscrepancy, ToolResult

CENTS = Decimal("0.01")

# Tabla sintetica: region -> ano -> (tasa, id de regla, tolerancia)
TAX_RULES: dict[str, dict[int, tuple[Decimal, str, Decimal]]] = {
    "US-CA": {
        2023: (Decimal("0.0725"), "CA-LOG-2023", Decimal("0.01")),
        2024: (Decimal("0.0875"), "CA-LOG-2024", Decimal("0.01")),
    },
    "US-TX": {
        2023: (Decimal("0.0625"), "TX-LOG-2023", Decimal("0.01")),
        2024: (Decimal("0.0625"), "TX-LOG-2024", Decimal("0.01")),
    },
    "MX-CMX": {
        2023: (Decimal("0.1600"), "MX-LOG-2023", Decimal("0.02")),
        2024: (Decimal("0.1600"), "MX-LOG-2024", Decimal("0.02")),
    },
    "EU-ES": {
        2023: (Decimal("0.2100"), "ES-LOG-2023", Decimal("0.02")),
        2024: (Decimal("0.2100"), "ES-LOG-2024", Decimal("0.02")),
    },
}

DEFAULT_YEAR = 2024


def _money(value: Any) -> Decimal:
    """Convierte a Decimal pasando por str: evita heredar ruido del float."""
    return Decimal(str(value))


def calculate_tax_discrepancy(
    amount: float | str | Decimal,
    region: str,
    recorded_total: float | str | Decimal | None = None,
    year: int = DEFAULT_YEAR,
) -> ToolResult:
    """Calcula el impuesto esperado y lo contrasta con el total registrado."""
    started = time.perf_counter()

    def _fail(code: str, detail: str) -> ToolResult:
        return ToolResult(
            name="calculate_tax_discrepancy", ok=False, error_code=code,
            content={"detail": detail},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        base = _money(amount)
    except (InvalidOperation, TypeError, ValueError):
        return _fail("invalid_argument", "amount no es un numero valido")

    if base < 0:
        return _fail("invalid_argument", "amount no puede ser negativo")
    if base > Decimal("100000000"):
        return _fail("invalid_argument", "amount fuera de rango admitido")

    region_key = str(region or "").strip().upper()
    if region_key not in TAX_RULES:
        return _fail(
            "unsupported_region",
            f"Region '{region}' sin regla sintetica. Soportadas: "
            f"{', '.join(sorted(TAX_RULES))}",
        )

    by_year = TAX_RULES[region_key]
    if year not in by_year:
        return _fail(
            "unsupported_year",
            f"No hay regla para {region_key} en {year}. "
            f"Anos disponibles: {sorted(by_year)}",
        )

    rate, rule_id, tolerance = by_year[year]

    expected_tax = (base * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
    expected_total = (base + expected_tax).quantize(CENTS, rounding=ROUND_HALF_UP)

    recorded: Decimal | None = None
    discrepancy: Decimal | None = None
    within: bool | None = None
    if recorded_total is not None:
        try:
            recorded = _money(recorded_total).quantize(CENTS, rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return _fail("invalid_argument", "recorded_total no es un numero valido")
        discrepancy = (recorded - expected_total).quantize(CENTS, rounding=ROUND_HALF_UP)
        within = abs(discrepancy) <= tolerance

    result = TaxDiscrepancy(
        amount=base.quantize(CENTS, rounding=ROUND_HALF_UP),
        region=region_key, tax_rate=rate, expected_tax=expected_tax,
        expected_total=expected_total, recorded_total=recorded,
        discrepancy=discrepancy, within_tolerance=within,
        tolerance=tolerance, rule_id=rule_id, rule_year=year,
    )
    payload = {k: (str(v) if isinstance(v, Decimal) else v)
               for k, v in result.model_dump().items()}
    payload["disclaimer"] = "Tasas sinteticas de demostracion, no reales."
    return ToolResult(
        name="calculate_tax_discrepancy", ok=True, content=payload,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
