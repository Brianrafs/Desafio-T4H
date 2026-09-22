import json

import httpx

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import TriageTurnResult
from banco_agil.models.errors import LLMError, RepositoryError
from banco_agil.services.exchange_service import ExchangeService


async def test_logs_do_not_contain_personal_data(data_dir, caplog):
    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
        )
    )
    records = [
        json.loads(record.message) for record in caplog.records if record.name == "banco_agil"
    ]
    assert {row["event"] for row in records} >= {
        "session_started",
        "authentication_attempt",
        "authentication_succeeded",
        "agent_transition",
    }
    for sensitive in ("00000000001", "1990-01-15", "Demonstração"):
        assert sensitive not in caplog.text


async def test_repository_error_keeps_authentication_context(data_dir, monkeypatch):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(cpf="00000000001"))

    def fail(*args):
        raise RepositoryError()

    monkeypatch.setattr(flow._tools.authentication, "authenticate", fail)
    await flow.process(TriageTurnResult(birth_date="1990-01-15"))
    assert flow.state.authentication.cpf == "00000000001"
    assert flow.state.authentication_attempts == 0


async def test_llm_error_preserves_state_and_allows_exit(data_dir):
    class BrokenProvider:
        async def interpret(self, message, state):
            state.authenticated = False
            raise LLMError()

    flow = BankingFlow(data_dir)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
        )
    )
    conversation = Conversation(flow, BrokenProvider())
    await conversation.send("Olá")
    assert flow.state.authenticated
    assert flow.state.current_agent == "credit"
    await conversation.send("encerrar")
    assert flow.state.status == "finished"


async def test_authentication_is_preserved_when_following_exchange_fails(data_dir):
    exchange = ExchangeService(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    flow = BankingFlow(data_dir, exchange)
    await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="exchange_rate",
            currency="USD",
        )
    )
    assert flow.state.authenticated
    assert flow.state.current_agent == "triage"
    assert flow.state.pending_intent == "exchange_rate"
