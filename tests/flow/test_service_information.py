from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import (
    CreditTurnResult,
    ExchangeTurnResult,
    InterviewTurnResult,
    TriageTurnResult,
)
from banco_agil.responses.briefs import build_response_brief
from banco_agil.responses.renderer import render_response


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

    assert [item.event for item in response.directives] == ["service_information"]
    assert response.directives[0].public_context == {"topic": "credit_evaluation"}
    assert response.next_step == "idle"
    assert response.expected_questions == 0
    brief = build_response_brief(response, "neutral")
    assert "limite total solicitado" in brief.directives[0].communication_goal
    assert "não garante aprovação" in render_response(response, brief, None).text
    assert flow.state.current_agent == "triage"
    assert not flow.state.credit.awaiting_requested_limit
    assert flow.tools.credit.requests.read() == []


async def test_information_preserves_and_resumes_pending_amount(data_dir):
    flow = BankingFlow(data_dir)
    await _authenticate(flow, intent="credit_limit_increase")

    response = await flow.process(CreditTurnResult(information_topic="credit_evaluation"))

    assert [item.event for item in response.directives] == [
        "service_information",
        "resume_pending_step",
    ]
    assert response.next_step == "await_requested_limit"
    assert response.expected_questions == 1
    assert (
        "qual **limite total**"
        in render_response(
            response, build_response_brief(response, "neutral"), None
        ).text.casefold()
    )
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit


async def test_internal_details_receive_a_bounded_answer(data_dir):
    flow = BankingFlow(data_dir)

    response = await flow.process(TriageTurnResult(information_topic="internal_details"))

    assert [item.event for item in response.directives] == ["service_information"]
    assert response.directives[0].public_context == {"topic": "internal_details"}
    brief = build_response_brief(response, "neutral")
    assert "framework" not in brief.model_dump_json().casefold()
    assert "provider" not in brief.model_dump_json().casefold()
    assert "prompt" not in brief.model_dump_json().casefold()
    assert "ferramenta" not in brief.model_dump_json().casefold()
    assert "como o atendimento funciona" in render_response(response, brief, None).text
    assert not flow.state.authenticated


async def test_capabilities_can_be_explained_before_authentication(data_dir):
    flow = BankingFlow(data_dir)

    response = await flow.process(TriageTurnResult(information_topic="capabilities"))

    assert [item.event for item in response.directives] == ["service_information"]
    assert (
        "consultar seu limite"
        in render_response(response, build_response_brief(response, "neutral"), None).text
    )


async def test_information_during_authentication_resumes_cpf_request(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(detected_intent="credit_limit_query"))

    response = await flow.process(TriageTurnResult(information_topic="authentication"))

    assert [item.event for item in response.directives] == [
        "service_information",
        "resume_pending_step",
    ]
    assert response.next_step == "await_cpf"
    assert response.expected_questions == 1
    assert (
        "Pode me informar seu **CPF**?"
        in render_response(response, build_response_brief(response, "neutral"), None).text
    )
    assert flow.state.pending_intent == "credit_limit_query"


async def test_information_resumes_birth_date_after_unsolicited_cpf(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(cpf="00000000001"))

    response = await flow.process(TriageTurnResult(information_topic="authentication"))

    assert response.next_step == "await_birth_date"
    assert response.expected_questions == 1
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

    assert [item.event for item in response.directives] == [
        "service_information",
        "resume_pending_step",
    ]
    assert response.next_step == "await_interview_field"
    assert response.directives[1].public_context == {"field": "monthly_income"}
    assert (
        "qual é sua **renda mensal**?"
        in render_response(response, build_response_brief(response, "neutral"), None).text
    )
    assert flow.state.current_agent == "credit_interview"
    assert flow.state.interview.next_missing_field() == "monthly_income"


async def test_information_during_exchange_resumes_currency_request(data_dir):
    flow = BankingFlow(data_dir)
    await _authenticate(flow, intent="exchange_rate")

    response = await flow.process(ExchangeTurnResult(information_topic="supported_currencies"))

    assert [item.event for item in response.directives] == [
        "service_information",
        "resume_pending_step",
    ]
    assert response.next_step == "await_currency"
    assert (
        "Qual moeda você gostaria de consultar"
        in render_response(response, build_response_brief(response, "neutral"), None).text
    )
    assert flow.state.current_agent == "exchange"
