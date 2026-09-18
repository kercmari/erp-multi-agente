"""Pruebas del calculo fiscal: exactitud monetaria y validacion."""
from __future__ import annotations

from decimal import Decimal

from app.tools.tax import calculate_tax_discrepancy


def test_calculo_correcto_us_ca_2024():
    r = calculate_tax_discrepancy(amount="12500.00", region="US-CA", year=2024)
    assert r.ok
    assert r.content["tax_rate"] == "0.0875"
    assert r.content["expected_tax"] == "1093.75"
    assert r.content["expected_total"] == "13593.75"
    assert r.content["rule_id"] == "CA-LOG-2024"


def test_regla_cambia_con_el_ano():
    """La misma base con distinto ejercicio da distinto resultado."""
    r23 = calculate_tax_discrepancy(amount="12500.00", region="US-CA", year=2023)
    r24 = calculate_tax_discrepancy(amount="12500.00", region="US-CA", year=2024)
    assert r23.content["expected_total"] == "13406.25"  # tasa derogada 7.25%
    assert r24.content["expected_total"] == "13593.75"  # tasa vigente 8.75%
    assert r23.content["expected_total"] != r24.content["expected_total"]


def test_discrepancia_detectada_caso_4402():
    """El ERP aplico la tasa derogada de 2023 a una orden de 2024."""
    r = calculate_tax_discrepancy(
        amount="12500.00", region="US-CA", recorded_total="13406.25", year=2024
    )
    assert r.ok
    assert r.content["discrepancy"] == "-187.50"
    assert r.content["within_tolerance"] is False


def test_diferencia_de_un_centavo_dentro_de_tolerancia():
    r = calculate_tax_discrepancy(
        amount="8750.40", region="US-CA", recorded_total="9516.07", year=2024
    )
    assert r.content["discrepancy"] == "0.01"
    assert r.content["within_tolerance"] is True


def test_precision_decimal_sin_error_de_float():
    """Con float, 0.1+0.2 != 0.3. Con Decimal el importe es exacto."""
    r = calculate_tax_discrepancy(amount="0.10", region="US-TX", year=2024)
    assert r.ok
    esperado = (Decimal("0.10") * Decimal("0.0625")).quantize(Decimal("0.01"))
    assert Decimal(r.content["expected_tax"]) == esperado


def test_redondeo_half_up_explicito():
    """5000.00 * 0.0625 = 312.50 exacto; se verifica el quantize."""
    r = calculate_tax_discrepancy(amount="5000.00", region="US-TX", year=2024)
    assert r.content["expected_tax"] == "312.50"
    assert r.content["expected_total"] == "5312.50"


def test_rechaza_monto_negativo():
    r = calculate_tax_discrepancy(amount=-100, region="US-CA")
    assert not r.ok and r.error_code == "invalid_argument"


def test_rechaza_region_no_soportada():
    r = calculate_tax_discrepancy(amount=100, region="XX-YY")
    assert not r.ok and r.error_code == "unsupported_region"


def test_rechaza_ano_sin_regla():
    r = calculate_tax_discrepancy(amount=100, region="US-CA", year=2019)
    assert not r.ok and r.error_code == "unsupported_year"


def test_rechaza_monto_no_numerico():
    r = calculate_tax_discrepancy(amount="no-es-numero", region="US-CA")
    assert not r.ok and r.error_code == "invalid_argument"


def test_declara_que_las_tasas_son_sinteticas():
    r = calculate_tax_discrepancy(amount="100.00", region="US-CA")
    assert "sintetic" in r.content["disclaimer"].lower()
