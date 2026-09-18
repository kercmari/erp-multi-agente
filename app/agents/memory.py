"""Memoria de sesion con aislamiento por usuario.

Propiedad de seguridad: una sesion pertenece a un user_id. Si otro usuario
presenta el mismo session_id, NO recibe el historial: se le abre una sesion
nueva. La memoria nunca sustituye la autorizacion; el rol se re-evalua en
cada turno contra la identidad actual.

Almacenamiento en memoria del proceso (adecuado para el MVP). Limitacion
documentada: no sobrevive a reinicios ni se comparte entre replicas. En
produccion iria a Redis o Cosmos DB con TTL (ver docs/AZURE.md).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_TURNS = 8
SESSION_TTL_S = 3600


@dataclass
class Turn:
    query: str
    answer: str
    decision: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    user_id: str
    turns: list[Turn] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.updated_at) > SESSION_TTL_S


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None, user_id: str) -> Session:
        with self._lock:
            if session_id and session_id in self._data:
                s = self._data[session_id]
                # Aislamiento: la sesion solo se devuelve a su dueno.
                if s.user_id == user_id and not s.is_expired():
                    return s
                if s.is_expired():
                    self._data.pop(session_id, None)
            new_id = str(uuid.uuid4())
            s = Session(session_id=new_id, user_id=user_id)
            self._data[new_id] = s
            return s

    def append(self, session: Session, turn: Turn) -> None:
        with self._lock:
            session.turns.append(turn)
            if len(session.turns) > MAX_TURNS:
                session.turns = session.turns[-MAX_TURNS:]
            session.updated_at = time.time()

    def remember(self, session: Session, key: str, value: Any) -> None:
        with self._lock:
            session.facts[key] = value
            session.updated_at = time.time()

    def purge_expired(self) -> int:
        with self._lock:
            dead = [k for k, v in self._data.items() if v.is_expired()]
            for k in dead:
                self._data.pop(k, None)
            return len(dead)


SESSIONS = SessionStore()


def history_as_messages(session: Session, limit: int = 3) -> list[dict[str, str]]:
    """Convierte los ultimos turnos en contexto para el modelo.

    Se limita deliberadamente: mas historial es mas latencia y mas coste, con
    rendimiento decreciente (ver docs/RENDIMIENTO.md).
    """
    msgs: list[dict[str, str]] = []
    for t in session.turns[-limit:]:
        msgs.append({"role": "user", "content": t.query})
        msgs.append({"role": "assistant", "content": t.answer})
    return msgs
