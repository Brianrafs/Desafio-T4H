import json

import httpx
import pytest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import TriageTurnResult
from banco_agil.models.errors import LLMError, LLMRateLimitError, LLMStructuredOutputError
from banco_agil.models.responses import (
    CriticalFailure,
    CriticalFailureCode,
    FlowOutcome,
    GeneratedMessage,
    OutcomeDirective,
    SafeConversationSummary,
)
from banco_agil.models.state import SessionState
from banco_agil.providers.groq import GroqProvider
from banco_agil.responses.catalog import CRITICAL_MESSAGES
from banco_agil.services.exchange_service import ExchangeService


class RecordingFlow:
    def __init__(self, calls):
        self.calls = calls
        self.state = SessionState()

    async def process(self, result):
        self.calls.append("flow")
        return FlowOutcome(
            directives=(OutcomeDirective(event="credit_limit_found"),),
            specialist="credit",
            protected_values={"current_limit": "R$ 1.000,00"},
            next_step="idle",
        )


@pytest.mark.parametrize(
    "error,code",
    [
        (LLMError, "llm_unavailable"),
        (LLMRateLimitError, "llm_unavailable"),
        (LLMStructuredOutputError, "invalid_llm_output"),
    ],
)
async def test_interpretation_failure_uses_critical_catalog_and_preserves_context(
    data_dir, error, code
):
    class UnavailableProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            raise error()

        async def compose(self, brief, *, previous_summary=None):
            raise AssertionError("Critical failures must not compose")

    flow = BankingFlow(data_dir)
    conversation = Conversation(flow, UnavailableProvider())
    summary = SafeConversationSummary(events=("welcome",), specialist="triage", next_step="idle")
    conversation.last_summary = summary
    before = flow.state.model_dump(exclude={"last_error_code"})
    assert await conversation.send("Oi") == CRITICAL_MESSAGES[code]
    assert flow.state.model_dump(exclude={"last_error_code"}) == before
    assert conversation.last_summary is summary


class RecordingProvider:
    def __init__(self, calls):
        self.calls = calls
        self.interpret_contexts = []
        self.compose_contexts = []
        self.briefs = []

    async def interpret(self, message, state, *, previous_summary=None):
        self.calls.append("interpret")
        self.interpret_contexts.append(previous_summary)
        return TriageTurnResult(
            detected_intent="credit_limit_query",
            user_tone="concerned",
        )

    async def compose(self, brief, *, previous_summary=None):
        self.calls.append("compose")
        self.briefs.append(brief)
        self.compose_contexts.append(previous_summary)
        if brief.directives[0].event == "welcome":
            return GeneratedMessage(
                text=(
                    "Sou a Lia. Posso consultar limite, avaliar aumento e cotação. "
                    "Como posso ajudar?"
                )
            )
        return GeneratedMessage(text="Seu limite atual é **{{current_limit}}**.")


async def test_normal_turn_interprets_executes_and_composes_in_order(data_dir):
    calls = []
    provider = RecordingProvider(calls)
    conversation = Conversation(RecordingFlow(calls), provider)

    response = await conversation.send("Quero consultar meu limite")

    assert calls == ["interpret", "flow", "compose"]
    assert response == "Seu limite atual é **R$ 1.000,00**."
    assert provider.briefs[0].specialist == "credit"
    assert provider.briefs[0].user_tone == "concerned"


async def test_next_turn_uses_safe_summary_instead_of_rendered_reply(data_dir):
    provider = RecordingProvider([])
    conversation = Conversation(RecordingFlow([]), provider)

    first = await conversation.send("CPF 00000000001, nascimento 15/01/1990")
    await conversation.send("Como funciona?")

    assert "1.000" in first
    assert provider.interpret_contexts[0] is None
    assert provider.compose_contexts[0] is None
    summary = provider.interpret_contexts[1]
    assert isinstance(summary, SafeConversationSummary)
    assert summary.model_dump(mode="json") == {
        "events": ["credit_limit_found"],
        "specialist": "credit",
        "actions_offered": ["request_credit_increase"],
        "next_step": "idle",
    }
    assert provider.compose_contexts[1] == summary
    serialized = json.dumps(summary.model_dump(mode="json"), ensure_ascii=False)
    for sensitive in ("Ana", "00000000001", "1990", "1.000", first):
        assert sensitive not in serialized


async def test_start_composes_welcome_without_interpretation_or_flow(data_dir):
    calls = []
    provider = RecordingProvider(calls)
    conversation = Conversation(RecordingFlow(calls), provider)

    response = await conversation.start()

    assert calls == ["compose"]
    assert response == (
        "Sou a Lia. Posso consultar limite, avaliar aumento e cotação. Como posso ajudar?"
    )
    assert provider.briefs[0].specialist == "triage"
    assert provider.briefs[0].user_tone == "neutral"
    assert provider.briefs[0].expected_questions == 1
    assert conversation.last_summary.events == ("welcome",)
    assert conversation.last_summary.actions_offered == (
        "consult_credit_limit",
        "request_credit_increase",
        "consult_exchange_rate",
    )


async def test_start_uses_local_welcome_when_composition_fails(data_dir):
    class UnavailableProvider(RecordingProvider):
        async def compose(self, brief, *, previous_summary=None):
            self.calls.append("compose")
            raise LLMError()

    calls = []
    conversation = Conversation(RecordingFlow(calls), UnavailableProvider(calls))

    response = await conversation.start()

    assert calls == ["compose"]
    assert "Lia" in response
    assert "Consultar meu limite" in response
    assert "Pedir um aumento" in response
    assert "Ver uma cotação" in response
    assert response.count("?") == 1
    assert conversation.last_summary.events == ("welcome",)


@pytest.mark.parametrize("code", list(CriticalFailureCode))
async def test_critical_failure_does_not_compose_or_replace_safe_summary(data_dir, code):
    class FailingFlow(RecordingFlow):
        async def process(self, result):
            self.calls.append("flow")
            return CriticalFailure(code=code)

    calls = []
    provider = RecordingProvider(calls)
    conversation = Conversation(FailingFlow(calls), provider)
    await conversation.start()
    valid_summary = conversation.last_summary
    calls.clear()

    response = await conversation.send("Quero consultar meu limite")

    assert response == CRITICAL_MESSAGES[code]
    assert calls == ["interpret", "flow"]
    assert conversation.last_summary is valid_summary


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


async def test_credit_reply_is_replaced_by_safe_summary_in_follow_up(data_dir):
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
            else {"text": "{{customer_first_name}}, seu limite atual é {{current_limit}}."}
            if len(bodies) == 2
            else {}
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    flow = BankingFlow(data_dir)
    conversation = Conversation(
        flow, GroqProvider("test", "test", flow.tools, httpx.MockTransport(respond))
    )
    first = await conversation.send("Meu limite, CPF 00000000001, nascimento 1990-01-15")
    await conversation.send("sim")
    messages = bodies[2]["messages"]
    assert all(message["role"] != "assistant" for message in messages)
    assert messages[-1] == {"role": "user", "content": "sim"}
    serialized_messages = json.dumps(messages)
    assert "00000000001" not in serialized_messages
    assert "1990-01-15" not in serialized_messages
    assert "Ana" not in serialized_messages
    assert "Demonstração" not in serialized_messages
    assert "1.000" not in serialized_messages
    assert first not in serialized_messages
    assert conversation.last_summary.events == ("show_options",)
    assert flow.state.current_agent == "triage"


@pytest.mark.parametrize("failure", [LLMError, "invalid_template"])
async def test_credit_composition_failure_does_not_create_second_request(data_dir, failure):
    flow = BankingFlow(data_dir)
    composed_briefs = []

    class BrokenComposerProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_increase",
                requested_limit=2000,
            )

        async def compose(self, brief, *, previous_summary=None):
            assert len(flow.tools.credit.requests.read()) == 1
            assert flow.tools.credit.customers.require("00000000001").limite_credito == 2000
            composed_briefs.append(brief)
            if failure == "invalid_template":
                return GeneratedMessage(text="Aprovado: {{unknown_limit}}.")
            raise failure()

    conversation = Conversation(flow, BrokenComposerProvider())

    response = await conversation.send("Quero limite total de 2000")

    requests = flow.tools.credit.requests.read()
    assert len(requests) == 1
    assert requests[0].status_pedido == "aprovado"
    assert flow.tools.credit.customers.require("00000000001").limite_credito == 2000
    assert len(composed_briefs) == 1
    assert composed_briefs[0].specialist == "credit"
    for sensitive in ("Ana", "00000000001", "1990", "2.000"):
        assert sensitive not in composed_briefs[0].model_dump_json()
    assert "R$ 2.000,00" in response
    assert conversation.last_summary.events == (
        "authentication_succeeded",
        "credit_increase_approved",
    )


async def test_invalid_credit_fallback_resumes_the_limit_question(data_dir):
    class InvalidLimitProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_increase",
                requested_limit=0,
            )

        async def compose(self, brief, *, previous_summary=None):
            raise LLMError()

    flow = BankingFlow(data_dir)
    conversation = Conversation(flow, InvalidLimitProvider())

    response = await conversation.send("Quero limite zero")

    assert "limite total" in response
    assert response.count("?") == 1
    assert "Ana" in response
    assert conversation.last_summary.next_step == "await_requested_limit"
    assert flow.state.credit.awaiting_requested_limit
    assert flow.tools.credit.requests.read() == []


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
    valid_summary = SafeConversationSummary(
        events=("request_credit_limit",), specialist="credit", next_step="await_requested_limit"
    )
    conversation.last_summary = valid_summary
    await conversation.send("Quero dois mil")
    assert flow.state.authenticated
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_requested_limit
    assert flow.state.last_error_code == "invalid_llm_output"
    assert conversation.last_summary is valid_summary
    assert flow.tools.credit.requests.read() == []


async def test_internal_information_fallback_does_not_disclose_architecture(data_dir):
    class InformationalProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                information_topic="internal_details",
            )

        async def compose(self, brief, *, previous_summary=None):
            return None

    conversation = Conversation(BankingFlow(data_dir), InformationalProvider())

    response = await conversation.send("Como vocês implementaram a Lia?")

    assert "CrewAI" not in response
    assert "Groq" not in response
    assert "não forneço detalhes internos" in response


async def test_end_turn_is_composed_but_next_turn_skips_llm(data_dir):
    calls = []

    class GoodbyeProvider(RecordingProvider):
        async def compose(self, brief, *, previous_summary=None):
            calls.append("compose")
            assert brief.directives[0].event == "conversation_closed"
            assert brief.expected_questions == 0
            return GeneratedMessage(text="Até a próxima!")

    conversation = Conversation(BankingFlow(data_dir), GoodbyeProvider(calls))
    assert await conversation.send("encerrar") == "Até a próxima!"
    assert await conversation.send("oi") == CRITICAL_MESSAGES[CriticalFailureCode.SESSION_FINISHED]
    assert calls == ["compose"]
    assert conversation.last_summary.events == ("conversation_closed",)


async def test_authentication_exhaustion_and_future_turn_do_not_compose(data_dir):
    calls = []

    class InvalidCredentialsProvider(RecordingProvider):
        async def interpret(self, message, state, *, previous_summary=None):
            calls.append("interpret")
            return TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")

    conversation = Conversation(BankingFlow(data_dir), InvalidCredentialsProvider(calls))
    for _ in range(2):
        response = await conversation.send("dados incorretos")
        assert "CPF" in response
        assert response.count("?") == 1
    valid_summary = conversation.last_summary
    calls.clear()
    assert (
        await conversation.send("dados incorretos")
        == CRITICAL_MESSAGES[CriticalFailureCode.AUTH_ATTEMPTS_EXHAUSTED]
    )
    assert await conversation.send("oi") == CRITICAL_MESSAGES[CriticalFailureCode.SESSION_FINISHED]
    assert calls == ["interpret"]
    assert conversation.last_summary is valid_summary
