import pytest

from banco_agil.flow.guards import validate_transition
from banco_agil.models.errors import AuthorizationError
from banco_agil.models.state import (
    AgentType,
    CreditInterviewContext,
    SessionState,
    TransitionIntent,
)


@pytest.mark.parametrize("source", list(AgentType))
@pytest.mark.parametrize("intent", list(TransitionIntent))
def test_transition_matrix(source, intent):
    state = SessionState(
        current_agent=source, authenticated=True, authenticated_customer_cpf="00000000001"
    )
    allowed = intent == TransitionIntent.END_CONVERSATION or (source, intent) in {
        (AgentType.TRIAGE, TransitionIntent.GO_TO_CREDIT),
        (AgentType.TRIAGE, TransitionIntent.GO_TO_EXCHANGE),
        (AgentType.CREDIT, TransitionIntent.GO_TO_EXCHANGE),
        (AgentType.EXCHANGE, TransitionIntent.GO_TO_CREDIT),
    }
    if allowed:
        validate_transition(state, intent)
    else:
        with pytest.raises(AuthorizationError):
            validate_transition(state, intent)


def test_interview_return_requires_persistence():
    state = SessionState(
        current_agent=AgentType.INTERVIEW,
        authenticated=True,
        authenticated_customer_cpf="00000000001",
        interview=CreditInterviewContext(
            monthly_income=0,
            employment_type="desempregado",
            fixed_expenses=0,
            dependents=0,
            has_active_debt=False,
        ),
    )
    with pytest.raises(AuthorizationError):
        validate_transition(state, TransitionIntent.RETURN_TO_CREDIT)
    state.interview.score_persisted = True
    validate_transition(state, TransitionIntent.RETURN_TO_CREDIT)
