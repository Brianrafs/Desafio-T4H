import pytest

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import TriageTurnResult


async def test_progressive_authentication(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(detected_intent="credit_limit_increase"))
    await flow.process(TriageTurnResult(cpf="000.000.000-01"))
    assert not flow.state.authenticated
    await flow.process(TriageTurnResult(birth_date="1990-01-15"))
    assert flow.state.authenticated
    assert flow.state.authenticated_customer_cpf == "00000000001"
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit
    assert flow.state.authentication.cpf is None


async def test_third_failure_ends_session(data_dir):
    flow = BankingFlow(data_dir)
    invalid = TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")
    for _ in range(3):
        await flow.process(invalid)
    assert flow.state.authentication_attempts == 3
    assert flow.state.status == "finished"
    before = flow.state.model_dump()
    await flow.process(TriageTurnResult(cpf="00000000001", birth_date="1990-01-15"))
    assert flow.state.model_dump() == before


async def test_end_before_authentication(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(end_requested=True))
    assert flow.state.status == "finished"


@pytest.mark.parametrize("intent", ["go_to_credit", "go_to_exchange", "start_credit_interview"])
async def test_transition_cannot_bypass_authentication(data_dir, intent):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(transition_request=intent))
    assert not flow.state.authenticated
    assert flow.state.current_agent == "triage"
