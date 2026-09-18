"""Verifica la conexion con el proveedor de LLM configurado.

Ejecutar ANTES de grabar el video para confirmar que la API key funciona.
Diagnostica el problema concreto si algo falla, en vez de dar un error opaco.

Uso:
    python scripts/verificar_llm.py
"""
from __future__ import annotations

import asyncio
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


from app.core.config import get_settings  # noqa: E402
from app.llm.base import LLMError  # noqa: E402
from app.llm.factory import build_llm  # noqa: E402


def separador(titulo: str) -> None:
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


async def main() -> int:
    s = get_settings()

    separador("1. CONFIGURACION LEIDA")
    print("  proveedor : " + s.llm_provider)
    print("  modelo    : " + s.llm_model)
    print("  base_url  : " + s.llm_base_url)
    key = s.llm_api_key
    if key:
        # Nunca imprimir la clave completa.
        print("  api_key   : " + key[:7] + "..." + key[-4:] + " (" + str(len(key)) + " caracteres)")
    else:
        print("  api_key   : (vacia)")

    if s.llm_is_mock:
        separador("RESULTADO: modo MOCK")
        print("El sistema funciona, pero SIN LLM real.")
        print()
        if not Path(".env").exists():
            print("Causa: no existe el archivo .env")
            print()
            print("Solucion:")
            print("  1. copy .env.example .env          (Windows)")
            print("     cp .env.example .env            (Linux/Mac)")
            print("  2. Edita .env y pon estas cuatro lineas SIN el # delante:")
            print("       LLM_PROVIDER=nvidia")
            print("       LLM_API_KEY=nvapi-tu-clave-aqui")
            print("       LLM_BASE_URL=https://integrate.api.nvidia.com/v1")
            print("       LLM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b")
        elif not key:
            print("Causa: existe .env pero LLM_API_KEY esta vacia o comentada.")
            print("Revisa que la linea NO empiece por '#'.")
        else:
            print("Causa: LLM_PROVIDER=mock. Cambialo a 'nvidia' en .env.")
        print()
        print("La demo funciona igual en modo mock; esto solo activa el LLM real.")
        return 0

    separador("2. PRUEBA DE CONEXION (sin herramientas)")
    llm = build_llm(s)
    print("  cliente: " + type(llm).__name__)
    try:
        r = await llm.complete(
            [{"role": "user", "content": "Responde unicamente con la palabra: listo"}]
        )
        print("  respuesta: " + (r.text or "(vacia)")[:120])
        print("  [OK] El modelo responde.")
    except LLMError as e:
        print("  [FALLO] codigo=" + e.code)
        print("  detalle: " + str(e))
        print()
        if e.code == "llm_unauthorized":
            print("  -> La clave es invalida o expiro.")
            print("     Genera una nueva en https://build.nvidia.com")
        elif e.code == "llm_rate_limited":
            print("  -> Limite de peticiones alcanzado. Espera unos minutos.")
        elif e.code == "llm_timeout":
            print("  -> Sin respuesta a tiempo. Revisa tu conexion o proxy.")
        elif e.code == "llm_bad_request":
            print("  -> El modelo '" + s.llm_model + "' puede no existir o no")
            print("     estar disponible para tu cuenta. Modelos verificados:")
            print("       nvidia/nemotron-3.5-lightning-30b-a3b   (mas rapido)")
            print("       openai/gpt-oss-20b")
            print("       nvidia/nemotron-3-super-120b-a12b")
        return 1
    except Exception as e:  # noqa: BLE001
        print("  [FALLO INESPERADO] " + type(e).__name__ + ": " + str(e)[:200])
        return 1

    separador("3. PRUEBA DE FUNCTION CALLING")
    print("  (esto es lo critico: el agente NO funciona sin function calling)")
    from app.agents.registry import TOOL_SPECS

    try:
        r = await llm.complete(
            [
                {
                    "role": "system",
                    "content": "Usa las herramientas disponibles cuando corresponda.",
                },
                {
                    "role": "user",
                    "content": "Consulta los datos de la orden 4402 en el ERP.",
                },
            ],
            TOOL_SPECS,
        )
        if r.tool_calls:
            print("  [OK] El modelo pidio " + str(len(r.tool_calls)) + " herramienta(s):")
            for c in r.tool_calls:
                print("       - " + c.get("name", "?") + " " + str(c.get("arguments")))
        else:
            print("  [AVISO] El modelo NO pidio herramientas.")
            print("  respuesta de texto: " + (r.text or "")[:150])
            print()
            print("  -> Este modelo puede no soportar function calling.")
            print("     Modelos verificados que si lo soportan:")
            print("       nvidia/nemotron-3.5-lightning-30b-a3b")
            print("       openai/gpt-oss-20b")
            print("       nvidia/nemotron-3-super-120b-a12b")
            return 1
    except LLMError as e:
        print("  [FALLO] codigo=" + e.code + " | " + str(e)[:150])
        return 1

    separador("4. PRUEBA DE STREAMING")
    print("  (el video depende de esto)")
    try:
        piezas = []
        async for p in llm.stream(
            [{"role": "user", "content": "Cuenta del uno al cinco, separado por comas."}]
        ):
            piezas.append(p)
        print("  fragmentos recibidos: " + str(len(piezas)))
        print("  texto: " + "".join(piezas)[:120])
        if len(piezas) > 1:
            print("  [OK] Streaming real confirmado.")
        else:
            print("  [AVISO] Llego en un solo bloque, no hay streaming incremental.")
    except LLMError as e:
        print("  [FALLO] codigo=" + e.code + " | " + str(e)[:150])
        return 1

    separador("5. AGENTE COMPLETO CON LLM REAL")
    from app.agents.memory import SESSIONS
    from app.agents.orchestrator import Orchestrator
    from app.security.identity import resolve_identity

    identidad, _ = resolve_identity("sofia.supervisora")
    sesion = SESSIONS.get_or_create(None, identidad.user_id)
    try:
        ans = await Orchestrator(llm=llm, settings=s).run(
            "Por que hay una discrepancia en el envio #4402?", identidad, sesion
        )
        print("  proveedor    : " + ans.llm_provider)
        print("  herramientas : " + str(ans.tool_calls))
        print("  iteraciones  : " + str(ans.iterations))
        print("  decision     : " + ans.decision.value)
        print("  evidencia    : " + str([(e.page, e.year) for e in ans.evidence]))
        print()
        print("  RESPUESTA:")
        for linea in ans.answer.split("\n"):
            if linea.strip():
                print("    " + linea.strip()[:100])

        esperadas = {"get_erp_data", "calculate_tax_discrepancy"}
        if esperadas.issubset(set(ans.tool_calls)):
            print()
            print("  [OK] Encadenamiento de herramientas confirmado con LLM real.")
        else:
            print()
            print("  [AVISO] No se observo el encadenamiento completo.")
            print("  Faltaron: " + str(esperadas - set(ans.tool_calls)))
    except LLMError as e:
        print("  [FALLO] codigo=" + e.code + " | " + str(e)[:150])
        return 1

    separador("LISTO PARA GRABAR")
    print("El LLM real funciona end-to-end. Puedes grabar el video con")
    print("LLM_PROVIDER=nvidia y mostrar el agente razonando de verdad.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
