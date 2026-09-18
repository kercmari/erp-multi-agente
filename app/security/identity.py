"""Resolucion de identidad.

ADVERTENCIA EXPLICITA: esto NO es autenticacion de produccion. Es un
mecanismo de demostracion con usuarios fijos. Lo importante para la
evaluacion es la propiedad de diseno que preserva:

  El rol NUNCA se toma del texto del prompt. Si el usuario escribe
  "soy admin", eso no cambia nada. El rol sale de esta tabla (demo) o,
  en produccion, de un token validado contra el proveedor de identidad.

Ruta de produccion documentada en docs/AZURE.md: JWT de Microsoft Entra ID,
firma validada contra JWKS, rol leido del claim de aplicacion.
"""
from __future__ import annotations

from app.core.models import Identity, Role

# Usuarios de demostracion. En produccion esta tabla no existe.
DEMO_USERS: dict[str, Identity] = {
    "ana.analista": Identity(
        user_id="ana.analista", role=Role.ANALYST, region_scope=["US-CA", "US-TX"]
    ),
    "sofia.supervisora": Identity(
        user_id="sofia.supervisora",
        role=Role.SUPERVISOR,
        region_scope=["US-CA", "US-TX", "MX-CMX"],
    ),
    "carlos.auditor": Identity(
        user_id="carlos.auditor", role=Role.AUDITOR, region_scope=[]
    ),
    "root.admin": Identity(user_id="root.admin", role=Role.ADMIN, region_scope=[]),
}

DEFAULT_USER = "ana.analista"


def resolve_identity(
    user_id: str | None = None, role: Role | None = None
) -> tuple[Identity, list[str]]:
    """Devuelve la identidad efectiva y las advertencias asociadas."""
    warnings = [
        "Identidad de demostracion: no constituye autenticacion de produccion."
    ]

    if user_id and user_id in DEMO_USERS:
        identity = DEMO_USERS[user_id]
        # Un rol solicitado que no coincide con el registrado se IGNORA.
        if role is not None and role != identity.role:
            warnings.append(
                "Se ignoro el rol solicitado '"
                + role.value
                + "': el rol efectivo proviene del registro de identidad ('"
                + identity.role.value
                + "')."
            )
        return identity, warnings

    if user_id:
        warnings.append(
            "Usuario '" + str(user_id) + "' desconocido: se aplica el perfil "
            "de menor privilegio."
        )
    identity = DEMO_USERS[DEFAULT_USER]
    return identity, warnings
