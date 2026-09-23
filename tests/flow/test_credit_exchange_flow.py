import httpx
import pytest

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.flow.transitions import transition
from banco_agil.models.agent_outputs import CreditTurnResult, ExchangeTurnResult, TriageTurnResult
from banco_agil.models.errors import RepositoryError, ScoreRangeNotFoundError
from banco_agil.models.responses import CriticalFailure, GeneratedMessage
from banco_agil.models.state import TransitionIntent
from banco_agil.responses.briefs import build_response_brief
from banco_agil.responses.renderer import render_response
from banco_agil.services.exchange_service import ExchangeService


async def authenticate(flow, intent="credit_limit_query"):
    return await flow.process(
        TriageTurnResult(cpf="00000000001", birth_date="1990-01-15", detected_intent=intent)
    )


async def test_query_and_increase(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)
    outcome = await flow.process(
        TriageTurnResult(detected_intent="credit_limit_increase", requested_limit=2000)
    )
    assert [item.event for item in outcome.directives] == ["credit_increase_approved"]
    assert outcome.protected_values == {"new_limit": "R$ 2.000,00"}
    assert outcome.specialist == "credit"
    assert outcome.next_step == "idle"
    assert outcome.expected_questions == 0
    assert flow.state.credit.last_request_status == "aprovado"
    assert flow._tools.credit.get_limit("00000000001") == 2000


async def test_rejected_outcome_missing_optional_value_falls_back_without_exception(
    data_dir, caplog
):
    flow = BankingFlow(data_dir)
    await authenticate(flow, "credit_limit_increase")
    outcome = await flow.process(CreditTurnResult(requested_limit=4000))
    assert [item.event for item in outcome.directives] == [
        "credit_increase_rejected_offer_interview"
    ]
    assert outcome.protected_values == {}
    brief = build_response_brief(outcome, "neutral")
    before = flow.state.model_dump()
    generated = "Seu limite continua {{current_limit}}. Quer fazer a entrevista?"

    rendered = render_response(outcome, brief, GeneratedMessage(text=generated))

    assert rendered.used_fallback
    assert rendered.fallback_reason == "unknown_placeholder"
    assert "current_limit" not in brief.allowed_placeholders
    assert "{{" not in rendered.text
    assert "Quer continuar?" in rendered.text
    assert generated not in caplog.text
    assert flow.state.model_dump() == before
    assert len(flow.tools.credit.requests.read()) == 1


async def test_credit_query_returns_confirmed_limit_outcome(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow, "credit_limit_increase")

    outcome = await flow.process(CreditTurnResult(detected_intent="credit_limit_query"))

    assert [item.event for item in outcome.directives] == ["credit_limit_found"]
    assert outcome.protected_values == {"current_limit": "R$ 1.000,00"}
    assert outcome.specialist == "credit"
    assert outcome.next_step == "idle"
    assert outcome.expected_questions == 0
    assert flow.state.current_agent == "triage"


async def test_invalid_limit_requests_correction_without_financial_effect(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)
    outcome = await flow.process(TriageTurnResult(requested_limit=0))

    assert outcome.directives[0].event == "invalid_input"
    assert outcome.next_step == "await_requested_limit"
    assert outcome.expected_questions == 1
    assert outcome.protected_values == {}
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit
    assert flow.state.last_error_code == "invalid_limit"
    assert flow.tools.credit.requests.read() == []
    assert flow.tools.credit.get_limit("00000000001") == 1000

    corrected = await flow.process(CreditTurnResult(requested_limit=2000))
    assert corrected.directives[0].event == "credit_increase_approved"
    assert len(flow.tools.credit.requests.read()) == 1


async def test_credit_request_without_amount_has_one_question(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)

    outcome = await flow.process(TriageTurnResult(detected_intent="credit_limit_increase"))

    assert [item.event for item in outcome.directives] == ["request_credit_limit"]
    assert outcome.next_step == "await_requested_limit"
    assert outcome.expected_questions == 1
    assert flow.tools.credit.requests.read() == []


async def test_credit_without_pending_operation_returns_options_outcome(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)
    transition(flow.state, TransitionIntent.GO_TO_CREDIT)

    outcome = await flow.process(CreditTurnResult())

    assert [item.event for item in outcome.directives] == ["show_options"]
    assert outcome.specialist == "triage"
    assert outcome.next_step == "idle"
    assert outcome.expected_questions == 1


async def test_authentication_and_credit_outcome_keep_private_values_out_of_brief(data_dir, caplog):
    flow = BankingFlow(data_dir)

    outcome = await authenticate(flow)

    assert [item.event for item in outcome.directives] == [
        "authentication_succeeded",
        "credit_limit_found",
    ]
    assert outcome.protected_values == {
        "customer_first_name": "Ana",
        "current_limit": "R$ 1.000,00",
    }
    public = build_response_brief(outcome, "neutral").model_dump_json()
    for value in ("Ana", "1.000", "00000000001", "1990-01-15"):
        assert value not in public
        assert value not in caplog.text
    assert all(item.public_context == {} for item in outcome.directives)


@pytest.mark.parametrize(
    ("error", "code"),
    [(RepositoryError, "persistence_failure"), (ScoreRangeNotFoundError, "invalid_internal_state")],
)
async def test_credit_failure_is_critical_and_preserves_pending_step(
    data_dir, monkeypatch, error, code
):
    flow = BankingFlow(data_dir)
    await authenticate(flow, "credit_limit_increase")
    before = flow.state.model_dump(exclude={"last_error_code"})

    def fail(*args):
        raise error()

    monkeypatch.setattr(flow.tools.credit, "request_increase", fail)
    outcome = await flow.process(CreditTurnResult(requested_limit=2000))

    assert isinstance(outcome, CriticalFailure)
    assert outcome.code == code
    assert flow.state.last_error_code == error.code
    assert flow.state.model_dump(exclude={"last_error_code"}) == before
    assert flow.tools.credit.requests.read() == []


async def test_topic_switch_and_forbidden_interview(data_dir):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"USDBRL": {"bid": "5"}})
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "credit_limit_increase")
    result = await flow.process(
        CreditTurnResult(transition_request="go_to_exchange", currency="USD")
    )
    assert [item.event for item in result.directives] == ["exchange_quote_found"]
    assert result.protected_values["exchange_rate"] == "1 USD = R$ 5.0000"
    assert flow.state.current_agent == "triage"
    await flow.process(TriageTurnResult(detected_intent="exchange_rate"))
    await flow.process(ExchangeTurnResult(transition_request="start_credit_interview"))
    assert flow.state.current_agent == "exchange"
    assert flow.state.last_error_code == "unauthorized"
    await flow.process(ExchangeTurnResult(detected_intent="credit_limit_query"))
    assert flow.state.current_agent == "triage"


async def test_exchange_failure_preserves_state(data_dir):
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "credit_limit_increase")
    outcome = await flow.process(
        CreditTurnResult(transition_request="go_to_exchange", currency="USD")
    )
    assert isinstance(outcome, CriticalFailure)
    assert outcome.code == "external_service_unavailable"
    assert flow.state.current_agent == "credit"
    assert flow.state.authenticated
    assert flow.state.last_error_code == "exchange_unavailable"


async def test_switching_to_exchange_explains_incomplete_credit_request(data_dir):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"EURBRL": {"bid": "6"}})
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "credit_limit_increase")
    assert flow.state.credit.awaiting_requested_limit

    reply = await flow.process(
        CreditTurnResult(transition_request="go_to_exchange", currency="EUR")
    )

    assert [item.event for item in reply.directives] == ["exchange_quote_found"]
    assert reply.next_step == "idle"
    assert reply.directives[0].public_context == {"credit_request_interrupted": True}
    brief = build_response_brief(reply, "neutral")
    assert "interrompido" in brief.directives[0].communication_goal
    assert "pedido de aumento ficou interrompido" in render_response(reply, brief, None).text
    assert not flow.state.credit.awaiting_requested_limit
    assert flow.state.current_agent == "triage"


async def test_exchange_does_not_deny_submission_after_partial_write(data_dir, monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"EURBRL": {"bid": "6"}})
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "credit_limit_increase")
    save = flow.tools.credit.requests.save

    def fail_save(request):
        raise RepositoryError()

    monkeypatch.setattr(flow.tools.credit.requests, "save", fail_save)
    await flow.process(CreditTurnResult(requested_limit=2000))
    assert flow.tools.credit.requests.read()[0].status_pedido == "pendente"
    reply = await flow.process(
        CreditTurnResult(currency="EUR", transition_request="go_to_exchange")
    )
    assert [item.event for item in reply.directives] == ["exchange_quote_found"]
    monkeypatch.setattr(flow.tools.credit.requests, "save", save)
    await flow.process(TriageTurnResult(detected_intent="credit_limit_query"))
    assert flow.tools.credit.requests.read()[0].status_pedido == "aprovado"
    assert len(flow.tools.credit.requests.read()) == 1


async def test_exchange_outcome_protects_quote_and_timestamp(data_dir, caplog):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"USDBRL": {"bid": "5", "timestamp": "1750000000"}}
        )
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "exchange_rate")

    outcome = await flow.process(ExchangeTurnResult(currency="USD"))

    assert [item.event for item in outcome.directives] == ["exchange_quote_found"]
    assert outcome.protected_values["exchange_rate"] == "1 USD = R$ 5.0000"
    assert "15/06/2025" in outcome.protected_values["quote_timestamp"]
    assert outcome.expected_questions == 0
    public = outcome.model_dump_json(exclude={"protected_values"})
    public += build_response_brief(outcome, "neutral").model_dump_json()
    for sensitive in ("5.0000", "1750000000", "15/06/2025"):
        assert sensitive not in public
        assert sensitive not in caplog.text
    assert outcome.directives[0].public_context == {}
    assert (
        "interrompido"
        not in render_response(outcome, build_response_brief(outcome, "neutral"), None).text
    )


async def test_exchange_without_currency_requests_one_question(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow, "exchange_rate")

    outcome = await flow.process(ExchangeTurnResult())

    assert [item.event for item in outcome.directives] == ["request_currency"]
    assert outcome.next_step == "await_currency"
    assert outcome.expected_questions == 1


async def test_unsupported_currency_is_composable_and_keeps_exchange_step(data_dir):
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "exchange_rate")

    outcome = await flow.process(ExchangeTurnResult(currency="USD"))

    assert [item.event for item in outcome.directives] == ["unsupported_currency"]
    assert outcome.next_step == "await_currency"
    assert outcome.expected_questions == 1
    assert flow.state.current_agent == "exchange"
    assert flow.state.last_error_code == "invalid_currency"
