"""Modelos de dominio. Pydantic valida entradas y salidas en todos los bordes."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(str, Enum):
    """Roles de la demo. En produccion vendrian de un IdP (Entra ID)."""

    ANALYST = "analyst"        # consulta conciliaciones, sin datos de RRHH
    SUPERVISOR = "supervisor"  # ademas puede proponer ajustes
    AUDITOR = "auditor"        # solo lectura, incluye historico
    ADMIN = "admin"            # acceso ampliado


class Decision(str, Enum):
    REPORT = "report"              # explicar, sin escribir nada
    PROPOSE_ADJUSTMENT = "propose_adjustment"
    ESCALATE_HUMAN = "escalate_human"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"


class Identity(BaseModel):
    """Identidad verificada. NUNCA se construye desde el texto del prompt."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    role: Role
    region_scope: list[str] = Field(default_factory=list)

    def may_read_hr(self) -> bool:
        return self.role == Role.ADMIN

    def may_propose_adjustment(self) -> bool:
        return self.role in (Role.SUPERVISOR, Role.ADMIN)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str = ""


class ToolResult(BaseModel):
    name: str
    call_id: str = ""
    ok: bool = True
    error_code: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0

    def to_llm_text(self) -> str:
        import json

        if not self.ok:
            return json.dumps(
                {"error": self.error_code, "detail": self.content.get("detail", "")},
                ensure_ascii=False,
            )
        return json.dumps(self.content, ensure_ascii=False, default=str)


class EvidenceRef(BaseModel):
    """Referencia trazable a la fuente. Sostiene el KPI de faithfulness."""

    source: str
    page: int | None = None
    year: int | None = None
    region: str | None = None
    doc_id: str | None = None
    score: float | None = None
    excerpt: str = ""


class OrderRecord(BaseModel):
    order_id: str
    invoice_amount: Decimal
    erp_amount: Decimal
    region: str
    currency: str = "USD"
    status: str = "open"
    issued_at: datetime | None = None
    carrier: str | None = None

    @field_validator("invoice_amount", "erp_amount", mode="before")
    @classmethod
    def _to_decimal(cls, v: Any) -> Decimal:
        return Decimal(str(v))


class TaxDiscrepancy(BaseModel):
    """Resultado del calculo fiscal. Decimal en todo el camino, nunca float."""

    amount: Decimal
    region: str
    tax_rate: Decimal
    expected_tax: Decimal
    expected_total: Decimal
    recorded_total: Decimal | None = None
    discrepancy: Decimal | None = None
    within_tolerance: bool | None = None
    tolerance: Decimal = Decimal("0.01")
    rule_id: str = ""
    rule_year: int | None = None


class AgentAnswer(BaseModel):
    """Salida validada del agente. La API nunca emite texto libre sin esto."""

    answer: str
    decision: Decision
    evidence: list[EvidenceRef] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    discrepancy: TaxDiscrepancy | None = None
    warnings: list[str] = Field(default_factory=list)
    session_id: str = ""
    iterations: int = 0
    llm_provider: str = "mock"


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    # Identidad de DEMO. En produccion se ignora y se usa el token validado.
    demo_user_id: str | None = None
    demo_role: Role | None = None


StreamEventType = Literal["progress", "token", "evidence", "result", "error", "done"]


class StreamEvent(BaseModel):
    """Contrato de eventos SSE acordado con frontend (ver docs/rendimiento)."""

    type: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
