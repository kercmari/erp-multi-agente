"""Demostracion del filtrado de metadata por ano (para el video y el README).

Muestra que SIN filtro, el fragmento derogado de 2023 gana por score y
contaminaria la respuesta. Con filtro, queda excluido.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# La consola de Windows (cp1252) puede reventar con caracteres que genera el
# modelo. Forzamos UTF-8 con reemplazo para que la demo nunca se caiga.
import io as _io_compat
import sys as _sys_compat

if hasattr(_sys_compat.stdout, "buffer"):
    _sys_compat.stdout = _io_compat.TextIOWrapper(
        _sys_compat.stdout.buffer, encoding="utf-8", errors="replace",
        line_buffering=True,
    )


from app.tools.policy import search_policy  # noqa: E402

CONSULTA = "tasa impositiva aplicable US-CA logistica"


def main() -> None:
    print("Consulta: " + CONSULTA)
    print("=" * 72)

    for etiqueta, year in [("year=2024", 2024), ("year=2023", 2023), ("SIN FILTRO", None)]:
        r = search_policy(CONSULTA, year=year, region="US-CA")
        res = r.content.get("results", [])
        anos = sorted({x["year"] for x in res})
        print("\n[" + etiqueta + "]")
        print("  fragmentos recuperados : " + str(len(res)))
        print("  anos presentes         : " + str(anos))
        if res:
            top = res[0]
            print(
                "  mejor resultado        : pagina "
                + str(top["page"])
                + " (ano "
                + str(top["year"])
                + ") score "
                + str(top["score"])
            )

    print("\n" + "=" * 72)
    print("CONCLUSION: sin filtro, el fragmento de 2023 (DEROGADO) gana por score.")
    print("El filtro por ano es lo que impide responder con la tasa obsoleta.")

    print("\n[year=2019] -> sin evidencia aplicable")
    r = search_policy(CONSULTA, year=2019)
    print("  " + str(r.content.get("note")))


if __name__ == "__main__":
    main()
