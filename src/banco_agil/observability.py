import json
import logging
from enum import StrEnum
from uuid import UUID

from banco_agil.models.domain import CreditRequestStatus
from banco_agil.models.errors import ErrorCode
from banco_agil.models.responses import FallbackReason
from banco_agil.models.state import AgentType


class Event(StrEnum):
    SESSION_STARTED = "session_started"
    AUTHENTICATION_ATTEMPT = "authentication_attempt"
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    AGENT_TRANSITION = "agent_transition"
    CREDIT_LIMIT_REQUESTED = "credit_limit_requested"
    CREDIT_REQUEST_EVALUATED = "credit_request_evaluated"
    CREDIT_SCORE_UPDATED = "credit_score_updated"
    EXCHANGE_RATE_REQUESTED = "exchange_rate_requested"
    EXTERNAL_API_FAILED = "external_api_failed"
    OPERATION_FAILED = "operation_failed"
    CONVERSATION_FINISHED = "conversation_finished"
    RESPONSE_COMPOSITION_STARTED = "response_composition_started"
    RESPONSE_COMPOSITION_SUCCEEDED = "response_composition_succeeded"
    RESPONSE_COMPOSITION_FALLBACK = "response_composition_fallback"
    RESPONSE_POLICY_REJECTED = "response_policy_rejected"


def configure_logging() -> None:
    from crewai.events.event_listener import EventListener

    # CrewAI 1.15 mantém um formatter global ativo mesmo com Agent(verbose=False).
    EventListener().formatter.verbose = False
    for name in ("httpx", "httpcore", "crewai", "litellm"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logger = logging.getLogger("banco_agil")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def record(
    event: Event,
    session_id: str,
    *,
    agent: AgentType | None = None,
    status: CreditRequestStatus | None = None,
    error_code: ErrorCode | None = None,
    reason: FallbackReason | None = None,
) -> None:
    """Contrato fechado: não aceita mensagem, CPF, valores ou objetos arbitrários."""
    if not isinstance(session_id, str):
        raise TypeError("Identificador de sessão inválido")
    payload = {"event": Event(event).value, "session_id": str(UUID(session_id))}
    for name, value, enum in (
        ("agent", agent, AgentType),
        ("status", status, CreditRequestStatus),
        ("error_code", error_code, ErrorCode),
        ("reason", reason, FallbackReason),
    ):
        if value is not None:
            payload[name] = enum(value).value
    logging.getLogger("banco_agil").info(json.dumps(payload, ensure_ascii=False))
