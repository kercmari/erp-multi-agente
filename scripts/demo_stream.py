"""Demostracion del streaming SSE contra el servidor en marcha (para el video).

Muestra los eventos conforme llegan, etiquetados y legibles en camara, y al
final un resumen con los tiempos reales medidos.

Requiere el servidor corriendo:  uvicorn app.api:app --port 8000

Uso:
    python scripts/demo_stream.py                    # orden 4402, supervisora
    python scripts/demo_stream.py 4403 ana.analista  # otra orden y rol
"""
from __future__ import annotations

import io
import json
import sys
import time

import httpx

# La consola de Windows usa cp1252 y revienta con ciertos caracteres que los
# modelos generan (espacios finos, guiones no separables). Forzamos UTF-8 con
# reemplazo para que una grabacion nunca se caiga por esto.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

URL = "http://localhost:8000/query/stream"


def main() -> int:
    orden = sys.argv[1] if len(sys.argv) > 1 else "4402"
    usuario = sys.argv[2] if len(sys.argv) > 2 else "sofia.supervisora"
    consulta = "Por que hay una discrepancia en el envio #" + orden + "?"

    print("=" * 74)
    print("CONSULTA : " + consulta)
    print("USUARIO  : " + usuario)
    print("=" * 74)
    print()

    t0 = time.perf_counter()
    t_primer_evento = None
    t_primer_token = None
    n_tokens = 0
    texto: list[str] = []
    resultado: dict | None = None

    try:
        with httpx.stream(
            "POST",
            URL,
            json={"query": consulta, "demo_user_id": usuario},
            timeout=180.0,
        ) as r:
            if r.status_code != 200:
                print("ERROR HTTP " + str(r.status_code))
                return 1

            evento = None
            for linea in r.iter_lines():
                if linea.startswith("event: "):
                    evento = linea[7:].strip()
                    continue
                if not linea.startswith("data: "):
                    continue

                data = json.loads(linea[6:])
                ahora = time.perf_counter() - t0
                if t_primer_evento is None:
                    t_primer_evento = ahora

                if evento == "progress":
                    etapa = data.get("stage", "")
                    msg = data.get("message", "")
                    tool = data.get("tool")
                    linea_txt = "  [" + format(ahora, "6.2f") + "s] " + etapa.upper()
                    if tool:
                        linea_txt += " -> " + tool
                    elif msg:
                        linea_txt += " : " + msg
                    print(linea_txt, flush=True)

                elif evento == "evidence":
                    print("  [" + format(ahora, "6.2f") + "s] EVIDENCIA recuperada:", flush=True)
                    for it in data.get("items", []):
                        print(
                            "            pagina "
                            + str(it.get("page"))
                            + "  ano "
                            + str(it.get("year"))
                            + "  score "
                            + str(it.get("score")),
                            flush=True,
                        )

                elif evento == "token":
                    if t_primer_token is None:
                        t_primer_token = ahora
                        print(
                            "\n  [" + format(ahora, "6.2f") + "s] "
                            "TOKENS (generacion en vivo):\n",
                            flush=True,
                        )
                    t = data.get("text", "")
                    texto.append(t)
                    n_tokens += 1
                    sys.stdout.write(t)
                    sys.stdout.flush()

                elif evento == "evidence_error" or evento == "error":
                    print(
                        "\n  [" + format(ahora, "6.2f") + "s] ERROR: "
                        + str(data.get("code")) + " - " + str(data.get("message")),
                        flush=True,
                    )

                elif evento == "result":
                    resultado = data

                elif evento == "done":
                    print("\n", flush=True)
    except httpx.ConnectError:
        print("No hay servidor en " + URL)
        print("Arrancalo con:  uvicorn app.api:app --port 8000")
        return 1
    except httpx.ReadTimeout:
        print("\nEl modelo tardo demasiado. Prueba con LLM_PROVIDER=mock en .env.")
        return 1

    total = time.perf_counter() - t0
    print("\n" + "=" * 74)
    print("RESUMEN")
    print("=" * 74)
    if t_primer_evento is not None:
        print("  primer evento     : " + format(t_primer_evento * 1000, ".0f") + " ms")
    if t_primer_token is not None:
        print("  primer token      : " + format(t_primer_token, ".1f") + " s")
    print("  tiempo total      : " + format(total, ".1f") + " s")
    print("  tokens recibidos  : " + str(n_tokens))
    if resultado:
        print("  herramientas      : " + str(resultado.get("tool_calls")))
        print("  iteraciones ReAct : " + str(resultado.get("iterations")))
        print("  DECISION          : " + str(resultado.get("decision", "")).upper())
        print("  proveedor         : " + str(resultado.get("llm_provider")))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
