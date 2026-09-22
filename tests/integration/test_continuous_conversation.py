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
        assert "**Consultar" in reply
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
    assert messages[-2] == {"role": "assistant", "content": first}
    assert messages[-1] == {"role": "user", "content": "sim"}
    assert "00000000001" not in json.dumps(messages)
    assert "1990-01-15" not in json.dumps(messages)
    assert flow.state.current_agent == "triage"
