"""Genera los datos sinteticos: base ERP simulada y PDF de normativa.

Todo es inventado. No hay datos reales de ninguna empresa ni persona.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

ORDERS = [
    # order_id, invoice, erp, region, currency, status, issued_at, carrier
    # 4402: caso principal. Discrepancia real por aplicar la tasa de 2023 en 2024.
    ("4402", "12500.00", "13406.25", "US-CA", "USD", "open", "2024-03-11", "Zentrax"),
    # 4403: diferencia de 1 centavo -> dentro de tolerancia, es redondeo.
    ("4403", "8750.40", "9516.07", "US-CA", "USD", "open", "2024-04-02", "Zentrax"),
    # 4404: coincide exactamente con la regla 2024 de Texas.
    ("4404", "5000.00", "5312.50", "US-TX", "USD", "closed", "2024-02-20", "Rulmex"),
    # 4405: region mexicana, discrepancia grande que exige escalamiento.
    ("4405", "22000.00", "26500.00", "MX-CMX", "USD", "open", "2024-05-14", "Andigo"),
    # 4406: region europea, coincide con la regla 2024.
    ("4406", "9800.00", "11858.00", "EU-ES", "EUR", "open", "2024-06-01", "Ibercarga"),
    # 4407: orden de 2023, para contrastar vigencia de reglas.
    ("4407", "15000.00", "16087.50", "US-CA", "USD", "closed", "2023-09-09", "Zentrax"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id       TEXT PRIMARY KEY,
    invoice_amount TEXT NOT NULL,
    erp_amount     TEXT NOT NULL,
    region         TEXT NOT NULL,
    currency       TEXT NOT NULL DEFAULT 'USD',
    status         TEXT NOT NULL DEFAULT 'open',
    issued_at      TEXT,
    carrier        TEXT
);
-- Tabla restringida: existe para demostrar que la capa de seguridad impide
-- su lectura aunque el usuario lo pida. El agente no tiene herramienta a ella.
CREATE TABLE IF NOT EXISTS employee_salaries (
    employee_id TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    salary      TEXT NOT NULL,
    region      TEXT NOT NULL
);
"""

SALARIES = [
    ("E-001", "Persona Demo Uno", "98000.00", "US-CA"),
    ("E-002", "Persona Demo Dos", "76500.00", "US-TX"),
]


def seed_erp(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?)", ORDERS
        )
        conn.executemany(
            "INSERT OR REPLACE INTO employee_salaries VALUES (?,?,?,?)", SALARIES
        )
        conn.commit()
    finally:
        conn.close()
    print("[ok] ERP simulado: " + str(path) + " (" + str(len(ORDERS)) + " ordenes)")


def seed_audit(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS adjustments (
                adjustment_id TEXT PRIMARY KEY,
                order_id      TEXT NOT NULL,
                amount        TEXT NOT NULL,
                reason        TEXT,
                status        TEXT NOT NULL DEFAULT 'proposed',
                created_by    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                UNIQUE(order_id, amount, status)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, user_id TEXT, role TEXT,
                event      TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    print("[ok] Base de auditoria: " + str(path))


# Normativa sintetica. Incluye 2023 y 2024 con tasas DISTINTAS para US-CA:
# esa diferencia es la que hace demostrable el filtro por ano en el RAG.
POLICY_PAGES = [
    (
        "Manual de Conciliacion Logistica - Edicion 2023",
        2023,
        "US-CA",
        "Seccion 1. Alcance. Este manual sintetico regula la conciliacion entre "
        "facturas de logistica y el sistema ERP para el ejercicio 2023.\n\n"
        "Seccion 2. Tasa aplicable. Para la region US-CA durante el ejercicio 2023 "
        "la tasa impositiva sobre servicios de logistica es de 7.25 por ciento "
        "(regla CA-LOG-2023). Esta tasa quedo derogada el 31 de diciembre de 2023.\n\n"
        "Seccion 3. Tolerancia. Se admite una diferencia maxima de 0.01 unidades "
        "monetarias por redondeo. Toda diferencia superior debe documentarse.",
    ),
    (
        "Manual de Conciliacion Logistica - Edicion 2024",
        2024,
        "US-CA",
        "Seccion 1. Alcance. Este manual sintetico regula la conciliacion entre "
        "facturas de logistica y el sistema ERP para el ejercicio 2024 y sustituye "
        "integramente a la edicion 2023.\n\n"
        "Seccion 2. Tasa aplicable. Para la region US-CA durante el ejercicio 2024 "
        "la tasa impositiva sobre servicios de logistica es de 8.75 por ciento "
        "(regla CA-LOG-2024), vigente desde el 1 de enero de 2024.\n\n"
        "Seccion 3. Tolerancia. Se mantiene la tolerancia de 0.01 unidades "
        "monetarias por redondeo para US-CA.",
    ),
    (
        "Manual de Conciliacion Logistica - Edicion 2024",
        2024,
        "US-CA",
        "Seccion 4. Discrepancias. Cuando la diferencia entre el total esperado y "
        "el total registrado en el ERP supere la tolerancia, el analista debe "
        "generar un reporte con la evidencia documental que respalde la diferencia.\n\n"
        "Seccion 5. Asientos de ajuste. La creacion de un asiento de ajuste requiere "
        "aprobacion de un supervisor. Ningun proceso automatico puede confirmar un "
        "asiento sin intervencion humana registrada.\n\n"
        "Seccion 6. Causa frecuente. La aplicacion de una tasa derogada de un "
        "ejercicio anterior es la causa mas frecuente de discrepancia detectada.",
    ),
    (
        "Manual de Conciliacion Logistica - Edicion 2024",
        2024,
        "US-TX",
        "Seccion 11. Region US-TX. Para el ejercicio 2024 la tasa impositiva "
        "aplicable a servicios de logistica en US-TX es de 6.25 por ciento "
        "(regla TX-LOG-2024), sin variacion respecto al ejercicio anterior.\n\n"
        "Seccion 12. Tolerancia. Se admite una diferencia maxima de 0.01 unidades "
        "monetarias por redondeo en US-TX, igual que en US-CA.",
    ),
    (
        "Manual de Conciliacion Logistica - Edicion 2024",
        2024,
        "MX-CMX",
        "Seccion 7. Region MX-CMX. Para el ejercicio 2024 la tasa aplicable a "
        "servicios de logistica en MX-CMX es de 16.00 por ciento (regla MX-LOG-2024). "
        "La tolerancia admitida por redondeo es de 0.02 unidades monetarias.\n\n"
        "Seccion 8. Escalamiento. Diferencias superiores a 500 unidades monetarias "
        "en MX-CMX deben escalarse a revision humana antes de cualquier ajuste.",
    ),
    (
        "Manual de Conciliacion Logistica - Edicion 2024",
        2024,
        "EU-ES",
        "Seccion 9. Region EU-ES. Para el ejercicio 2024 la tasa aplicable es de "
        "21.00 por ciento (regla ES-LOG-2024), con tolerancia de 0.02 unidades.\n\n"
        "Seccion 10. Proteccion de datos. Los informes de conciliacion no deben "
        "incluir datos personales de empleados. La informacion retributiva esta "
        "fuera del alcance de este manual y de cualquier consulta de conciliacion.",
    ),
]


def seed_policy_pdf(path: Path) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, title="Normativa sintetica")
    styles = getSampleStyleSheet()
    flow = []
    for i, (title, year, region, body) in enumerate(POLICY_PAGES):
        flow.append(Paragraph(title, styles["Title"]))
        flow.append(
            Paragraph("Ejercicio " + str(year) + " | Region " + region, styles["Heading3"])
        )
        flow.append(Spacer(1, 10))
        for para in body.split("\n\n"):
            flow.append(Paragraph(para.replace("\n", " "), styles["BodyText"]))
            flow.append(Spacer(1, 6))
        if i < len(POLICY_PAGES) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    print("[ok] PDF normativo: " + str(path) + " (" + str(len(POLICY_PAGES)) + " paginas)")


def main() -> None:
    s = get_settings()
    seed_erp(Path(s.erp_db_path))
    seed_audit(Path(s.audit_db_path))
    seed_policy_pdf(Path(s.policy_pdf_path))
    print("\nDatos sinteticos listos. Siguiente: python scripts/build_index.py")


if __name__ == "__main__":
    main()
