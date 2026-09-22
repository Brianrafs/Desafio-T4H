import json
import logging
from enum import StrEnum


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


def record(event: Event, session_id: str, *, agent=None, status=None, error_code=None) -> None:
    """Contrato fechado: não aceita mensagem, CPF, valores ou objetos arbitrários."""
    payload = {"event": event.value, "session_id": session_id}
    for name, value in (("agent", agent), ("status", status), ("error_code", error_code)):
        if value is not None:
            payload[name] = value
    logging.getLogger("banco_agil").info(json.dumps(payload, ensure_ascii=False))
