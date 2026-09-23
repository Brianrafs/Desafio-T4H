import pytest

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult
from banco_agil.models.errors import RepositoryError
from banco_agil.models.responses import CriticalFailure, GeneratedMessage
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.responses.briefs import build_response_brief
from banco_agil.responses.renderer import render_response


async def rejected_flow(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=4000,
        )
    )
    assert flow.state.credit.last_request_status == "rejeitado"
    return flow


async def test_interview_start_returns_intro_and_first_question(data_dir):
    flow = await rejected_flow(data_dir)
    outcome = await flow.process(CreditTurnResult(interview_accepted=True))

    assert [item.event for item in outcome.directives] == [
        "interview_started",
        "interview_question",
    ]
    assert outcome.directives[-1].public_context == {"field": "monthly_income"}
    assert outcome.specialist == "credit_interview"
    assert outcome.next_step == "await_interview_field"
    assert outcome.expected_questions == 1


async def test_interview_ignores_other_extracted_fields_when_advancing_state(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    outcome = await flow.process(InterviewTurnResult(monthly_income=5000, employment_type="formal"))

    assert flow.state.interview.monthly_income == 5000
    assert flow.state.interview.employment_type is None
    assert [item.event for item in outcome.directives] == ["interview_question"]
    assert outcome.directives[-1].public_context == {"field": "employment_type"}
    assert outcome.next_step == "await_interview_field"
    assert outcome.expected_questions == 1


async def test_interview_missing_answer_repeats_only_current_field(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    outcome = await flow.process(InterviewTurnResult(employment_type="formal"))

    assert flow.state.interview.monthly_income is None
    assert flow.state.interview.employment_type is None
    assert [item.event for item in outcome.directives] == ["interview_question"]
    assert outcome.directives[0].public_context == {"field": "monthly_income"}


async def test_golden_path(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
        dict(has_active_debt=False),
    ]:
        outcome = await flow.process(InterviewTurnResult(**values))
    assert [item.event for item in outcome.directives] == ["interview_reanalysis_approved"]
    assert outcome.protected_values == {"new_limit": "R$ 4.000,00"}
    assert outcome.specialist == "credit"
    assert outcome.next_step == "idle"
    assert outcome.expected_questions == 0
    assert flow.state.current_agent == "triage"
    assert flow.state.interview.completed
    assert flow.state.interview.score_persisted
    customer = CustomerRepository(data_dir).require("00000000001")
    assert customer.score_credito == 800
    assert customer.limite_credito == 4000
    requests = CreditRequestRepository(data_dir).read()
    assert [row.status_pedido for row in requests] == ["rejeitado", "aprovado"]


async def test_only_expected_field_is_accepted(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    await flow.process(
        InterviewTurnResult(
            monthly_income=10000,
            employment_type="formal",
            fixed_expenses=0,
            dependents=0,
            has_active_debt=False,
        )
    )
    assert flow.state.interview.monthly_income == 10000
    assert flow.state.interview.employment_type is None
    assert not flow.state.interview.is_complete()


@pytest.mark.parametrize("accept", [False, None])
async def test_no_interview_without_acceptance(data_dir, accept):
    flow = await rejected_flow(data_dir)
    response = await flow.process(CreditTurnResult(interview_accepted=accept))
    assert flow.state.current_agent == ("triage" if accept is False else "credit")
    assert flow.state.interview is None
    if accept is False:
        assert [item.event for item in response.directives] == ["credit_increase_rejected_final"]
        assert response.specialist == "credit"
        assert response.next_step == "idle"
        assert response.expected_questions == 0


@pytest.mark.parametrize("completed", [False, True])
async def test_renderer_rejects_new_interview_after_refusal_or_completion(data_dir, completed):
    flow = await rejected_flow(data_dir)
    outcome = await flow.process(CreditTurnResult(interview_accepted=completed))
    if completed:
        for values in [
            dict(monthly_income=1000),
            dict(employment_type="desempregado"),
            dict(fixed_expenses=1000),
            dict(dependents=5),
            dict(has_active_debt=True),
        ]:
            outcome = await flow.process(InterviewTurnResult(**values))
        assert flow.state.interview.completed
        assert outcome.directives[0].event == "interview_reanalysis_rejected"
    else:
        assert outcome.directives[0].event == "credit_increase_rejected_final"
    brief = build_response_brief(outcome, "neutral")
    assert "start_credit_interview" not in brief.allowed_actions
    before = flow.state.model_dump()

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Não consegui aprovar. Podemos fazer outra entrevista financeira."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "outra entrevista" not in rendered.text
    assert "consultar seu limite" in rendered.text
    assert flow.state.model_dump() == before


async def test_repository_failure_submitting_interview_is_critical_and_rolls_back(
    data_dir, monkeypatch
):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
    ]:
        await flow.process(InterviewTurnResult(**values))
    before = flow.state.model_dump(exclude={"last_error_code"})

    def fail(*args):
        raise RepositoryError()

    monkeypatch.setattr(flow.tools.score, "submit", fail)
    outcome = await flow.process(InterviewTurnResult(has_active_debt=False))

    assert isinstance(outcome, CriticalFailure)
    assert outcome.code == "persistence_failure"
    assert flow.state.last_error_code == "repository_error"
    assert flow.state.model_dump(exclude={"last_error_code"}) == before
    assert flow.state.authenticated
    assert flow.state.current_agent == "credit_interview"


async def test_no_interview_without_rejection(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_increase"
        )
    )
    await flow.process(CreditTurnResult(interview_accepted=True))
    assert flow.state.current_agent == "credit"
    assert flow.state.interview is None


async def test_end_during_interview(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    await flow.process(InterviewTurnResult(end_requested=True))
    assert flow.state.status == "finished"
    assert CustomerRepository(data_dir).require("00000000001").score_credito == 400


async def test_retry_after_interview_does_not_duplicate_request(data_dir, monkeypatch):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
    ]:
        await flow.process(InterviewTurnResult(**values))
    save = flow._tools.credit.requests.save

    def fail(request):
        raise RepositoryError()

    monkeypatch.setattr(flow._tools.credit.requests, "save", fail)
    await flow.process(InterviewTurnResult(has_active_debt=False))
    assert flow.state.current_agent == "credit"
    assert flow.state.interview.completed
    monkeypatch.setattr(flow._tools.credit.requests, "save", save)
    await flow.process(CreditTurnResult())
    assert [row.status_pedido for row in flow._tools.credit.requests.read()] == [
        "rejeitado",
        "aprovado",
    ]


async def test_ambiguous_interview_answer_keeps_confirmation_pending(data_dir):
    flow = await rejected_flow(data_dir)
    response = await flow.process(CreditTurnResult(interview_accepted=None))
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_interview_confirmation
    assert flow.state.interview is None
    assert [item.event for item in response.directives] == [
        "credit_increase_rejected_offer_interview"
    ]
    assert response.next_step == "await_interview_confirmation"
    assert response.expected_questions == 1
    assert response.protected_values == {}


async def test_rejected_reanalysis_finishes_without_offering_another_interview(data_dir):
    flow = BankingFlow(data_dir)
    first_response = await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=15000,
        )
    )
    assert first_response.directives[-1].event == "credit_increase_rejected_offer_interview"
    assert first_response.next_step == "await_interview_confirmation"
    assert first_response.expected_questions == 1

    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
        dict(has_active_debt=False),
    ]:
        final_response = await flow.process(InterviewTurnResult(**values))

    assert flow.state.interview.completed
    assert flow.state.current_agent == "triage"
    assert not flow.state.credit.awaiting_interview_confirmation
    assert [item.event for item in final_response.directives] == ["interview_reanalysis_rejected"]
    assert final_response.next_step == "idle"
    assert final_response.expected_questions == 0
    assert final_response.protected_values == {}


async def test_completed_interview_is_not_offered_again_in_same_session(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=15000,
        )
    )
    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
        dict(has_active_debt=False),
    ]:
        await flow.process(InterviewTurnResult(**values))

    response = await flow.process(
        TriageTurnResult(detected_intent="credit_limit_increase", requested_limit=15000)
    )

    assert flow.state.current_agent == "triage"
    assert not flow.state.credit.awaiting_interview_confirmation
    assert [item.event for item in response.directives] == ["credit_increase_rejected_final"]
    assert response.next_step == "idle"
    assert response.expected_questions == 0


async def test_later_approved_request_is_not_described_as_interview_reanalysis(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=15000,
        )
    )
    await flow.process(CreditTurnResult(interview_accepted=True))
    for values in [
        dict(monthly_income=10000),
        dict(employment_type="formal"),
        dict(fixed_expenses=1000),
        dict(dependents=0),
        dict(has_active_debt=False),
    ]:
        await flow.process(InterviewTurnResult(**values))

    response = await flow.process(
        TriageTurnResult(detected_intent="credit_limit_increase", requested_limit=4000)
    )

    assert flow.state.credit.last_request_status == "aprovado"
    assert [item.event for item in response.directives] == ["credit_increase_approved"]


async def test_declined_interview_can_be_offered_after_another_rejected_request(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=False))

    response = await flow.process(
        TriageTurnResult(detected_intent="credit_limit_increase", requested_limit=4000)
    )

    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_interview_confirmation
    assert [item.event for item in response.directives] == [
        "credit_increase_rejected_offer_interview"
    ]
