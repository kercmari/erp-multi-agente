"""Capa de validacion y seguridad.

Principio de diseno: la deteccion de patrones es una defensa PARCIAL y
deliberadamente la primera, no la unica. Aunque un atacante evada el regex,
el acceso efectivo sigue bloqueado porque:

  1. No existe ninguna herramienta que lea la tabla de salarios. El agente no
     puede alcanzar ese dato aunque quiera.
  2. get_erp_data devuelve solo campos de una lista blanca.
  3. La autorizacion se evalua contra la identidad verificada, no contra lo
     que el usuario afirme en el texto.

Eso es defensa en profundidad: el regex reduce ruido y deja traza; el control
real vive en la capa de datos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.core.models import Identity, Role


class Verdict(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    NEEDS_ELEVATION = "needs_elevation"


@dataclass
class ScreeningResult:
    verdict: Verdict
    reason: str = ""
    categories: list[str] = field(default_factory=list)
    user_message: str = ""


# --- Patrones de intencion restringida ----------------------------------
# Datos retributivos y de RRHH: fuera del alcance de conciliacion.
HR_PATTERNS = [
    r"\bsalari\w*", r"\bsueldo\w*", r"\bn[oó]min\w*", r"\bremuneraci[oó]n\w*",
    r"\bcompensaci[oó]n\w*", r"\bbonus\b", r"\bsalary\b", r"\bpayroll\b",
    r"\bcuanto (?:gana|cobra)\b", r"\bemployee_salaries\b",
]

# Intentos de anular instrucciones o escalar privilegios.
# Nota: se admiten hasta 3 palabras intermedias ("ignora TODAS LAS instrucciones")
# porque exigir adyacencia dejaba pasar variantes triviales.
_FILLER = r"(?:\s+\w+){0,3}\s+"
INJECTION_PATTERNS = [
    r"\bignor\w*" + _FILLER + r"(?:instrucciones|reglas|restricciones|permisos)",
    r"\bignore" + _FILLER + r"(?:instructions|rules|restrictions|permissions)",
    r"\bolvida\w*" + _FILLER + r"(?:instrucciones|reglas|restricciones)",
    r"\bact[uú]a\s+como\b", r"\bpretend\s+to\s+be\b",
    r"\beres\s+(?:ahora\s+)?(?:un\s+)?admin",
    r"\bmodo\s+(?:desarrollador|developer|dios)\b",
    r"\bsin\s+restricciones\b", r"\bsalta\w*\s+(?:los\s+)?permisos",
    r"\bdesactiva\w*\s+(?:la\s+)?seguridad",
    r"\bsystem\s+prompt\b", r"\bprompt\s+del\s+sistema\b",
    r"\brevela\w*\s+(?:tus\s+)?instrucciones",
    r"\bsoy\s+(?:el\s+)?(?:admin|administrador|ceo|director)\b",
]

# Intentos de ejecutar SQL arbitrario a traves del agente.
SQL_PATTERNS = [
    r"\bdrop\s+table\b", r"\bdelete\s+from\b", r"\btruncate\b",
    r"\bunion\s+select\b", r"\bselect\s+\*\s+from\b", r"\b;\s*--",
    r"\bupdate\s+\w+\s+set\b", r"\binsert\s+into\b",
]

_HR_RE = [re.compile(p, re.IGNORECASE) for p in HR_PATTERNS]
_INJ_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_SQL_RE = [re.compile(p, re.IGNORECASE) for p in SQL_PATTERNS]


def screen_input(text: str, identity: Identity) -> ScreeningResult:
    """Evalua la consulta del usuario ANTES de gastar un token de LLM."""
    q = str(text or "")
    cats: list[str] = []

    if any(r.search(q) for r in _INJ_RE):
        cats.append("prompt_injection")
    if any(r.search(q) for r in _SQL_RE):
        cats.append("sql_injection")
    if any(r.search(q) for r in _HR_RE):
        cats.append("restricted_hr_data")

    if "sql_injection" in cats:
        return ScreeningResult(
            verdict=Verdict.BLOCK, categories=cats,
            reason="Intento de SQL arbitrario",
            user_message=(
                "No puedo ejecutar sentencias SQL arbitrarias. Solo consulto "
                "ordenes concretas mediante consultas parametrizadas."
            ),
        )

    if "prompt_injection" in cats:
        return ScreeningResult(
            verdict=Verdict.BLOCK, categories=cats,
            reason="Intento de anular instrucciones o escalar privilegios",
            user_message=(
                "No puedo ignorar mis restricciones ni cambiar tu rol. Tus "
                "permisos provienen de tu identidad verificada, no del texto "
                "de la consulta. Puedo ayudarte con conciliaciones dentro de "
                "tu alcance."
            ),
        )

    if "restricted_hr_data" in cats:
        # Incluso ADMIN queda fuera: no hay herramienta hacia RRHH.
        if not identity.may_read_hr():
            return ScreeningResult(
                verdict=Verdict.BLOCK, categories=cats,
                reason="Rol " + identity.role.value + " sin acceso a datos retributivos",
                user_message=(
                    "La informacion salarial y de RRHH esta fuera del alcance de "
                    "este asistente de conciliacion y de tu rol ("
                    + identity.role.value
                    + "). Puedo ayudarte con discrepancias entre facturas y ERP."
                ),
            )
        return ScreeningResult(
            verdict=Verdict.BLOCK, categories=cats,
            reason="Datos de RRHH fuera del alcance del sistema",
            user_message=(
                "Este sistema no expone datos retributivos por diseno: no existe "
                "ninguna herramienta conectada a esa informacion."
            ),
        )

    return ScreeningResult(verdict=Verdict.ALLOW)


def authorize_tool(tool_name: str, identity: Identity) -> ScreeningResult:
    """Segunda barrera: autorizacion en el punto de ejecucion de la herramienta."""
    if tool_name == "propose_adjustment" and not identity.may_propose_adjustment():
        return ScreeningResult(
            verdict=Verdict.NEEDS_ELEVATION,
            reason="Rol " + identity.role.value + " no puede proponer ajustes",
            user_message=(
                "Tu rol puede consultar y reportar, pero proponer un asiento de "
                "ajuste requiere rol de supervisor."
            ),
        )
    return ScreeningResult(verdict=Verdict.ALLOW)


# --- Proteccion de salida ------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email-redactado]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[id-redactado]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[tarjeta-redactada]"),
]

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|bearer|password|secret|token)\b\s*[:=]\s*\S+"),
    re.compile(r"\bnvapi-\w+"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
]


def scrub_output(text: str) -> tuple[str, list[str]]:
    """Redacta PII y secretos antes de que el texto salga al cliente."""
    warnings: list[str] = []
    out = text
    for pattern, replacement in _PII_PATTERNS:
        if pattern.search(out):
            out = pattern.sub(replacement, out)
            warnings.append("Se redacto informacion personal en la respuesta.")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(out):
            out = pattern.sub("[secreto-redactado]", out)
            warnings.append("Se redacto un posible secreto en la respuesta.")
    return out, list(dict.fromkeys(warnings))


def redact_for_log(text: str, max_chars: int = 200) -> str:
    """Minimiza lo que llega a los logs: recorta y redacta."""
    scrubbed, _ = scrub_output(str(text or ""))
    return scrubbed[:max_chars]
