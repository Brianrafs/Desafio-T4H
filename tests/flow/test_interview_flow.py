import pytest

from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult
from banco_agil.models.errors import RepositoryError
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository


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
        await flow.process(InterviewTurnResult(**values))
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
    await flow.process(CreditTurnResult(interview_accepted=accept))
    assert flow.state.current_agent == ("triage" if accept is False else "credit")
    assert flow.state.interview is None


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
