import json

import httpx

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import TriageTurnResult
from banco_agil.providers.groq import GroqProvider
from banco_agil.services.exchange_service import ExchangeService


async def test_four_operations_without_reauthentication_or_reusing_amount(data_dir):
    exchange = ExchangeService(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"EURBRL": {"bid": "6"}})
        )
    )
    flow = BankingFlow(data_dir, exchange)
    original_id = flow.state.session_id
    for result in [
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
        ),
        TriageTurnResult(currency="EUR"),
        TriageTurnResult(requested_limit=2000),
        TriageTurnResult(detected_intent="credit_limit_query"),
    ]:
        reply = await flow.process(result)
        assert flow.state.current_agent == "triage"
        assert flow.state.authenticated
        assert flow.state.session_id == original_id
        assert reply
        assert flow.state.credit.requested_limit is None
    await flow.process(TriageTurnResult(detected_intent="credit_limit_increase"))
    assert flow.state.credit.awaiting_requested_limit
    assert flow.state.credit.requested_limit is None
    assert len(flow.tools.credit.requests.read()) == 1


async def test_follow_up_has_last_reply_without_old_credentials(data_dir):
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        output = (
            {
                "cpf": "00000000001",
                "birth_date": "1990-01-15",
                "detected_intent": "credit_limit_query",
            }
            if len(bodies) == 1
            else {}
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    flow = BankingFlow(data_dir)
    conversation = Conversation(
        flow, GroqProvider("test", "test", flow.tools, httpx.MockTransport(respond))
    )
    first = await conversation.send("Meu limite, CPF 00000000001, nascimento 1990-01-15")
    await conversation.send("sim")
    messages = bodies[1]["messages"]
    assert messages[-2]["role"] == "assistant"
    assert "Seu limite de crédito atual" in messages[-2]["content"]
    assert messages[-2]["content"] != first
    assert messages[-1] == {"role": "user", "content": "sim"}
    serialized_messages = json.dumps(messages)
    assert "00000000001" not in serialized_messages
    assert "1990-01-15" not in serialized_messages
    assert "Ana" not in serialized_messages
    assert "Demonstração" not in serialized_messages
    assert flow.state.current_agent == "triage"


async def test_json_failure_keeps_authenticated_session_and_last_question(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_increase"
        )
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
    )
    conversation = Conversation(flow, GroqProvider("test", "test", flow.tools, transport))
    conversation.last_reply = "Qual limite total você deseja?"
    await conversation.send("Quero dois mil")
    assert flow.state.authenticated
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit
    assert flow.state.last_error_code == "invalid_llm_output"
    assert conversation.last_reply == "Qual limite total você deseja?"
    assert flow.tools.credit.requests.read() == []


async def test_model_message_is_ignored_for_deterministic_information(data_dir):
    class InformationalProvider:
        async def interpret(self, message, state, *, last_reply=None):
            return TriageTurnResult(
                information_topic="internal_details",
                message="Uso CrewAI com agentes especializados e Groq como modelo.",
            )

    conversation = Conversation(BankingFlow(data_dir), InformationalProvider())

    response = await conversation.send("Como vocês implementaram a Lia?")

    assert "CrewAI" not in response
    assert "Groq" not in response
    assert "não forneço detalhes internos" in response
