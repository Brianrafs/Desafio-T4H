import httpx

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, ExchangeTurnResult, TriageTurnResult
from banco_agil.services.exchange_service import ExchangeService


async def authenticate(flow, intent="credit_limit_query"):
    return await flow.process(
        TriageTurnResult(cpf="00000000001", birth_date="1990-01-15", detected_intent=intent)
    )


async def test_query_and_increase(data_dir):
    flow = BankingFlow(data_dir)
    assert "1.000,00" in await authenticate(flow)
    await flow.process(
        CreditTurnResult(detected_intent="credit_limit_increase", requested_limit=2000)
    )
    assert flow.state.credit.last_request_status == "aprovado"
    assert flow._tools.credit.get_limit("00000000001") == 2000


async def test_zero_limit_is_controlled(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)
    await flow.process(CreditTurnResult(requested_limit=0))
    assert flow.state.last_error_code == "invalid_limit"
    assert flow.tools.credit.requests.read() == []


async def test_topic_switch_and_forbidden_interview(data_dir):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"USDBRL": {"bid": "5"}})
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow)
    result = await flow.process(
        CreditTurnResult(transition_request="go_to_exchange", currency="USD")
    )
    assert "5.0000" in result
    assert flow.state.current_agent == "exchange"
    await flow.process(ExchangeTurnResult(transition_request="start_credit_interview"))
    assert flow.state.current_agent == "exchange"
    assert flow.state.last_error_code == "unauthorized"
    await flow.process(ExchangeTurnResult(detected_intent="credit_limit_query"))
    assert flow.state.current_agent == "credit"


async def test_exchange_failure_preserves_state(data_dir):
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow)
    await flow.process(CreditTurnResult(transition_request="go_to_exchange", currency="USD"))
    assert flow.state.current_agent == "credit"
    assert flow.state.authenticated
    assert flow.state.last_error_code == "exchange_unavailable"
