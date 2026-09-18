"""API FastAPI: endpoint de consulta con streaming SSE real.

Contrato de errores:
  - Fallo ANTES de abrir el stream -> codigo HTTP apropiado (400/403/503).
  - Fallo DESPUES de abrir el stream -> evento SSE de tipo "error". No se
    intenta reemplazar el codigo HTTP porque ya se envio el 200.
Nunca se filtran trazas internas ni secretos al cliente.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.memory import SESSIONS, Turn
from app.agents.orchestrator import Orchestrator
from app.core.config import get_settings
from app.core.models import AgentAnswer, QueryRequest
from app.security.guardrails import redact_for_log
from app.security.identity import DEMO_USERS, resolve_identity

logger = logging.getLogger("conciliacion")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    logger.info(
        "Arranque | proveedor=%s modelo=%s mock=%s",
        s.llm_provider, s.llm_model, s.llm_is_mock,
    )
    yield
    SESSIONS.purge_expired()


app = FastAPI(
    title="Agente de Conciliacion Logistica",
    version="1.0.0",
    description=(
        "Sistema multi-agente que concilia facturas de logistica contra un ERP "
        "simulado, respaldando cada conclusion con normativa recuperada por RAG."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    rid = str(uuid.uuid4())[:8]
    request.state.request_id = rid
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    logger.info(
        "req=%s %s %s -> %s (%dms)",
        rid, request.method, request.url.path, response.status_code,
        int((time.perf_counter() - started) * 1000),
    )
    return response


@app.get("/health")
async def health() -> dict[str, Any]:
    s = get_settings()
    from pathlib import Path

    return {
        "status": "ok",
        "llm_provider": s.llm_provider,
        "llm_is_mock": s.llm_is_mock,
        "erp_db": Path(s.erp_db_path).exists(),
        "vector_index": Path(s.vector_index_path, "vectors.npy").exists(),
    }


@app.get("/demo/users")
async def demo_users() -> dict[str, Any]:
    """Usuarios de demostracion. NO es un directorio de produccion."""
    return {
        "warning": "Identidades de demostracion, no autenticacion real.",
        "users": [
            {
                "user_id": u.user_id,
                "role": u.role.value,
                "region_scope": u.region_scope or ["global"],
            }
            for u in DEMO_USERS.values()
        ],
    }


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    """Serializa un evento SSE con tipo explicito."""
    return "event: " + event_type + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@app.post("/query", response_model=AgentAnswer)
async def query(req: QueryRequest) -> Any:
    """Consulta sin streaming. Devuelve la respuesta validada completa."""
    identity, id_warnings = resolve_identity(req.demo_user_id, req.demo_role)
    session = SESSIONS.get_or_create(req.session_id, identity.user_id)
    logger.info(
        "consulta user=%s rol=%s q=%s",
        identity.user_id, identity.role.value, redact_for_log(req.query),
    )

    try:
        orch = Orchestrator()
        answer = await orch.run(req.query, identity, session)
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": "dependency_unavailable",
                "message": (
                    "Falta preparar los datos. Ejecuta scripts/seed_data.py y "
                    "scripts/build_index.py."
                ),
                "detail": str(e)[:200],
            },
        )
    except Exception:
        # No se filtra la traza al cliente; queda en el log del servidor.
        logger.exception("Fallo no controlado en /query")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Error interno. No se realizo ninguna accion sobre el ERP.",
            },
        )

    answer.warnings = id_warnings + answer.warnings
    SESSIONS.append(
        session,
        Turn(query=req.query, answer=answer.answer, decision=answer.decision.value),
    )
    return answer


@app.post("/query/stream")
async def query_stream(req: QueryRequest) -> Any:
    """Consulta con streaming SSE de tokens reales.

    Tipos de evento: progress | token | evidence | result | error | done
    """
    identity, id_warnings = resolve_identity(req.demo_user_id, req.demo_role)
    session = SESSIONS.get_or_create(req.session_id, identity.user_id)
    logger.info(
        "stream user=%s rol=%s q=%s",
        identity.user_id, identity.role.value, redact_for_log(req.query),
    )

    async def event_source() -> AsyncIterator[str]:
        # Primer evento inmediato: reduce el tiempo percibido de espera.
        yield _sse(
            "progress",
            {
                "stage": "accepted",
                "session_id": session.session_id,
                "role": identity.role.value,
                "warnings": id_warnings,
            },
        )
        final_answer, final_decision = "", "unknown"
        try:
            orch = Orchestrator()
            async for event in orch.stream(req.query, identity, session):
                if event.type == "result":
                    final_answer = event.data.get("answer", "")
                    final_decision = event.data.get("decision", "unknown")
                yield _sse(event.type, event.data)
        except FileNotFoundError:
            yield _sse(
                "error",
                {
                    "code": "dependency_unavailable",
                    "message": (
                        "Falta preparar los datos: ejecuta scripts/seed_data.py "
                        "y scripts/build_index.py."
                    ),
                },
            )
            yield _sse("done", {"decision": "aborted"})
            return
        except Exception:
            logger.exception("Fallo no controlado en /query/stream")
            # Ya se envio 200: el error viaja como evento, no como codigo HTTP.
            yield _sse(
                "error",
                {
                    "code": "internal_error",
                    "message": (
                        "Error interno durante la generacion. No se realizo "
                        "ninguna accion sobre el ERP."
                    ),
                },
            )
            yield _sse("done", {"decision": "aborted"})
            return

        if final_answer:
            SESSIONS.append(
                session,
                Turn(query=req.query, answer=final_answer, decision=final_decision),
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # evita buffering en proxies
            "Connection": "keep-alive",
        },
    )
