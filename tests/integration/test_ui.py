import json
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult
from banco_agil.models.errors import LLMError, RepositoryError
from banco_agil.models.responses import GeneratedMessage
from banco_agil.providers.groq import GroqProvider
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.exchange_service import ExchangeService

APP = Path(__file__).parents[2] / "app.py"


class ScriptedProvider:
    def __init__(self, *, interpretations, compositions):
        self.interpretations = iter(interpretations)
        self.compositions = iter(compositions)

    async def interpret(self, message, state, *, previous_summary=None):
        return next(self.interpretations)

    async def compose(self, brief, *, previous_summary=None):
        if brief.directives[0].event == "welcome":
            return GeneratedMessage(text="Sou a Lia. Como posso ajudar?")
        generated = next(self.compositions, None)
        if generated is None:
            raise LLMError()
        return generated


@pytest.fixture(autouse=True)
def offline_created_conversations(monkeypatch):
    def create(settings):
        from banco_agil.repositories.bootstrap import initialize_demo_data

        initialize_demo_data(APP.parent / "data", settings.data_dir)
        return Conversation(
            BankingFlow(settings.data_dir),
            ScriptedProvider(interpretations=[], compositions=[]),
        )

    monkeypatch.setattr("banco_agil.bootstrap.create_conversation", create)


@pytest.mark.parametrize("reset", ["new_conversation", "demo_reset"])
def test_start_composes_once_per_session_including_reset(data_dir, monkeypatch, reset):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    welcomes = []

    class WelcomeProvider(ScriptedProvider):
        async def compose(self, brief, *, previous_summary=None):
            welcomes.append(brief)
            return GeneratedMessage(text="Sou a Lia. Por onde você prefere começar?")

    def create(settings):
        return Conversation(
            BankingFlow(settings.data_dir), WelcomeProvider(interpretations=[], compositions=[])
        )

    monkeypatch.setattr("banco_agil.bootstrap.create_conversation", create)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert app.session_state.messages == [
        {"role": "assistant", "content": "Sou a Lia. Por onde você prefere começar?"}
    ]
    app.run()
    assert len(welcomes) == 1
    app.button(key=f"request_{reset}").click().run()
    assert len(welcomes) == 1
    app.button(key=f"confirm_{reset}").click().run()
    assert not app.exception
    assert len(welcomes) == 2
    assert all(brief.directives[0].event == "welcome" for brief in welcomes)
    assert len(app.session_state.messages) == 1


def test_app_starts_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert app.title[0].value == "Banco Ágil"
    assert "Lia" in app.session_state.messages[0]["content"]
    assert any("Lia" in caption.value for caption in app.caption)
    app.button(key="end_conversation").click().run()
    assert not app.exception
    assert app.session_state.conversation.flow.state.status == "finished"


def test_golden_path_through_chat(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    provider = ScriptedProvider(
        interpretations=[
            TriageTurnResult(
                cpf="00000000001", birth_date="1990-01-15", detected_intent="credit_limit_query"
            ),
            TriageTurnResult(detected_intent="credit_limit_increase", requested_limit=4000),
            CreditTurnResult(interview_accepted=True),
            InterviewTurnResult(monthly_income=10000),
            InterviewTurnResult(employment_type="formal"),
            InterviewTurnResult(fixed_expenses=1000),
            InterviewTurnResult(dependents=0),
            InterviewTurnResult(has_active_debt=False),
        ],
        compositions=[],
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
    app.button(key="request_new_conversation").click().run()
    app.button(key="confirm_new_conversation").click().run()
    assert not app.exception
    assert not app.session_state.conversation.flow.state.authenticated


def test_quick_action_and_lia_markdown(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    flow = BankingFlow(data_dir)
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        flow,
        ScriptedProvider(
            interpretations=[
                TriageTurnResult(
                    cpf="00000000001",
                    birth_date="1990-01-15",
                    detected_intent="credit_limit_query",
                ),
            ],
            compositions=[],
        ),
    )
    app.run()
    app.button(key="quick_Consultar limite").click().run()
    assert not app.exception
    response = app.session_state.messages[-1]["content"]
    assert not response.startswith("Entendi.")
    assert "**R$ 1.000,00**" in response
    assert "avaliar um aumento" in response
    assert "\n- **" not in response
    assert flow.state.current_agent == "triage"
    assert not app.button(key="quick_Pedir aumento").disabled


def test_three_authentication_failures_through_chat(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    bad = TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        BankingFlow(data_dir), ScriptedProvider(interpretations=[bad, bad, bad], compositions=[])
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
            {"text": "Sou a Lia. Como posso ajudar?"},
            {
                "cpf": "00000000001",
                "birth_date": "1990-01-15",
                "detected_intent": "exchange_rate",
                "currency": "EUR",
            },
            {"text": "A cotação confirmada é {{exchange_rate}}.{{quote_timestamp}}"},
            {"currency": "GBP"},
            {"text": "Até a próxima!"},
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


def test_reset_demo_data_requires_confirmation(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    customers = CustomerRepository(data_dir)
    customer = customers.require("00000000001")
    customer.limite_credito = 2000
    customers.save(customer)

    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button(key="request_demo_reset").click().run()
    assert CustomerRepository(data_dir).require("00000000001").limite_credito == 2000

    app.button(key="confirm_demo_reset").click().run()

    assert not app.exception
    assert CustomerRepository(data_dir).require("00000000001").limite_credito == 1000
    assert app.session_state.messages[0]["content"] == "Sou a Lia. Como posso ajudar?"


def test_new_conversation_requires_confirmation(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    flow = BankingFlow(data_dir)
    flow.state.authenticated = True
    flow.state.authenticated_customer_cpf = "00000000001"
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        flow, ScriptedProvider(interpretations=[], compositions=[])
    )
    app.run()

    app.button(key="request_new_conversation").click().run()
    assert app.session_state.conversation.flow.state.authenticated

    app.button(key="confirm_new_conversation").click().run()
    assert not app.session_state.conversation.flow.state.authenticated
    assert app.session_state.messages == [
        {"role": "assistant", "content": "Sou a Lia. Como posso ajudar?"}
    ]


def test_privacy_notice_is_visible_before_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    rendered = " ".join(element.value for element in app.caption)
    assert "dados fictícios" in rendered
    assert "Groq" in rendered


def test_authenticated_status_does_not_expose_cpf(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    flow = BankingFlow(data_dir)
    flow.state.authenticated = True
    flow.state.authenticated_customer_cpf = "00000000001"
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        flow, ScriptedProvider(interpretations=[], compositions=[])
    )
    app.run()
    rendered = " ".join(element.value for element in [*app.caption, *app.success])
    assert "Identidade confirmada" in rendered
    assert "00000000001" not in rendered


def test_interview_progress_survives_agent_generated_question(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    flow = BankingFlow(data_dir)
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        flow,
        ScriptedProvider(
            interpretations=[
                TriageTurnResult(
                    cpf="00000000001",
                    birth_date="1990-01-15",
                    detected_intent="credit_limit_increase",
                    requested_limit=4000,
                ),
                CreditTurnResult(interview_accepted=True),
            ],
            compositions=[
                GeneratedMessage(text="Não foi possível aprovar. Quer fazer a entrevista?"),
                GeneratedMessage(text="Vamos começar. Qual é sua renda mensal?"),
            ],
        ),
    )
    app.run()
    app.chat_input[0].set_value("Quero um limite de 4000").run()
    app.chat_input[0].set_value("Sim").run()

    assert not app.exception
    assert app.session_state.messages[-1]["content"] == ("Vamos começar. Qual é sua renda mensal?")
    assert flow.state.interview.next_missing_field() == "monthly_income"
    assert not app.sidebar.get("progress")
    assert any("etapa 1 de 5" in item.value for item in app.caption)
    assert len(app.get("progress")) == 1
    assert app.get("progress")[0].proto.value == 0


def test_ending_from_sidebar_clears_interview_progress(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    flow = BankingFlow(data_dir)
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(
        flow,
        ScriptedProvider(
            interpretations=[
                TriageTurnResult(
                    cpf="00000000001",
                    birth_date="1990-01-15",
                    detected_intent="credit_limit_increase",
                    requested_limit=4000,
                ),
                CreditTurnResult(interview_accepted=True),
            ],
            compositions=[],
        ),
    )
    app.run()
    app.chat_input[0].set_value("Quero um limite de 4000").run()
    app.chat_input[0].set_value("Sim").run()
    assert app.get("progress")

    app.button(key="end_conversation").click().run()

    assert not app.exception
    assert flow.state.status == "finished"
    assert not app.get("progress")


@pytest.mark.parametrize("error", [RepositoryError(), OSError("private filesystem detail")])
def test_failed_demo_reset_is_controlled_and_retryable(data_dir, monkeypatch, error):
    from banco_agil.repositories.bootstrap import reset_demo_data

    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    original = app.session_state.conversation.flow.state.id

    def fail_reset(*args):
        raise error

    monkeypatch.setattr("banco_agil.repositories.bootstrap.reset_demo_data", fail_reset)
    app.button(key="request_demo_reset").click().run()
    app.button(key="confirm_demo_reset").click().run()
    assert not app.exception
    assert app.error
    assert "private filesystem detail" not in app.error[0].value
    assert app.session_state.conversation.flow.state.id == original
    monkeypatch.setattr("banco_agil.repositories.bootstrap.reset_demo_data", reset_demo_data)
    app.button(key="confirm_demo_reset").click().run()
    assert not app.exception
    assert app.session_state.conversation.flow.state.id != original
