import json
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult
from banco_agil.providers.groq import GroqProvider
from banco_agil.services.exchange_service import ExchangeService

APP = Path(__file__).parents[2] / "app.py"


class ScriptedProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    async def interpret(self, message, state):
        return next(self.outputs)


def test_app_starts_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert app.title[0].value == "Banco Ágil"
    app.button(key="end_conversation").click().run()
    assert not app.exception
    assert app.session_state.conversation.flow.state.status == "finished"


def test_golden_path_through_chat(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    provider = ScriptedProvider(
        [
            TriageTurnResult(
                cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
            ),
            CreditTurnResult(requested_limit=4000),
            CreditTurnResult(interview_accepted=True),
            InterviewTurnResult(monthly_income=10000),
            InterviewTurnResult(employment_type="formal"),
            InterviewTurnResult(fixed_expenses=1000),
            InterviewTurnResult(dependents=0),
            InterviewTurnResult(has_active_debt=False),
        ]
    )
    conversation = Conversation(BankingFlow(data_dir), provider)
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = conversation
    app.run()
    for message in [
        "Meu limite, CPF 00000000001, 15/01/1990",
        "Quero 4000",
        "Sim",
        "10000",
        "CLT",
        "1000",
        "0",
        "Não",
    ]:
        app.chat_input[0].set_value(message).run()
        assert not app.exception
    assert conversation.flow.state.credit.last_request_status == "aprovado"
    assert any("4.000,00" in message["content"] for message in app.session_state.messages)
    app.chat_input[0].set_value("encerrar").run()
    assert app.chat_input[0].disabled
    app.button(key="new_conversation").click().run()
    assert not app.exception
    assert not app.session_state.conversation.flow.state.authenticated


def test_three_authentication_failures_through_chat(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    bad = TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        BankingFlow(data_dir), ScriptedProvider([bad, bad, bad])
    )
    app.run()
    for _ in range(3):
        app.chat_input[0].set_value("00000000001, 01/01/2000").run()
        assert not app.exception
    assert app.chat_input[0].disabled
    assert app.session_state.conversation.flow.state.authentication_attempts == 3


def test_actual_agents_and_exchange_through_ui(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    outputs = iter(
        [
            {
                "cpf": "00000000001",
                "birth_date": "1990-01-15",
                "detected_intent": "exchange_rate",
                "currency": "EUR",
            },
            {"currency": "GBP"},
        ]
    )

    def respond_groq(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(next(outputs))}}]}
        )

    def respond_exchange(request):
        if "GBP" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json={"EURBRL": {"bid": "6.1234", "timestamp": "1750000000"}})

    flow = BankingFlow(data_dir, ExchangeService(transport=httpx.MockTransport(respond_exchange)))
    provider = GroqProvider("test", "test", flow.tools, httpx.MockTransport(respond_groq))
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(flow, provider)
    app.run()
    app.chat_input[0].set_value("Cotação do euro, CPF 00000000001, 15/01/1990").run()
    assert not app.exception
    assert "6.1234" in app.session_state.messages[-1]["content"]
    app.chat_input[0].set_value("E a libra?").run()
    assert not app.exception
    assert "indisponível" in app.session_state.messages[-1]["content"]
    assert flow.state.authenticated
    app.button(key="end_conversation").click().run()
    assert flow.state.status == "finished"
