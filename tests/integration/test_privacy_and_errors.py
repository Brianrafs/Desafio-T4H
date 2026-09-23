import json

import httpx
import pytest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import CreditTurnResult, InterviewTurnResult, TriageTurnResult
from banco_agil.models.errors import LLMError, LLMStructuredOutputError, RepositoryError
from banco_agil.models.responses import FlowOutcome, GeneratedMessage, OutcomeDirective
from banco_agil.providers.groq import GroqProvider
from banco_agil.services.exchange_service import ExchangeService


async def test_protected_values_only_exist_in_first_user_input(data_dir, caplog):
    bodies = []
    outputs = iter(
        [
            {
                "cpf": "00000000001",
                "birth_date": "1990-01-15",
                "detected_intent": "credit_limit_query",
            },
            {"text": "Olá, {{customer_first_name}}. Seu limite é {{current_limit}}."},
            {"information_topic": "credit_evaluation"},
            {"text": "A análise considera os dados do cadastro e não garante aprovação."},
        ]
    )

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(next(outputs))}}]},
        )

    flow = BankingFlow(data_dir)
    provider = GroqProvider("test", "test", flow.tools, httpx.MockTransport(respond))
    conversation = Conversation(flow, provider)
    original = "Sou Ana. Meu limite é R$ 1.000,00, CPF 00000000001, nascimento 15/01/1990"

    first = await conversation.send(original)
    await conversation.send("Como funciona o aumento?")

    assert len(bodies) == 4
    assert bodies[0]["messages"][-1]["content"] == original
    assert "Ana" in first
    assert "R$ 1.000,00" in first
    for serialized in (
        *(json.dumps(body, ensure_ascii=False) for body in bodies[1:]),
        conversation.last_summary.model_dump_json(),
        caplog.text,
    ):
        for protected in ("00000000001", "15/01/1990", "1990-01-15", "Ana", "1.000"):
            assert protected not in serialized
    assert "Resumo seguro anterior:" in bodies[2]["messages"][0]["content"]
    assert "previous_summary" in json.loads(bodies[3]["messages"][-1]["content"])


@pytest.mark.parametrize(
    "composition,reason,rejected",
    [
        (LLMError, "provider_unavailable", False),
        (LLMStructuredOutputError, "invalid_schema", False),
        ("Seu limite é {{current_limit}}.", "missing_placeholder", True),
        ("Seu limite é {{unknown_limit}}.", "unknown_placeholder", True),
        (
            "Olá, {{customer_first_name}}. Seu limite é {{current_limit}}. Aprovação garantida.",
            "policy_rejected",
            True,
        ),
        (
            "Olá, {{customer_first_name}}. Seu limite é {{current_limit}}.",
            None,
            False,
        ),
    ],
)
async def test_composition_logs_one_terminal_event_with_safe_reason(
    data_dir, caplog, composition, reason, rejected
):
    class Provider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_query",
            )

        async def compose(self, brief, *, previous_summary=None):
            if isinstance(composition, type):
                raise composition("CPF 00000000001, Ana, R$ 1.000,00")
            return GeneratedMessage(text=composition)

    conversation = Conversation(BankingFlow(data_dir), Provider())
    response = await conversation.send("Quero consultar meu limite")

    rows = [
        json.loads(row.message)
        for row in caplog.records
        if row.name == "banco_agil" and json.loads(row.message)["event"].startswith("response_")
    ]
    expected = ["response_composition_started"]
    if rejected:
        expected.append("response_policy_rejected")
    expected.append("response_composition_fallback" if reason else "response_composition_succeeded")
    assert [row["event"] for row in rows] == expected
    assert rows[-1].get("reason") == reason
    if rejected:
        assert rows[-2]["reason"] == reason
    assert "Ana" in response
    assert "R$ 1.000,00" in response
    for sensitive in ("Ana", "R$", "00000000001", "current_limit", "Aprovação garantida"):
        assert sensitive not in caplog.text


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
        async def interpret(self, message, state, *, previous_summary=None):
            state.authenticated = False
            raise LLMError()

        async def compose(self, brief, *, previous_summary=None):
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
    assert flow.state.current_agent == "triage"
    goodbye = await conversation.send("encerrar")
    assert flow.state.status == "finished"
    assert "encerrada" in goodbye
    assert conversation.last_summary.events == ("conversation_closed",)


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


async def test_financial_profile_is_not_logged_when_persistence_fails(
    data_dir, monkeypatch, caplog
):
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
    for result in (
        InterviewTurnResult(monthly_income=9876),
        InterviewTurnResult(employment_type="formal"),
        InterviewTurnResult(fixed_expenses=1234),
        InterviewTurnResult(dependents=2),
    ):
        await flow.process(result)

    def fail_submit(*args):
        raise RepositoryError()

    monkeypatch.setattr(flow._tools.score, "submit", fail_submit)
    await flow.process(InterviewTurnResult(has_active_debt=True))

    for sensitive in ("9876", "1234", "00000000001", "1990-01-15"):
        assert sensitive not in caplog.text


class CommittedCreditFlow:
    """Isola a resposta aprovada; os efeitos são do BankingFlow real."""

    def __init__(self, data_dir):
        self.banking = BankingFlow(data_dir)
        self.process_count = 0

    @property
    def state(self):
        return self.banking.state

    async def process(self, result):
        self.process_count += 1
        await self.banking.process(result)
        return FlowOutcome(
            directives=(OutcomeDirective(event="credit_increase_approved"),),
            specialist="credit",
            protected_values={"new_limit": "R$ 2.000,00"},
            next_step="idle",
        )


@pytest.mark.parametrize("failure", [LLMError, LLMStructuredOutputError, "invalid_template"])
async def test_composition_fallback_keeps_committed_credit_effect_once(data_dir, failure):
    flow = CommittedCreditFlow(data_dir)

    class FailingComposer:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_increase",
                requested_limit=2000,
            )

        async def compose(self, brief, *, previous_summary=None):
            assert len(flow.banking.tools.credit.requests.read()) == 1
            if failure == "invalid_template":
                return GeneratedMessage(text="Aprovado: {{unknown_limit}}.")
            raise failure()

    conversation = Conversation(flow, FailingComposer())

    response = await conversation.send("Solicito o limite de dois mil")

    assert flow.process_count == 1
    assert len(flow.banking.tools.credit.requests.read()) == 1
    assert flow.state.authenticated
    assert flow.state.current_agent == "triage"
    assert "**aprovado**" in response
    assert "**R$ 2.000,00**" in response
    assert conversation.last_summary.events == ("credit_increase_approved",)


async def test_composition_http_payload_excludes_message_state_and_protected_data(data_dir):
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            output = {
                "cpf": "00000000001",
                "birth_date": "1990-01-15",
                "detected_intent": "credit_limit_increase",
                "requested_limit": 2000,
            }
        else:
            output = {"text": "Seu novo limite aprovado é **{{new_limit}}**."}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    flow = CommittedCreditFlow(data_dir)
    provider = GroqProvider("test", "test", flow.banking.tools, httpx.MockTransport(respond))
    conversation = Conversation(flow, provider)
    original = "Sou Ana, CPF 00000000001, 15/01/1990. Solicito R$ 2.000,00."

    response = await conversation.send(original)

    assert len(bodies) == 2
    assert response == "Seu novo limite aprovado é **R$ 2.000,00**."
    composition = json.dumps(bodies[1], ensure_ascii=False)
    for sensitive in (
        original,
        response,
        "Ana",
        "00000000001",
        "1990",
        "2.000",
        str(flow.state.session_id),
    ):
        assert sensitive not in composition
    context = json.loads(bodies[1]["messages"][-1]["content"])
    assert set(context) == {"brief"}
    assert context["brief"]["specialist"] == "credit"
    assert context["brief"]["directives"][0]["event"] == "credit_increase_approved"
    assert "protected_values" not in context["brief"]
