from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import (
    CreditTurnResult,
    ExchangeTurnResult,
    InterviewTurnResult,
    TriageTurnResult,
)


async def _authenticate(flow: BankingFlow, intent="credit_limit_query") -> str:
    return await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent=intent,
        )
    )


async def test_credit_evaluation_question_does_not_start_increase(data_dir):
    flow = BankingFlow(data_dir)
    await _authenticate(flow)

    response = await flow.process(
        TriageTurnResult(
            detected_intent="credit_limit_increase",
            information_topic="credit_evaluation",
        )
    )

    assert "limite total solicitado" in response
    assert "não garante aprovação" in response
    assert flow.state.current_agent == "triage"
    assert not flow.state.credit.awaiting_requested_limit
    assert flow.tools.credit.requests.read() == []


async def test_information_preserves_and_resumes_pending_amount(data_dir):
    flow = BankingFlow(data_dir)
    await _authenticate(flow, intent="credit_limit_increase")

    response = await flow.process(CreditTurnResult(information_topic="credit_evaluation"))

    assert "limite total solicitado" in response
    assert "qual **limite total**" in response.casefold()
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit


async def test_internal_details_receive_a_bounded_answer(data_dir):
    flow = BankingFlow(data_dir)

    response = await flow.process(TriageTurnResult(information_topic="internal_details"))

    assert "como o atendimento funciona" in response
    assert "código, prompts, ferramentas ou arquitetura" in response
    assert not flow.state.authenticated


async def test_capabilities_can_be_explained_before_authentication(data_dir):
    flow = BankingFlow(data_dir)

    response = await flow.process(TriageTurnResult(information_topic="capabilities"))

    assert "consultar seu limite" in response
    assert "cotação" in response
    assert "CPF" not in response


async def test_information_during_authentication_resumes_cpf_request(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(detected_intent="credit_limit_query"))

    response = await flow.process(TriageTurnResult(information_topic="authentication"))

    assert "cadastro correto" in response
    assert "pode me informar seu **CPF**?" in response
    assert flow.state.pending_intent == "credit_limit_query"


async def test_information_resumes_birth_date_after_unsolicited_cpf(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(cpf="00000000001"))

    response = await flow.process(TriageTurnResult(information_topic="authentication"))

    assert "qual é sua **data de nascimento**?" in response
    assert flow.state.authentication.cpf == "00000000001"


async def test_information_during_interview_resumes_current_question(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_increase",
            requested_limit=4000,
        )
    )
    await flow.process(CreditTurnResult(interview_accepted=True))

    response = await flow.process(InterviewTurnResult(information_topic="credit_interview"))

    assert "cinco perguntas" in response
    assert "qual é sua **renda mensal**?" in response
    assert flow.state.current_agent == "credit_interview"
    assert flow.state.interview.next_missing_field() == "monthly_income"


async def test_information_during_exchange_resumes_currency_request(data_dir):
    flow = BankingFlow(data_dir)
    await _authenticate(flow, intent="exchange_rate")

    response = await flow.process(ExchangeTurnResult(information_topic="supported_currencies"))

    assert "**dólar (USD)**" in response
    assert "qual moeda você gostaria de consultar" in response
    assert flow.state.current_agent == "exchange"
