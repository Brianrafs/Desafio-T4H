from banco_agil.flow.guards import validate_transition
from banco_agil.models.state import (
    AgentType,
    ConversationStatus,
    SessionState,
    TransitionIntent,
)
from banco_agil.observability import Event, record

DESTINATIONS = {
    TransitionIntent.RETURN_TO_TRIAGE: AgentType.TRIAGE,
    TransitionIntent.GO_TO_CREDIT: AgentType.CREDIT,
    TransitionIntent.GO_TO_EXCHANGE: AgentType.EXCHANGE,
    TransitionIntent.START_CREDIT_INTERVIEW: AgentType.INTERVIEW,
    TransitionIntent.RETURN_TO_CREDIT: AgentType.CREDIT,
}


def transition(
    state: SessionState, intent: TransitionIntent, *, accepted=False, operation_completed=False
) -> None:
    validate_transition(state, intent, accepted=accepted, operation_completed=operation_completed)
    if intent == TransitionIntent.END_CONVERSATION:
        state.status = ConversationStatus.FINISHED
        record(Event.CONVERSATION_FINISHED, state.session_id)
    else:
        state.current_agent = DESTINATIONS[intent]
        record(Event.AGENT_TRANSITION, state.session_id, agent=state.current_agent)
