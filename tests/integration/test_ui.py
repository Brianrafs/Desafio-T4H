from pathlib import Path

from streamlit.testing.v1 import AppTest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult

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
