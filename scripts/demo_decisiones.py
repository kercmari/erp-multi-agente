"""Demostracion de los dos contrastes de decision (para el video y el README).

1. MISMO dato, roles distintos -> decision distinta (autorizacion).
2. MISMO rol, datos distintos  -> decision distinta (logica de negocio).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.disable(logging.INFO)

# La consola de Windows (cp1252) puede reventar con caracteres que genera el
# modelo. Forzamos UTF-8 con reemplazo para que la demo nunca se caiga.
import io as _io_compat
import sys as _sys_compat

if hasattr(_sys_compat.stdout, "buffer"):
    _sys_compat.stdout = _io_compat.TextIOWrapper(
        _sys_compat.stdout.buffer, encoding="utf-8", errors="replace",
        line_buffering=True,
    )


from fastapi.testclient import TestClient  # noqa: E402

from app.api import app  # noqa: E402

client = TestClient(app)


def consultar(query: str, user: str) -> dict:
    return client.post("/query", json={"query": query, "demo_user_id": user}).json()


def main() -> None:
    print("=" * 74)
    print("CONTRASTE 1 - Misma orden #4402, roles distintos")
    print("=" * 74)
    print("La autorizacion no solo bloquea: cambia la decision de negocio.\n")
    for user in ("sofia.supervisora", "ana.analista", "carlos.auditor"):
        d = consultar("Por que hay una discrepancia en el envio #4402?", user)
        print("  " + user.ljust(20) + " -> " + d["decision"])

    print("\n" + "=" * 74)
    print("CONTRASTE 2 - Mismo rol (analista), datos distintos")
    print("=" * 74)
    casos = [
        ("4403", "diferencia de 0.01: redondeo dentro de tolerancia"),
        ("4404", "importe correcto"),
        ("9999", "orden inexistente: no se inventa nada"),
    ]
    for orden, desc in casos:
        d = consultar("Revisa el envio #" + orden, "ana.analista")
        print("  #" + orden + "  " + d["decision"].ljust(22) + desc)

    print("\n" + "=" * 74)
    print("Todos los casos recorren el MISMO codigo.")
    print("Lo que cambia es el dato y el permiso; la decision se adapta.")
    print("=" * 74)


if __name__ == "__main__":
    main()
