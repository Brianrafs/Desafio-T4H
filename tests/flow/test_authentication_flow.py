import pytest

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, TriageTurnResult
from banco_agil.models.errors import RepositoryError
from banco_agil.models.responses import CriticalFailure, FlowOutcome, OutcomeDirective
from banco_agil.responses.briefs import build_response_brief


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


async def test_successful_authentication_confirms_first_name_once(data_dir):
    flow = BankingFlow(data_dir)

    first = await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_query",
        )
    )
    second = await flow.process(TriageTurnResult(detected_intent="credit_limit_query"))

    assert [item.event for item in first.directives] == [
        "authentication_succeeded",
        "credit_limit_found",
    ]
    assert first.protected_values == {"customer_first_name": "Ana", "current_limit": "R$ 1.000,00"}
    assert "Ana" not in build_response_brief(first, "neutral").model_dump_json()
    assert [item.event for item in second.directives] == ["credit_limit_found"]
    assert "customer_first_name" not in second.protected_values


async def test_authentication_confirmation_survives_following_operation_error(data_dir):
    flow = BankingFlow(data_dir)

    response = await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=0,
        )
    )

    assert [item.event for item in response.directives] == [
        "authentication_succeeded",
        "invalid_input",
        "resume_pending_step",
    ]
    assert response.protected_values == {"customer_first_name": "Ana"}
    assert response.next_step == "await_requested_limit"
    assert flow.state.authenticated


async def test_third_failure_ends_session(data_dir):
    flow = BankingFlow(data_dir)
    invalid = TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")
    for remaining in (2, 1):
        retry = await flow.process(invalid)
        assert retry.directives[0].event == "authentication_retry"
        assert retry.directives[0].public_context == {"remaining_attempts": remaining}
        assert retry.next_step == "await_cpf"
        assert retry.expected_questions == 1
        assert retry.protected_values == {}
    failure = await flow.process(invalid)
    assert failure == CriticalFailure(code="auth_attempts_exhausted")
    assert flow.state.authentication_attempts == 3
    assert flow.state.status == "finished"
    before = flow.state.model_dump()
    closed = await flow.process(TriageTurnResult(cpf="00000000001", birth_date="1990-01-15"))
    assert closed == CriticalFailure(code="session_finished")
    assert flow.state.model_dump() == before


async def test_end_before_authentication(data_dir):
    flow = BankingFlow(data_dir)
    outcome = await flow.process(TriageTurnResult(end_requested=True))
    assert [item.event for item in outcome.directives] == ["conversation_closed"]
    assert outcome.next_step == "finished"
    assert outcome.expected_questions == 0
    assert flow.state.status == "finished"


@pytest.mark.parametrize("intent", ["go_to_credit", "go_to_exchange", "start_credit_interview"])
async def test_transition_cannot_bypass_authentication(data_dir, intent):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(transition_request=intent))
    assert not flow.state.authenticated
    assert flow.state.current_agent == "triage"


async def test_incomplete_authentication_does_not_consume_attempt(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(cpf="00000000001"))
    await flow.process(TriageTurnResult())
    assert flow.state.authentication_attempts == 0
    assert flow.state.authentication.cpf == "00000000001"


async def test_incompatible_turn_result_records_controlled_error(data_dir):
    flow = BankingFlow(data_dir)
    before = flow.state.model_dump(exclude={"last_error_code"})
    response = await flow.process(CreditTurnResult(detected_intent="credit_limit_query"))
    assert response == CriticalFailure(code="invalid_llm_output")
    assert flow.state.last_error_code == "invalid_llm_output"
    assert flow.state.model_dump(exclude={"last_error_code"}) == before


@pytest.mark.parametrize(
    "result,event,next_step",
    [
        (TriageTurnResult(), "welcome", "idle"),
        (TriageTurnResult(detected_intent="credit_limit_query"), "request_cpf", "await_cpf"),
        (TriageTurnResult(birth_date="1990-01-15"), "request_cpf", "await_cpf"),
        (TriageTurnResult(cpf="00000000001"), "request_birth_date", "await_birth_date"),
    ],
)
async def test_triage_requests_only_the_pending_authentication_field(
    data_dir, result, event, next_step
):
    outcome = await BankingFlow(data_dir).process(result)
    assert isinstance(outcome, FlowOutcome)
    assert [item.event for item in outcome.directives] == [event]
    assert outcome.next_step == next_step
    assert outcome.expected_questions == 1
    assert outcome.protected_values == {}


async def test_authenticated_triage_offers_options_without_repeating_name(data_dir):
    flow = BankingFlow(data_dir)
    first = await flow.process(TriageTurnResult(cpf="00000000001", birth_date="1990-01-15"))
    second = await flow.process(TriageTurnResult())
    assert [item.event for item in first.directives] == ["authentication_succeeded", "show_options"]
    assert first.protected_values == {"customer_first_name": "Ana"}
    assert first.expected_questions == 1
    assert [item.event for item in second.directives] == ["show_options"]
    assert second.protected_values == {}


@pytest.mark.parametrize("name,code", [("Outra", "invalid_internal_state"), ("Ana", None)])
async def test_authentication_prefix_rejects_only_divergent_protected_collision(
    data_dir, monkeypatch, name, code
):
    async def credit_outcome(self, result):
        return FlowOutcome(
            directives=(OutcomeDirective(event="credit_limit_found"),),
            specialist="credit",
            next_step="idle",
            protected_values={"customer_first_name": name, "current_limit": "R$ 1.000,00"},
        )

    monkeypatch.setattr(BankingFlow, "_credit", credit_outcome)
    outcome = await BankingFlow(data_dir).process(
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
        )
    )
    if code:
        assert outcome == CriticalFailure(code=code)
    else:
        assert outcome.protected_values == {
            "customer_first_name": "Ana",
            "current_limit": "R$ 1.000,00",
        }
        assert [item.event for item in outcome.directives] == [
            "authentication_succeeded",
            "credit_limit_found",
        ]


async def test_authentication_repository_failure_returns_critical_contract(data_dir, monkeypatch):
    flow = BankingFlow(data_dir)

    def fail(*args):
        raise RepositoryError()

    monkeypatch.setattr(flow.tools.authentication, "authenticate", fail)
    outcome = await flow.process(TriageTurnResult(cpf="00000000001", birth_date="1990-01-15"))
    assert outcome == CriticalFailure(code="persistence_failure")
    assert not flow.state.authenticated
    assert flow.state.authentication_attempts == 0
