from banco_agil.models.domain import CreditRequestStatus
from banco_agil.models.errors import AuthorizationError
from banco_agil.models.state import (
    AgentType,
    ConversationStatus,
    SessionState,
    TransitionIntent,
)


def validate_transition(
    state: SessionState, intent: TransitionIntent, *, accepted=False, operation_completed=False
) -> None:
    if state.status != ConversationStatus.ACTIVE:
        raise AuthorizationError()
    if intent == TransitionIntent.END_CONVERSATION:
        return
    if not state.authenticated or not state.authenticated_customer_cpf:
        raise AuthorizationError()
    source = state.current_agent
    allowed = False
    if intent == TransitionIntent.RETURN_TO_TRIAGE:
        allowed = (
            operation_completed
            and source in (AgentType.CREDIT, AgentType.EXCHANGE)
            and not state.credit.awaiting_requested_limit
            and not state.credit.awaiting_interview_confirmation
        )
    elif intent == TransitionIntent.GO_TO_CREDIT:
        allowed = source in (AgentType.TRIAGE, AgentType.EXCHANGE)
    elif intent == TransitionIntent.GO_TO_EXCHANGE:
        allowed = source in (AgentType.TRIAGE, AgentType.CREDIT)
    elif intent == TransitionIntent.START_CREDIT_INTERVIEW:
        allowed = (
            source == AgentType.CREDIT
            and accepted
            and state.credit.awaiting_interview_confirmation
            and state.credit.last_request_status == CreditRequestStatus.REJECTED
            and state.credit.requested_limit is not None
        )
    elif intent == TransitionIntent.RETURN_TO_CREDIT:
        allowed = (
            source == AgentType.INTERVIEW
            and state.interview is not None
            and state.interview.is_complete()
            and state.interview.score_persisted
        )
    if not allowed:
        raise AuthorizationError()
