# Agent-Generated Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer os agentes especializados interpretarem intenções e formularem todas as respostas não críticas, mantendo decisões, estado, valores protegidos e transições sob controle determinístico.

**Architecture:** Cada turno normal terá uma chamada de interpretação, execução única do `BankingFlow` e uma chamada de composição a partir de `ResponseBrief`. O Flow retornará diretivas estruturadas; um renderer local validará placeholders e políticas antes de inserir valores protegidos, usando fallbacks determinísticos quando a composição falhar.

**Tech Stack:** Python 3.13, Pydantic 2.x, CrewAI 1.x, httpx 0.28.x, pytest, pytest-asyncio, pytest-cov, Ruff e uv.

**Spec:** `docs/superpowers/specs/2026-09-23-agent-response-generation-design.md`

## Global Constraints

- Python deve permanecer em `>=3.13,<3.14`; nenhuma dependência nova será adicionada.
- CrewAI deve permanecer em `>=1.0,<2`, Pydantic em `>=2.11,<3` e httpx em `>=0.28,<1`.
- Autenticação, decisões financeiras, transições e autorização nunca dependem do LLM.
- A operação de negócio ocorre no máximo uma vez por turno e nunca é repetida por falha de composição.
- A segunda chamada e o histórico seguro não recebem nome, CPF, nascimento, limites, cotações, renda ou despesas.
- A mensagem original continua sendo enviada somente à primeira chamada de interpretação; sanitização dessa entrada está fora do escopo.
- Não haverá terceira chamada de revisão; schema, políticas, placeholders e fallback serão locais.
- Somente falhas críticas usam texto fixo sem tentativa de composição.
- Todo `ResponseEvent` componível deve ter política e fallback antes de ser usado.
- Logs nunca incluem prompts, mensagens completas, placeholders resolvidos ou valores protegidos.
- Cada comportamento será desenvolvido em ciclo RED → GREEN, com commit atômico em português.
- A suíte completa deve permanecer verde, com cobertura mínima de 85%, Ruff e formatação aprovados.

## Review Focus

1. **Diretivas combinadas:** autenticação seguida de consulta e informação seguida de retomada devem produzir uma mensagem coesa, com os dois fatos e no máximo a pergunta autorizada.
2. **Marcadores hostis ou malformados:** marcador duplicado, desconhecido, incompleto ou escapado nunca pode vazar texto nem impedir o fallback.
3. **Falha após efeito persistido:** se composição falhar depois de um aumento aprovado, o limite muda uma vez, a solicitação é gravada uma vez e o fallback descreve o outcome confirmado.
4. **Privacidade entre chamadas:** credenciais presentes na primeira entrada não podem reaparecer no prompt de composição nem no resumo enviado no turno seguinte.
5. **Encerramento no mesmo turno:** a despedida do turno que encerra pode ser composta; qualquer mensagem posterior deve usar `SESSION_FINISHED` fixo sem chamar o modelo.

---

## File Structure

### Novos arquivos

- `src/banco_agil/models/responses.py`: enums e contratos imutáveis de outcome, brief, política, mensagem renderizada e resumo seguro.
- `src/banco_agil/responses/__init__.py`: exportações públicas do subsistema.
- `src/banco_agil/responses/catalog.py`: objetivos de comunicação, políticas, ações permitidas, fallbacks e mensagens críticas.
- `src/banco_agil/responses/briefs.py`: transformação pura de `FlowOutcome` em `ResponseBrief`.
- `src/banco_agil/responses/renderer.py`: validação local, substituição de placeholders e seleção de fallback.
- `tests/unit/test_response_models.py`: validação dos contratos.
- `tests/unit/test_response_renderer.py`: catálogo, brief, políticas, placeholders e fallbacks.

### Arquivos modificados

- `src/banco_agil/models/agent_outputs.py`: interpretação sem mensagem livre e com `UserTone`.
- `src/banco_agil/flow/banking_flow.py`: outcomes estruturados em vez de texto normal.
- `src/banco_agil/providers/groq.py`: protocolos e prompts distintos para `interpret` e `compose`.
- `src/banco_agil/agents/factory.py`: factories distintas de intérprete e responder, sem tools no responder.
- `src/banco_agil/conversation.py`: pipeline em duas chamadas, fallbacks e histórico seguro.
- `src/banco_agil/presentation.py`: manter apenas compatibilidade temporária; ao final, remover voz e sanitização antigas.
- `src/banco_agil/models/errors.py`: mapear falhas críticas para códigos sem montar texto no Flow.
- `src/banco_agil/observability.py`: eventos seguros de composição e fallback.
- `app.py`: obter boas-vindas por `Conversation.start()` e não por constante global.
- Testes existentes em `tests/flow/`, `tests/integration/` e `tests/unit/`: trocar assertivas de strings do Flow por diretivas e cobrir o pipeline final.

---

### Task 1: Contratos do pipeline de respostas

**Files:**
- Create: `src/banco_agil/models/responses.py`
- Create: `tests/unit/test_response_models.py`
- Modify: `src/banco_agil/models/agent_outputs.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Consumes: `Model`, `AgentType`, `IntentType` e `InformationTopic` existentes.
- Produces: `UserTone`, `ResponseEvent`, `ResponseAction`, `NextStep`, `CriticalFailureCode`, `FallbackReason`, `OutcomeDirective`, `FlowOutcome`, `CriticalFailure`, `ResponseDirective`, `ResponseBrief`, `ResponsePolicy`, `GeneratedMessage`, `RenderedResponse` e `SafeConversationSummary`.

- [ ] **Step 1: Escrever testes falhando para enums e contratos fechados**

```python
import pytest
from pydantic import ValidationError

from banco_agil.models.responses import (
    FlowOutcome,
    GeneratedMessage,
    OutcomeDirective,
    ResponseEvent,
)


def test_flow_outcome_requires_at_least_one_directive():
    with pytest.raises(ValidationError):
        FlowOutcome(
            directives=(),
            specialist="credit",
            protected_values={},
            next_step="idle",
        )


def test_generated_message_has_hard_length_limit():
    with pytest.raises(ValidationError):
        GeneratedMessage(text="x" * 701)


def test_response_event_contains_every_approved_event():
    assert {item.value for item in ResponseEvent} == {
        "welcome",
        "show_options",
        "request_cpf",
        "request_birth_date",
        "authentication_succeeded",
        "authentication_retry",
        "credit_limit_found",
        "request_credit_limit",
        "credit_increase_approved",
        "credit_increase_rejected_offer_interview",
        "credit_increase_rejected_final",
        "interview_started",
        "interview_question",
        "interview_reanalysis_approved",
        "interview_reanalysis_rejected",
        "request_currency",
        "exchange_quote_found",
        "unsupported_currency",
        "service_information",
        "resume_pending_step",
        "invalid_input",
        "conversation_closed",
    }


def test_outcome_directive_forbids_unknown_properties():
    with pytest.raises(ValidationError):
        OutcomeDirective(event="welcome", public_context={}, text="não permitido")
```

- [ ] **Step 2: Executar os testes e confirmar RED**

Run: `uv run pytest tests/unit/test_response_models.py -q`

Expected: FAIL durante importação porque `banco_agil.models.responses` ainda não existe.

- [ ] **Step 3: Criar os contratos exatos**

```python
from enum import StrEnum

from pydantic import Field

from banco_agil.models.domain import Model
from banco_agil.models.state import AgentType


class UserTone(StrEnum):
    NEUTRAL = "neutral"
    UNCERTAIN = "uncertain"
    CONCERNED = "concerned"
    FRUSTRATED = "frustrated"
    POSITIVE = "positive"


class ResponseEvent(StrEnum):
    WELCOME = "welcome"
    SHOW_OPTIONS = "show_options"
    REQUEST_CPF = "request_cpf"
    REQUEST_BIRTH_DATE = "request_birth_date"
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_RETRY = "authentication_retry"
    CREDIT_LIMIT_FOUND = "credit_limit_found"
    REQUEST_CREDIT_LIMIT = "request_credit_limit"
    CREDIT_INCREASE_APPROVED = "credit_increase_approved"
    CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW = "credit_increase_rejected_offer_interview"
    CREDIT_INCREASE_REJECTED_FINAL = "credit_increase_rejected_final"
    INTERVIEW_STARTED = "interview_started"
    INTERVIEW_QUESTION = "interview_question"
    INTERVIEW_REANALYSIS_APPROVED = "interview_reanalysis_approved"
    INTERVIEW_REANALYSIS_REJECTED = "interview_reanalysis_rejected"
    REQUEST_CURRENCY = "request_currency"
    EXCHANGE_QUOTE_FOUND = "exchange_quote_found"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    SERVICE_INFORMATION = "service_information"
    RESUME_PENDING_STEP = "resume_pending_step"
    INVALID_INPUT = "invalid_input"
    CONVERSATION_CLOSED = "conversation_closed"


class ResponseAction(StrEnum):
    CONSULT_CREDIT_LIMIT = "consult_credit_limit"
    REQUEST_CREDIT_INCREASE = "request_credit_increase"
    START_CREDIT_INTERVIEW = "start_credit_interview"
    CONSULT_EXCHANGE_RATE = "consult_exchange_rate"
    END_CONVERSATION = "end_conversation"


class NextStep(StrEnum):
    AWAIT_CPF = "await_cpf"
    AWAIT_BIRTH_DATE = "await_birth_date"
    AWAIT_REQUESTED_LIMIT = "await_requested_limit"
    AWAIT_INTERVIEW_CONFIRMATION = "await_interview_confirmation"
    AWAIT_INTERVIEW_FIELD = "await_interview_field"
    AWAIT_CURRENCY = "await_currency"
    IDLE = "idle"
    FINISHED = "finished"


class CriticalFailureCode(StrEnum):
    LLM_UNAVAILABLE = "llm_unavailable"
    INVALID_LLM_OUTPUT = "invalid_llm_output"
    EXTERNAL_SERVICE_UNAVAILABLE = "external_service_unavailable"
    PERSISTENCE_FAILURE = "persistence_failure"
    AUTH_ATTEMPTS_EXHAUSTED = "auth_attempts_exhausted"
    SESSION_FINISHED = "session_finished"
    INVALID_INTERNAL_STATE = "invalid_internal_state"


class FallbackReason(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_SCHEMA = "invalid_schema"
    UNKNOWN_PLACEHOLDER = "unknown_placeholder"
    MISSING_PLACEHOLDER = "missing_placeholder"
    POLICY_REJECTED = "policy_rejected"


class OutcomeDirective(Model):
    event: ResponseEvent
    public_context: dict[str, str | int | bool] = Field(default_factory=dict)


class FlowOutcome(Model):
    directives: tuple[OutcomeDirective, ...] = Field(min_length=1)
    specialist: AgentType
    protected_values: dict[str, str] = Field(default_factory=dict)
    next_step: NextStep
    expected_questions: int = Field(default=0, ge=0, le=1)


class CriticalFailure(Model):
    code: CriticalFailureCode


class ResponseDirective(Model):
    event: ResponseEvent
    communication_goal: str = Field(min_length=1)
    public_context: dict[str, str | int | bool] = Field(default_factory=dict)


class ResponseBrief(Model):
    directives: tuple[ResponseDirective, ...] = Field(min_length=1)
    required_placeholders: frozenset[str] = frozenset()
    allowed_placeholders: frozenset[str] = frozenset()
    allowed_actions: tuple[ResponseAction, ...] = ()
    next_step: NextStep
    expected_questions: int = Field(ge=0, le=1)
    user_tone: UserTone
    constraints: tuple[str, ...] = ()


class ResponsePolicy(Model):
    required_placeholders: frozenset[str] = frozenset()
    allowed_placeholders: frozenset[str] = frozenset()
    expected_questions: int = Field(ge=0, le=1)
    max_length: int = Field(default=700, gt=0)
    forbidden_patterns: tuple[str, ...] = ()
    required_patterns: tuple[str, ...] = ()


class GeneratedMessage(Model):
    text: str = Field(min_length=1, max_length=700)


class RenderedResponse(Model):
    text: str = Field(min_length=1)
    used_fallback: bool
    fallback_reason: FallbackReason | None = None


class SafeConversationSummary(Model):
    events: tuple[ResponseEvent, ...] = Field(min_length=1)
    specialist: AgentType
    actions_offered: tuple[ResponseAction, ...] = ()
    next_step: NextStep
```

Adicionar `user_tone: UserTone = UserTone.NEUTRAL` ao `TurnResult`, mantendo `message`
temporariamente para compatibilidade até a Task 9.

- [ ] **Step 4: Executar testes focados e confirmar GREEN**

Run: `uv run pytest tests/unit/test_response_models.py tests/unit/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Executar lint, revisar diff e commitar**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/models/responses.py src/banco_agil/models/agent_outputs.py tests/unit/test_response_models.py tests/unit/test_models.py
git commit -m "feat(respostas): adiciona contratos estruturados"
```

---

### Task 2: Catálogo, briefs, políticas e renderer seguro

**Files:**
- Create: `src/banco_agil/responses/__init__.py`
- Create: `src/banco_agil/responses/catalog.py`
- Create: `src/banco_agil/responses/briefs.py`
- Create: `src/banco_agil/responses/renderer.py`
- Create: `tests/unit/test_response_renderer.py`

**Interfaces:**
- Consumes: todos os modelos produzidos na Task 1.
- Produces: `EVENT_DEFINITIONS`, `CRITICAL_MESSAGES`, `build_response_brief(outcome, user_tone)`, `render_response(outcome, brief, generated, fallback_reason=None)` e `safe_summary(outcome, brief)`.

- [ ] **Step 1: Escrever testes falhando para cobertura do catálogo e privacidade do brief**

```python
from banco_agil.models.responses import (
    FlowOutcome,
    NextStep,
    OutcomeDirective,
    ResponseEvent,
    UserTone,
)
from banco_agil.responses.briefs import build_response_brief
from banco_agil.responses.catalog import EVENT_DEFINITIONS


def test_every_response_event_has_definition_and_fallback():
    assert set(EVENT_DEFINITIONS) == set(ResponseEvent)
    assert all(definition.fallback for definition in EVENT_DEFINITIONS.values())


def test_brief_contains_placeholder_name_but_not_protected_value():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_limit_found"),),
        specialist="credit",
        protected_values={"current_limit": "R$ 2.500,00"},
        next_step=NextStep.IDLE,
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    serialized = brief.model_dump_json()
    assert "current_limit" in serialized
    assert "2.500" not in serialized
```

- [ ] **Step 2: Escrever testes falhando para marcadores e políticas hostis**

```python
import pytest

from banco_agil.models.responses import GeneratedMessage
from banco_agil.responses.renderer import render_response


@pytest.fixture
def credit_limit_response():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_limit_found"),),
        specialist="credit",
        protected_values={"current_limit": "R$ 2.500,00"},
        next_step="idle",
    )
    return outcome, build_response_brief(outcome, UserTone.NEUTRAL)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("Seu limite é {{current_limit}} e {{unknown}}.", "unknown_placeholder"),
        ("Seu limite foi consultado.", "missing_placeholder"),
        ("Seu limite é {{current_limit}} e R$ 9.999,99.", "policy_rejected"),
        ("Pedido aprovado. Limite: {{current_limit}}.", "policy_rejected"),
        ("{{current_limit}} e novamente {{current_limit}}.", "policy_rejected"),
        ("Use { {current_limit} }.", "missing_placeholder"),
    ],
)
def test_invalid_generated_message_uses_fallback(credit_limit_response, text, reason):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, GeneratedMessage(text=text))

    assert rendered.used_fallback
    assert rendered.fallback_reason == reason
    assert "9.999" not in rendered.text
```

- [ ] **Step 3: Executar testes e confirmar RED**

Run: `uv run pytest tests/unit/test_response_renderer.py -q`

Expected: FAIL durante importação porque o pacote `banco_agil.responses` ainda não existe.

- [ ] **Step 4: Criar o catálogo central fechado**

Definir em `catalog.py`:

```python
class EventDefinition(Model):
    communication_goal: str
    policy: ResponsePolicy
    allowed_actions: tuple[ResponseAction, ...] = ()
    constraints: tuple[str, ...] = ()
    fallback: str = Field(min_length=1)


EVENT_DEFINITIONS: dict[ResponseEvent, EventDefinition] = {
    ResponseEvent.CREDIT_LIMIT_FOUND: EventDefinition(
        communication_goal="Informe o limite atual confirmado e ofereça ajuda sem prometer aumento.",
        policy=ResponsePolicy(
            required_placeholders=frozenset({"current_limit"}),
            allowed_placeholders=frozenset({"current_limit"}),
            expected_questions=0,
            forbidden_patterns=(r"aprova(?:do|ção) garantida", r"R\$\s*\d"),
        ),
        allowed_actions=(ResponseAction.REQUEST_CREDIT_INCREASE,),
        fallback=(
            "Seu limite de crédito atual é **{{current_limit}}**.\n\n"
            "Se quiser, também posso avaliar um aumento para você."
        ),
    ),
    ResponseEvent.CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW: EventDefinition(
        communication_goal="Informe a reprovação sem julgamento e ofereça a entrevista financeira.",
        policy=ResponsePolicy(
            allowed_placeholders=frozenset({"current_limit"}),
            expected_questions=1,
            forbidden_patterns=(r"\baprovad[oa]\b", r"aprovação garantida", r"R\$\s*\d"),
        ),
        allowed_actions=(ResponseAction.START_CREDIT_INTERVIEW,),
        fallback=(
            "Não consegui aprovar esse valor agora, então seu limite continua o mesmo.\n\n"
            "Podemos fazer uma **entrevista financeira rápida** e analisar novamente com "
            "informações atualizadas. **Quer continuar?**"
        ),
    ),
}
```

Completar o dicionário para todos os valores de `ResponseEvent`, movendo os textos de fallback
existentes de `presentation.py`, `INFORMATION_RESPONSES` e `banking_flow.py`. Os fallbacks de
`AUTHENTICATION_SUCCEEDED`, `CREDIT_LIMIT_FOUND`, `CREDIT_INCREASE_APPROVED` e
`EXCHANGE_QUOTE_FOUND` devem usar respectivamente `{{customer_first_name}}`,
`{{current_limit}}`, `{{new_limit}}` e `{{exchange_rate}}`.

Definir `CRITICAL_MESSAGES` com os textos atuais dos erros equivalentes e cobertura exata para
todos os valores de `CriticalFailureCode`.

- [ ] **Step 5: Implementar factory e renderer puros**

```python
PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
FINANCIAL_LITERAL_PATTERN = re.compile(r"R\$\s*\d", re.IGNORECASE)


def build_response_brief(outcome: FlowOutcome, user_tone: UserTone) -> ResponseBrief:
    definitions = [EVENT_DEFINITIONS[item.event] for item in outcome.directives]
    return ResponseBrief(
        directives=tuple(
            ResponseDirective(
                event=item.event,
                communication_goal=definition.communication_goal,
                public_context=item.public_context,
            )
            for item, definition in zip(outcome.directives, definitions, strict=True)
        ),
        required_placeholders=frozenset().union(
            *(item.policy.required_placeholders for item in definitions)
        ),
        allowed_placeholders=frozenset().union(
            *(item.policy.allowed_placeholders for item in definitions)
        ),
        allowed_actions=tuple(
            dict.fromkeys(action for item in definitions for action in item.allowed_actions)
        ),
        next_step=outcome.next_step,
        expected_questions=outcome.expected_questions,
        user_tone=user_tone,
        constraints=tuple(dict.fromkeys(c for item in definitions for c in item.constraints)),
    )
```

`render_response` deve validar o texto antes de substituir qualquer valor. Ao falhar, deve
montar os blocos de fallback na ordem das diretivas, validar o catálogo e somente então inserir
os valores de `outcome.protected_values`. Retornar `RenderedResponse`, nunca lançar conteúdo do
modelo na exceção. Placeholder repetido é inválido mesmo quando autorizado, pois poderia repetir
um dado protegido fora da estrutura prevista.

- [ ] **Step 6: Adicionar teste de diretivas combinadas do Review Focus**

```python
def test_combined_authentication_and_limit_have_one_cohesive_fallback():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="authentication_succeeded"),
            OutcomeDirective(event="credit_limit_found"),
        ),
        specialist="credit",
        protected_values={
            "customer_first_name": "Ana",
            "current_limit": "R$ 2.500,00",
        },
        next_step="idle",
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(outcome, brief, generated=None)

    assert rendered.text.count("Ana") == 1
    assert rendered.text.count("R$ 2.500,00") == 1
    assert rendered.text.count("?") <= 1
```

- [ ] **Step 7: Executar testes e commitar**

```bash
uv run pytest tests/unit/test_response_renderer.py tests/unit/test_response_models.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/responses src/banco_agil/models/responses.py tests/unit/test_response_renderer.py
git commit -m "feat(respostas): valida mensagens e fallbacks"
```

---

### Task 3: Segunda chamada e responders especializados

**Files:**
- Modify: `src/banco_agil/providers/groq.py`
- Modify: `src/banco_agil/agents/factory.py`
- Modify: `tests/integration/test_groq.py`

**Interfaces:**
- Consumes: `ResponseBrief`, `SafeConversationSummary` e `GeneratedMessage` das Tasks 1 e 2.
- Produces: `LLMProvider.compose(brief, previous_summary=None) -> GeneratedMessage` e `create_responder(kind, llm)` sem tools.

- [ ] **Step 1: Escrever teste falhando para prompt seguro de composição**

```python
async def test_compose_sends_brief_without_protected_values(data_dir):
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"text":"Seu limite é {{current_limit}}."}'}}]},
        )

    provider = GroqProvider(
        "test", "test", BankingFlow(data_dir).tools, httpx.MockTransport(respond)
    )
    brief = ResponseBrief(
        directives=(ResponseDirective(
            event="credit_limit_found",
            communication_goal="Informe o limite confirmado.",
        ),),
        required_placeholders=frozenset({"current_limit"}),
        allowed_placeholders=frozenset({"current_limit"}),
        next_step="idle",
        expected_questions=0,
        user_tone="neutral",
    )

    result = await provider.compose(brief)

    assert result.text == "Seu limite é {{current_limit}}."
    serialized = json.dumps(bodies[0], ensure_ascii=False)
    assert "2.500" not in serialized
    assert "CPF" not in serialized
```

- [ ] **Step 2: Escrever teste falhando que garante responder sem tools**

```python
def test_responder_has_no_tools(data_dir):
    agent = create_responder(
        AgentType.CREDIT,
        GroqLLM("test", "test"),
    )

    assert agent.tools == []
    assert not agent.allow_delegation
```

- [ ] **Step 3: Executar testes e confirmar RED**

Run: `uv run pytest tests/integration/test_groq.py -k 'compose or responder' -q`

Expected: FAIL porque `GroqProvider.compose` e `create_responder` ainda não existem.

- [ ] **Step 4: Separar factories de interpretação e resposta**

Manter `PERSONA` compartilhada e criar responsabilidades de resposta que usem apenas brief,
resumo seguro e schema. O responder deve ter `tools=[]`, `max_iter=1`, `cache=False` e
`allow_delegation=False`.

```python
def create_responder(kind: AgentType, llm: BaseLLM) -> Agent:
    return Agent(
        role=f"Lia — resposta de {kind.value}",
        goal=RESPONSE_RESPONSIBILITIES[kind],
        backstory=PERSONA,
        llm=llm,
        tools=[],
        allow_delegation=False,
        verbose=False,
        cache=False,
        max_iter=1,
        max_retry_limit=0,
        guardrail_max_retries=0,
    )
```

- [ ] **Step 5: Adicionar `compose` ao protocolo e ao provider**

```python
class LLMProvider(Protocol):
    async def interpret(
        self, message: str, state: SessionState, *, previous_summary: SafeConversationSummary | None
    ) -> TurnResult: ...

    async def compose(
        self,
        brief: ResponseBrief,
        *,
        previous_summary: SafeConversationSummary | None = None,
    ) -> GeneratedMessage: ...
```

`compose` deve criar um `GroqLLM` novo com orçamento próprio, schema de `GeneratedMessage`, brief
serializado e resumo seguro. Não incluir estado, tools, mensagem original, resposta anterior ou
valores protegidos. Preservar o tratamento atual de 400 `json_validate_failed`, 429, truncamento
e uma correção de formato.

- [ ] **Step 6: Executar integração do provider e suíte de regressão**

Run: `uv run pytest tests/integration/test_groq.py -q`

Expected: PASS.

- [ ] **Step 7: Commitar**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/providers/groq.py src/banco_agil/agents/factory.py tests/integration/test_groq.py
git commit -m "feat(agentes): adiciona composição especializada"
```

---

### Task 4: Orquestração em duas chamadas e histórico seguro

**Files:**
- Modify: `src/banco_agil/conversation.py`
- Modify: `src/banco_agil/presentation.py`
- Modify: `tests/integration/test_continuous_conversation.py`
- Modify: `tests/integration/test_privacy_and_errors.py`

**Interfaces:**
- Consumes: `LLMProvider.compose`, renderer, catálogo crítico e contratos de resposta.
- Produces: `Conversation.start() -> str`, `Conversation.send() -> str`, `last_summary: SafeConversationSummary | None` e suporte temporário a `str | FlowOutcome | CriticalFailure` durante a migração.

- [ ] **Step 1: Escrever teste falhando para ordem interpretação → Flow → composição**

Adicionar no próprio `tests/integration/test_continuous_conversation.py` estes doubles explícitos,
ajustando somente imports para os contratos criados nas Tasks 1–3:

```python
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


class RecordingProvider:
    def __init__(self, calls):
        self.calls = calls
        self.interpret_contexts = []

    async def interpret(self, message, state, *, previous_summary=None):
        self.calls.append("interpret")
        self.interpret_contexts.append(previous_summary)
        return TriageTurnResult(detected_intent="credit_limit_query")

    async def compose(self, brief, *, previous_summary=None):
        self.calls.append("compose")
        return GeneratedMessage(text="Seu limite atual é {{current_limit}}.")
```

```python
async def test_normal_turn_interprets_executes_and_composes_in_order(data_dir):
    calls = []
    flow = RecordingFlow(calls)
    provider = RecordingProvider(calls)
    conversation = Conversation(flow, provider)

    response = await conversation.send("Quero consultar meu limite")

    assert calls == ["interpret", "flow", "compose"]
    assert response == "Seu limite atual é **R$ 1.000,00**."
```

Os doubles `RecordingFlow` e `RecordingProvider` devem retornar contratos reais, sem mocks de
métodos internos.

- [ ] **Step 2: Escrever teste falhando para histórico seguro**

```python
async def test_next_turn_uses_safe_summary_instead_of_rendered_reply(data_dir):
    provider = RecordingProvider([])
    conversation = Conversation(RecordingFlow([]), provider)

    first = await conversation.send("CPF 00000000001, nascimento 15/01/1990")
    await conversation.send("Como funciona?")

    assert "1.000" in first
    serialized = json.dumps(
        provider.interpret_contexts[1].model_dump(mode="json"),
        ensure_ascii=False,
    )
    assert "Ana" not in serialized
    assert "00000000001" not in serialized
    assert "1990" not in serialized
    assert "1.000" not in serialized
    assert "credit_limit_found" in serialized
```

- [ ] **Step 3: Executar testes e confirmar RED**

Run: `uv run pytest tests/integration/test_continuous_conversation.py -k 'order or safe_summary' -q`

Expected: FAIL porque `Conversation` ainda usa uma chamada e `last_reply`.

- [ ] **Step 4: Implementar pipeline com compatibilidade temporária**

```python
async def _render_outcome(
    self,
    outcome: FlowOutcome,
    user_tone: UserTone,
) -> str:
    brief = build_response_brief(outcome, user_tone)
    try:
        generated = await self.provider.compose(
            brief,
            previous_summary=self.last_summary,
        )
        rendered = render_response(outcome, brief, generated)
    except LLMError:
        rendered = render_response(
            outcome,
            brief,
            generated=None,
            fallback_reason=FallbackReason.PROVIDER_UNAVAILABLE,
        )
    self.last_summary = safe_summary(outcome, brief)
    return rendered.text
```

`send` deve continuar aceitando string legada somente enquanto os domínios são migrados. Para
`CriticalFailure`, resolver `CRITICAL_MESSAGES[code]`, não chamar `compose` e não substituir o
último resumo válido. Para um outcome, nunca usar `result.message` ou `with_lia_voice`.

Adicionar `start()` que compõe um outcome `WELCOME` sem chamar `interpret`, usando o fallback se
o provider falhar.

- [ ] **Step 5: Executar testes focados e commitar**

```bash
uv run pytest tests/integration/test_continuous_conversation.py tests/integration/test_privacy_and_errors.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/conversation.py src/banco_agil/presentation.py tests/integration/test_continuous_conversation.py tests/integration/test_privacy_and_errors.py
git commit -m "feat(conversa): orquestra respostas em duas etapas"
```

---

### Task 5: Migrar o especialista de crédito

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `src/banco_agil/models/errors.py`
- Modify: `tests/flow/test_credit_exchange_flow.py`
- Modify: `tests/flow/test_interview_flow.py`
- Modify: `tests/integration/test_continuous_conversation.py`

**Interfaces:**
- Consumes: `FlowOutcome`, `OutcomeDirective`, `CriticalFailure`, `ResponseEvent` e `NextStep`.
- Produces: `_credit(result) -> FlowOutcome | CriticalFailure | str` temporariamente e `_evaluate_credit() -> FlowOutcome | CriticalFailure`.

- [ ] **Step 1: Converter assertivas de crédito para eventos e observar RED**

```python
async def test_credit_query_returns_confirmed_limit_outcome(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow)

    outcome = await flow.process(
        CreditTurnResult(detected_intent="credit_limit_query")
    )

    assert [item.event for item in outcome.directives] == ["credit_limit_found"]
    assert outcome.protected_values == {"current_limit": "R$ 1.000,00"}
    assert outcome.next_step == "idle"


async def test_rejected_credit_offers_interview_as_state_decision(data_dir):
    flow = await rejected_flow(data_dir)
    outcome = await flow.process(CreditTurnResult())

    assert outcome.directives[-1].event == "credit_increase_rejected_offer_interview"
    assert outcome.next_step == "await_interview_confirmation"
    assert outcome.expected_questions == 1
```

Run: `uv run pytest tests/flow/test_credit_exchange_flow.py -q`

Expected: FAIL porque `_credit` ainda retorna strings.

- [ ] **Step 2: Criar helpers de outcome sem texto**

```python
@staticmethod
def _outcome(
    specialist: AgentType,
    *events: ResponseEvent,
    protected_values: dict[str, str] | None = None,
    next_step: NextStep = NextStep.IDLE,
    expected_questions: int = 0,
    public_context: dict[ResponseEvent, dict[str, str | int | bool]] | None = None,
) -> FlowOutcome:
    contexts = public_context or {}
    return FlowOutcome(
        directives=tuple(
            OutcomeDirective(event=event, public_context=contexts.get(event, {}))
            for event in events
        ),
        specialist=specialist,
        protected_values=protected_values or {},
        next_step=next_step,
        expected_questions=expected_questions,
    )
```

Manter `_money` como formatter local para valores protegidos. Converter consulta, pedido de
valor, aprovação, reprovação com oferta, reprovação final e validação de limite para os eventos
correspondentes. `InvalidCreditLimitError` deve virar `INVALID_INPUT` com
`NextStep.AWAIT_REQUESTED_LIMIT`; `RepositoryError` e `ScoreRangeNotFoundError` continuam
críticos e são mapeados para `CriticalFailure`.

- [ ] **Step 3: Confirmar GREEN nos testes de crédito migrados**

Run: `uv run pytest tests/flow/test_credit_exchange_flow.py tests/flow/test_interview_flow.py tests/integration/test_continuous_conversation.py -q`

Expected: PASS.

- [ ] **Step 4: Verificar operação única explicitamente**

```python
async def test_credit_composition_failure_does_not_create_second_request(data_dir):
    class BrokenComposerProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_increase",
                requested_limit=2000,
            )

        async def compose(self, brief, *, previous_summary=None):
            raise LLMError()

    flow = BankingFlow(data_dir)
    conversation = Conversation(flow, BrokenComposerProvider())

    response = await conversation.send("Quero limite total de 2000")

    requests = flow.tools.credit.requests.read()
    assert len(requests) == 1
    assert requests[0].status_pedido == "aprovado"
    assert flow.tools.credit.customers.require("00000000001").limite_credito == 2000
    assert "R$ 2.000,00" in response
```

- [ ] **Step 5: Commitar**

```bash
uv run pytest tests/flow/test_credit_exchange_flow.py tests/flow/test_interview_flow.py tests/integration/test_continuous_conversation.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/flow/banking_flow.py src/banco_agil/models/errors.py tests/flow/test_credit_exchange_flow.py tests/flow/test_interview_flow.py tests/integration/test_continuous_conversation.py
git commit -m "feat(credito): retorna outcomes para composição"
```

---

### Task 6: Migrar a entrevista financeira

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `tests/flow/test_interview_flow.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: `_outcome` e contratos das Tasks 1 e 5.
- Produces: `_interview(result) -> FlowOutcome | CriticalFailure` e contexto público `interview_field` para `INTERVIEW_QUESTION`.

- [ ] **Step 1: Escrever testes falhando para início e pergunta do campo atual**

```python
async def test_interview_start_returns_intro_and_first_question(data_dir):
    flow = await rejected_flow(data_dir)
    outcome = await flow.process(CreditTurnResult(interview_accepted=True))

    assert [item.event for item in outcome.directives] == [
        "interview_started",
        "interview_question",
    ]
    assert outcome.directives[-1].public_context == {"interview_field": "monthly_income"}
    assert outcome.next_step == "await_interview_field"
    assert outcome.expected_questions == 1


async def test_interview_ignores_generated_question_when_advancing_state(data_dir):
    flow = await rejected_flow(data_dir)
    await flow.process(CreditTurnResult(interview_accepted=True))
    outcome = await flow.process(InterviewTurnResult(monthly_income=5000))

    assert flow.state.interview.monthly_income == 5000
    assert outcome.directives[-1].public_context == {"interview_field": "employment_type"}
```

- [ ] **Step 2: Executar e confirmar RED**

Run: `uv run pytest tests/flow/test_interview_flow.py -k 'start_returns or generated_question' -q`

Expected: FAIL porque entrevista ainda retorna `_interview_question()` como string.

- [ ] **Step 3: Substituir perguntas por diretivas**

Criar `_interview_question_outcome()` que consulta somente `state.interview.next_missing_field()`
e retorna `INTERVIEW_QUESTION` com `public_context={"interview_field": field}`. O Flow não deve
manter texto de renda, emprego, despesas, dependentes ou dívida. O responder recebe o nome do
campo e as opções permitidas vindas do catálogo.

Ao completar a entrevista, preservar persistência de score, `reanalysis_pending` e transição;
os resultados finais vêm dos eventos `INTERVIEW_REANALYSIS_APPROVED` ou
`INTERVIEW_REANALYSIS_REJECTED` produzidos por `_evaluate_credit`.

- [ ] **Step 4: Atualizar teste de progresso da UI sem depender do texto**

```python
def test_interview_progress_survives_agent_generated_question(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    flow = BankingFlow(data_dir)
    provider = ScriptedProvider(
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
    )
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(flow, provider)
    app.run()

    app.chat_input[0].set_value("Quero um limite de 4000").run()
    app.chat_input[0].set_value("Sim").run()

    assert not app.exception
    assert flow.state.interview.next_missing_field() == "monthly_income"
    assert app.get("progress")[0].proto.value == 0
```

Atualizar o `ScriptedProvider` já existente nesse arquivo para receber duas sequências nomeadas,
`interpretations` e `compositions`, e implementar `compose()` retornando o próximo
`GeneratedMessage`. Migrar as instanciações antigas no mesmo arquivo nessa etapa.

- [ ] **Step 5: Executar e commitar**

```bash
uv run pytest tests/flow/test_interview_flow.py tests/integration/test_ui.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/flow/banking_flow.py tests/flow/test_interview_flow.py tests/integration/test_ui.py
git commit -m "feat(entrevista): delega formulação das perguntas"
```

---

### Task 7: Migrar câmbio e informações sobre o serviço

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `src/banco_agil/presentation.py`
- Modify: `tests/flow/test_credit_exchange_flow.py`
- Modify: `tests/flow/test_service_information.py`
- Modify: `tests/integration/test_exchange.py`

**Interfaces:**
- Consumes: outcome, catálogo e renderer.
- Produces: `_exchange(result) -> FlowOutcome | CriticalFailure` e `_service_information(topic) -> FlowOutcome` sem textos no Flow.

- [ ] **Step 1: Escrever testes falhando para cotação protegida e retomada**

```python
async def test_exchange_outcome_protects_quote(data_dir):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"USDBRL": {"bid": "5", "timestamp": "1750000000"}},
        )
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "exchange_rate")

    outcome = await flow.process(ExchangeTurnResult(currency="USD"))

    assert [item.event for item in outcome.directives] == ["exchange_quote_found"]
    assert outcome.protected_values["exchange_rate"] == "1 USD = R$ 5.0000"
    assert "5.0000" not in outcome.model_dump_json(exclude={"protected_values"})


async def test_information_during_pending_credit_has_two_directives(data_dir):
    flow = BankingFlow(data_dir)
    await authenticate(flow, "credit_limit_increase")

    outcome = await flow.process(
        CreditTurnResult(information_topic="credit_evaluation")
    )

    assert [item.event for item in outcome.directives] == [
        "service_information",
        "resume_pending_step",
    ]
    assert outcome.next_step == "await_requested_limit"
    assert outcome.expected_questions == 1
```

- [ ] **Step 2: Executar e confirmar RED**

Run: `uv run pytest tests/flow/test_credit_exchange_flow.py tests/flow/test_service_information.py -q`

Expected: FAIL porque os métodos ainda retornam textos.

- [ ] **Step 3: Converter câmbio para outcomes**

`REQUEST_CURRENCY` usa `NextStep.AWAIT_CURRENCY` e uma pergunta. `EXCHANGE_QUOTE_FOUND` guarda
cotação e timestamp formatado apenas em `protected_values`. `InvalidCurrencyError` vira
`UNSUPPORTED_CURRENCY`; indisponibilidade do serviço vira
`CriticalFailure(EXTERNAL_SERVICE_UNAVAILABLE)`.

- [ ] **Step 4: Converter informações e retomada para diretivas**

Mover o conteúdo factual de `INFORMATION_RESPONSES` para `public_context={"topic": topic.value}`
e para os objetivos do catálogo. `_pending_question` deixa de produzir string e passa a retornar
`NextStep`; quando não for `IDLE`, adicionar `RESUME_PENDING_STEP` e definir uma pergunta.

O tópico `INTERNAL_DETAILS` envia somente `topic="internal_details"`; nenhum nome de framework,
provider, prompt ou ferramenta entra no brief.

- [ ] **Step 5: Executar testes e commitar**

```bash
uv run pytest tests/flow/test_credit_exchange_flow.py tests/flow/test_service_information.py tests/integration/test_exchange.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/flow/banking_flow.py src/banco_agil/presentation.py tests/flow/test_credit_exchange_flow.py tests/flow/test_service_information.py tests/integration/test_exchange.py
git commit -m "feat(atendimento): estrutura câmbio e informações"
```

---

### Task 8: Migrar triagem, autenticação, boas-vindas e encerramento

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `src/banco_agil/conversation.py`
- Modify: `app.py`
- Modify: `tests/flow/test_authentication_flow.py`
- Modify: `tests/integration/test_continuous_conversation.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: todos os domínios já migrados.
- Produces: `_triage(result) -> FlowOutcome | CriticalFailure`, `process(result) -> FlowOutcome | CriticalFailure`, `Conversation.start()` usado pela UI e remoção do caminho legado de strings.

- [ ] **Step 1: Escrever teste falhando para diretivas combinadas de autenticação**

```python
async def test_authentication_and_limit_are_combined_without_name_in_brief(data_dir):
    flow = BankingFlow(data_dir)

    outcome = await flow.process(
        TriageTurnResult(
            cpf="00000000001",
            birth_date="1990-01-15",
            detected_intent="credit_limit_query",
        )
    )

    assert [item.event for item in outcome.directives] == [
        "authentication_succeeded",
        "credit_limit_found",
    ]
    assert outcome.protected_values == {
        "customer_first_name": "Ana",
        "current_limit": "R$ 1.000,00",
    }
```

- [ ] **Step 2: Escrever teste falhando para terceira tentativa e sessão encerrada**

```python
async def test_third_authentication_failure_is_critical_and_future_turn_skips_llm(data_dir):
    flow = BankingFlow(data_dir)
    invalid = TriageTurnResult(cpf="00000000001", birth_date="2000-01-01")
    await flow.process(invalid)
    await flow.process(invalid)

    failure = await flow.process(invalid)

    assert failure.code == "auth_attempts_exhausted"
    assert flow.state.status == "finished"
```

- [ ] **Step 3: Escrever teste falhando para despedida composta no turno atual**

Adicionar no arquivo de teste um provider mínimo que mede as duas chamadas:

```python
class CountingProvider:
    def __init__(self):
        self.interpret_calls = 0
        self.compose_calls = 0

    async def interpret(self, message, state, *, previous_summary=None):
        self.interpret_calls += 1
        return TriageTurnResult(end_requested=True)

    async def compose(self, brief, *, previous_summary=None):
        self.compose_calls += 1
        return GeneratedMessage(text="Até a próxima!")
```

```python
async def test_end_turn_is_composed_but_next_turn_uses_fixed_closed_message(data_dir):
    provider = CountingProvider()
    conversation = Conversation(BankingFlow(data_dir), provider)

    goodbye = await conversation.send("encerrar")
    closed = await conversation.send("oi")

    assert "até" in goodbye.casefold()
    assert provider.compose_calls == 1
    assert provider.interpret_calls == 0
    assert closed == CRITICAL_MESSAGES[CriticalFailureCode.SESSION_FINISHED]
```

- [ ] **Step 4: Executar e confirmar RED**

Run: `uv run pytest tests/flow/test_authentication_flow.py tests/integration/test_continuous_conversation.py -q`

Expected: FAIL porque triagem e encerramento ainda retornam strings.

- [ ] **Step 5: Migrar triagem e combinar outcomes**

Substituir solicitações de CPF/nascimento, retries, identidade confirmada e opções pelos eventos
correspondentes. `_resume_intent()` deve receber diretivas prefixadas e concatená-las ao outcome
do especialista sem duplicar `protected_values`. Colisão de uma mesma chave com valores
diferentes deve produzir `CriticalFailure(INVALID_INTERNAL_STATE)`.

Na terceira falha, marcar sessão como encerrada e retornar
`CriticalFailure(AUTH_ATTEMPTS_EXHAUSTED)`. Nas duas primeiras, retornar
`AUTHENTICATION_RETRY` com `remaining_attempts` público e o próximo passo correto.

- [ ] **Step 6: Remover compatibilidade com strings da Conversation**

Depois que todos os domínios retornarem contratos, trocar o tipo de `BankingFlow.process` para
`FlowOutcome | CriticalFailure` e remover o ramo legado. Comando inequívoco de encerramento
continua sem interpretação, mas seu `FlowOutcome(CONVERSATION_CLOSED)` passa pelo compositor.

- [ ] **Step 7: Inicializar a UI com `Conversation.start()`**

Em `app.py`, remover importação e inserção direta de `WELCOME`. Ao criar a conversa, executar
`asyncio.run(conversation.start())` uma vez e guardar a mensagem retornada. Garantir que reruns
do Streamlit não chamem `start()` novamente.

- [ ] **Step 8: Executar testes de Flow e UI e commitar**

```bash
uv run pytest tests/flow tests/integration/test_continuous_conversation.py tests/integration/test_ui.py -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
git add src/banco_agil/flow/banking_flow.py src/banco_agil/conversation.py app.py tests/flow tests/integration/test_continuous_conversation.py tests/integration/test_ui.py
git commit -m "feat(triagem): conclui pipeline estruturado"
```

---

### Task 9: Remover apresentação legada, fechar observabilidade e validar privacidade

**Files:**
- Modify: `src/banco_agil/models/agent_outputs.py`
- Modify: `src/banco_agil/presentation.py`
- Modify: `src/banco_agil/models/errors.py`
- Modify: `src/banco_agil/observability.py`
- Modify: `src/banco_agil/providers/groq.py`
- Modify: `tests/unit/test_presentation.py`
- Modify: `tests/integration/test_privacy_and_errors.py`
- Modify: `tests/integration/test_groq.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: pipeline totalmente migrado.
- Produces: ausência de `message`, `last_reply`, `with_lia_voice`, `without_identity_confirmation` e mensagens normais no Flow; eventos seguros de observabilidade.

- [ ] **Step 1: Escrever teste falhando que proíbe texto livre no interpretador**

```python
def test_interpreter_result_has_no_message_field():
    assert "message" not in TurnResult.model_fields
    with pytest.raises(ValidationError):
        TriageTurnResult(message="texto não autorizado")
```

- [ ] **Step 2: Escrever teste falhando para privacidade nas duas chamadas**

```python
async def test_protected_values_only_exist_in_first_user_input(data_dir):
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
            {"text": "A análise considera os dados do cadastro."},
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

    await conversation.send(
        "Meu limite, CPF 00000000001, nascimento 15/01/1990"
    )
    await conversation.send("Como funciona o aumento?")

    interpret_first = json.dumps(bodies[0], ensure_ascii=False)
    compose_first = json.dumps(bodies[1], ensure_ascii=False)
    interpret_second = json.dumps(bodies[2], ensure_ascii=False)
    assert "00000000001" in interpret_first
    for serialized in (compose_first, interpret_second):
        assert "00000000001" not in serialized
        assert "15/01/1990" not in serialized
        assert "Ana" not in serialized
        assert "1.000" not in serialized
```

- [ ] **Step 3: Escrever teste falhando para observabilidade sem conteúdo**

```python
async def test_composition_fallback_log_has_reason_but_no_message(data_dir, caplog):
    class InvalidComposerProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="credit_limit_query",
            )

        async def compose(self, brief, *, previous_summary=None):
            return GeneratedMessage(
                text="Seu limite é {{current_limit}}. Aprovação garantida."
            )

    conversation = Conversation(BankingFlow(data_dir), InvalidComposerProvider())

    await conversation.send("Quero consultar meu limite")

    assert "response_composition_fallback" in caplog.text
    assert "policy_rejected" in caplog.text
    assert "R$" not in caplog.text
    assert "00000000001" not in caplog.text
```

- [ ] **Step 4: Executar e confirmar RED**

Run: `uv run pytest tests/integration/test_privacy_and_errors.py tests/unit/test_presentation.py -q`

Expected: FAIL porque os campos e helpers legados ainda existem e os novos eventos não foram
registrados.

- [ ] **Step 5: Remover legado e adicionar eventos fechados**

Remover `message` de `TurnResult`, `last_reply` da `Conversation`, `with_lia_voice` e
`without_identity_confirmation`. Remover `WELCOME`, `CLOSED`, `OPTIONS` e
`INFORMATION_RESPONSES` depois de confirmar que o catálogo possui os fallbacks equivalentes.

Adicionar ao enum `Event`:

```python
RESPONSE_COMPOSITION_STARTED = "response_composition_started"
RESPONSE_COMPOSITION_SUCCEEDED = "response_composition_succeeded"
RESPONSE_COMPOSITION_FALLBACK = "response_composition_fallback"
RESPONSE_POLICY_REJECTED = "response_policy_rejected"
```

Estender `record` somente com `reason` enumerado; não aceitar `message`, `prompt`, `value` ou
payload arbitrário.

- [ ] **Step 6: Executar toda a suíte com cobertura**

Run: `uv run pytest -q --cov=src/banco_agil --cov-report=term-missing --cov-fail-under=85`

Expected: PASS, zero falhas e cobertura total de pelo menos 85%.

- [ ] **Step 7: Executar qualidade e busca estrutural**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
! rg -n 'return\s+[f]?"|return\s+\(' src/banco_agil/flow/banking_flow.py
! rg -n 'last_reply|with_lia_voice|without_identity_confirmation' src tests
```

Expected: todos os comandos retornam sucesso; as buscas negadas não encontram apresentação
legada. Se o Flow ainda tiver retornos literais não destinados ao usuário, substituir a busca
por uma verificação AST que distingue strings internas antes de commitar.

- [ ] **Step 8: Commitar fechamento do pipeline**

```bash
git add src/banco_agil tests app.py
git commit -m "refactor(agentes): remove respostas montadas pelo flow"
```

---

## Verificação final do plano

Executar no HEAD final:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q --cov=src/banco_agil --cov-report=term-missing --cov-fail-under=85
git diff --check
git status --short --branch
```

Esperado:

- Ruff sem violações;
- todos os arquivos formatados;
- suíte completa sem falhas;
- cobertura total de pelo menos 85%;
- working tree limpo;
- commits atômicos exatamente nas fronteiras funcionais deste plano.
