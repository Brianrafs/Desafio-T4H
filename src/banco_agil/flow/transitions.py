from banco_agil.flow.guards import validate_transition
from banco_agil.models.state import (
    AgentType,
    ConversationStatus,
    SessionState,
    TransitionIntent,
)

DESTINATIONS = {
    TransitionIntent.GO_TO_CREDIT: AgentType.CREDIT,
    TransitionIntent.GO_TO_EXCHANGE: AgentType.EXCHANGE,
    TransitionIntent.START_CREDIT_INTERVIEW: AgentType.INTERVIEW,
    TransitionIntent.RETURN_TO_CREDIT: AgentType.CREDIT,
}


def transition(state: SessionState, intent: TransitionIntent, *, accepted=False) -> None:
    validate_transition(state, intent, accepted=accepted)
    if intent == TransitionIntent.END_CONVERSATION:
        state.status = ConversationStatus.FINISHED
    else:
        state.current_agent = DESTINATIONS[intent]
