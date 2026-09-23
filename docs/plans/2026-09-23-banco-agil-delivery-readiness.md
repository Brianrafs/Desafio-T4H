# Banco Ágil Delivery Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o commit `154c2d1` em uma entrega pública, reproduzível e melhor apresentada, fechando as lacunas de robustez, UX, CI e documentação identificadas no relatório de avaliação.

**Architecture:** Preservar a arquitetura atual - CrewAI Agents para interpretação, `BankingFlow` para estado e autorização, Services determinísticos para regras, Repositories para CSV e Streamlit para apresentação. As mudanças adicionam validações no limite correto, funções explícitas de restauração da demo, feedback visual derivado do estado e automação de qualidade, sem mover regras financeiras para a UI ou para o LLM.

**Tech Stack:** Python 3.13, CrewAI 1.x, Pydantic 2.x, Streamlit 1.x, httpx, pytest, pytest-asyncio, pytest-cov, Ruff, uv e GitHub Actions.

**Spec:** `docs/plans/2026-09-22-banco-agil-design.md`

**Change brief:** `2026-09-23-relatorio-avaliacao-desafio-t4h.md`, avaliação do commit `154c2d1e4c7fe8e9c89e062ec82085198d115ce5`.

## Global Constraints

- Partir do commit `154c2d1e4c7fe8e9c89e062ec82085198d115ce5`; se `main` avançar, comparar as mudanças antes de executar este plano.
- Manter `requires-python = ">=3.13,<3.14"` até existir uma matriz comprovada para outras versões.
- Manter `crewai[litellm]>=1.0,<2`, `httpx>=0.28,<1`, `pydantic>=2.11,<3`, `pydantic-settings>=2.10,<3` e `streamlit>=1.57,<2`.
- Nenhuma decisão financeira, autenticação ou transição pode depender do LLM.
- Não incluir CPF, nascimento, renda, despesas, dívida, prompts ou secrets em logs.
- Testes automatizados não podem depender de Groq ou AwesomeAPI reais.
- Usar somente clientes e informações fictícias na demonstração e nos assets.
- Preservar os schemas dos três CSVs exigidos pelo desafio.
- Usar escrita atômica para qualquer alteração nos CSVs de runtime.
- Não adicionar banco de dados, Langfuse, dark mode ou abstrações novas fora do escopo desta entrega.
- Commits devem ser atômicos, em português e seguir Conventional Commits.
- Não tornar o repositório público antes de concluir a auditoria de secrets e a verificação final.

## Review Focus

- Faixas de score com lacuna interna devem falhar na inicialização, em vez de quebrar somente na primeira solicitação daquele score; coberto na Task 1.
- Restaurar a demo não pode apagar arquivos alheios nem manter limites, scores ou solicitações alterados; coberto nas Tasks 2 e 3.
- Mudar de crédito para câmbio enquanto o valor está pendente deve informar que nenhum pedido foi enviado; coberto na Task 6.
- Falhas de output e inputs ambíguos não podem consumir tentativa de autenticação, iniciar entrevista ou alterar estado protegido; coberto na Task 7.
- A interface deve mostrar privacidade, autenticação e progresso sem renderizar PII; coberto nas Tasks 4 e 5.

---

## Execution Preflight

Executar antes da Task 1:

```bash
git status --short
git rev-parse HEAD
uv sync --locked
uv run pytest -q
uv run ruff check src tests app.py
uv run ruff format --check src tests app.py
```

Resultados esperados:

- worktree limpo;
- `HEAD` igual a `154c2d1e4c7fe8e9c89e062ec82085198d115ce5`, ou mudança revisada explicitamente;
- suíte existente verde;
- Ruff lint e format verdes.

Se a baseline falhar, interromper o plano e diagnosticar a falha antes de modificar código.

## Planned File Map

| Arquivo | Responsabilidade após o plano |
|---|---|
| `src/banco_agil/repositories/score_range_repository.py` | validar cobertura contínua de score de 0 a 1000 |
| `src/banco_agil/repositories/bootstrap.py` | inicializar e restaurar somente os CSVs conhecidos da demo |
| `src/banco_agil/models/state.py` | expor progresso tipado da entrevista |
| `src/banco_agil/flow/banking_flow.py` | registrar outputs inválidos e explicar interrupção do pedido de crédito |
| `app.py` | aviso de privacidade, status seguro, progresso e reset confirmado |
| `tests/unit/test_repositories.py` | invariantes de faixas e duplicidade |
| `tests/unit/test_bootstrap.py` | inicialização e restauração idempotente dos dados fictícios |
| `tests/unit/test_models.py` | contrato de progresso da entrevista |
| `tests/flow/test_authentication_flow.py` | tentativas incompletas e output incompatível |
| `tests/flow/test_credit_exchange_flow.py` | troca de assunto com crédito incompleto |
| `tests/flow/test_interview_flow.py` | aceite ambíguo e recusa repetida |
| `tests/integration/test_privacy_and_errors.py` | ausência de PII em falhas e logs |
| `tests/integration/test_ui.py` | avisos, status, progresso e restauração da demo |
| `pyproject.toml` / `uv.lock` | cobertura como dependência reproduzível |
| `.github/workflows/ci.yml` | verificação automática do commit e PR |
| `README.md` | cumprir as seis seções obrigatórias e orientar a demonstração |
| `docs/assets/banco-agil-home.png` | evidência visual usando apenas dados fictícios |

### Task 1: Fechar invariantes dos repositories

**Files:**
- Modify: `src/banco_agil/repositories/score_range_repository.py`
- Modify: `tests/unit/test_repositories.py`

**Interfaces:**
- Consumes: `ScoreRangeRepository.read() -> list[ScoreRange]`, `CustomerRepository.read()`, `CreditRequestRepository.read()`.
- Produces: `ScoreRangeRepository.read()` garante cobertura ordenada, contínua e completa de 0 a 1000; as exceções continuam sendo `RepositoryError`.

- [ ] **Step 1: Escrever testes para cobertura completa e duplicidades**

Adicionar a `tests/unit/test_repositories.py`:

```python
def test_score_ranges_must_cover_zero_to_thousand_without_gaps(data_dir):
    repository = ScoreRangeRepository(data_dir)
    rows = repository.read()

    rows[0].score_min = 1
    repository.write(rows)
    with pytest.raises(RepositoryError):
        repository.read()

    rows[0].score_min = 0
    rows[1].score_min = rows[0].score_max + 2
    repository.write(rows)
    with pytest.raises(RepositoryError):
        repository.read()

    rows[1].score_min = rows[0].score_max + 1
    rows[-1].score_max = 999
    repository.write(rows)
    with pytest.raises(RepositoryError):
        repository.read()


def test_duplicate_customer_cpf_is_rejected(data_dir):
    repository = CustomerRepository(data_dir)
    rows = repository.read()
    repository.write([*rows, rows[0].model_copy()])
    with pytest.raises(RepositoryError):
        repository.read()


def test_duplicate_credit_request_key_is_rejected(data_dir):
    repository = CreditRequestRepository(data_dir)
    request = CreditRequest(
        cpf_cliente="00000000001",
        data_hora_solicitacao=datetime.now(UTC),
        limite_atual=1000,
        novo_limite_solicitado=1500,
    )
    repository.write([request, request.model_copy()])
    with pytest.raises(RepositoryError):
        repository.read()
```

- [ ] **Step 2: Executar os testes e confirmar a falha específica**

```bash
uv run pytest tests/unit/test_repositories.py -q
```

Esperado: o teste de lacunas falha; os testes de duplicidade passam com a proteção já existente.

- [ ] **Step 3: Implementar validação contínua das faixas**

Substituir a validação de sobreposição em `ScoreRangeRepository.read` por:

```python
def read(self) -> list[ScoreRange]:
    ranges = sorted(super().read(), key=lambda row: row.score_min)
    if not ranges or ranges[0].score_min != 0 or ranges[-1].score_max != 1000:
        raise RepositoryError()
    if any(
        left.score_max + 1 != right.score_min
        for left, right in zip(ranges, ranges[1:], strict=False)
    ):
        raise RepositoryError()
    return ranges
```

- [ ] **Step 4: Executar testes unitários e qualidade**

```bash
uv run pytest tests/unit/test_repositories.py tests/unit/test_credit.py -q
uv run ruff check src/banco_agil/repositories tests/unit/test_repositories.py
uv run ruff format --check src/banco_agil/repositories tests/unit/test_repositories.py
```

Esperado: todos passam.

- [ ] **Step 5: Commit**

```bash
git add src/banco_agil/repositories/score_range_repository.py tests/unit/test_repositories.py
git commit -m "fix(persistencia): valida cobertura das faixas de score"
```

### Task 2: Criar restauração segura dos dados de demonstração

**Files:**
- Modify: `src/banco_agil/repositories/bootstrap.py`
- Create: `tests/unit/test_bootstrap.py`

**Interfaces:**
- Consumes: `CustomerRepository`, `ScoreRangeRepository`, `CreditRequestRepository`.
- Produces: `reset_demo_data(source: Path, destination: Path) -> None`, que sobrescreve apenas os três CSVs conhecidos usando os repositories.

- [ ] **Step 1: Escrever os testes de reset e preservação**

Criar `tests/unit/test_bootstrap.py`:

```python
from pathlib import Path

from banco_agil.models.domain import CreditRequest
from banco_agil.repositories.bootstrap import initialize_demo_data, reset_demo_data
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository


SOURCE = Path(__file__).parents[2] / "data"


def test_reset_demo_data_restores_customers_and_requests(tmp_path):
    initialize_demo_data(SOURCE, tmp_path)
    customers = CustomerRepository(tmp_path)
    customer = customers.require("00000000001")
    customer.limite_credito = 2000
    customer.score_credito = 900
    customers.save(customer)
    requests = CreditRequestRepository(tmp_path)
    requests.add(
        CreditRequest(
            cpf_cliente=customer.cpf,
            data_hora_solicitacao="2026-09-23T12:00:00Z",
            limite_atual=1000,
            novo_limite_solicitado=2000,
        )
    )

    reset_demo_data(SOURCE, tmp_path)

    restored = customers.require("00000000001")
    assert restored.limite_credito == 1000
    assert restored.score_credito == 400
    assert requests.read() == []


def test_reset_demo_data_preserves_unrelated_files(tmp_path):
    initialize_demo_data(SOURCE, tmp_path)
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("preservar", encoding="utf-8")

    reset_demo_data(SOURCE, tmp_path)

    assert unrelated.read_text(encoding="utf-8") == "preservar"
```

- [ ] **Step 2: Executar e confirmar falha por interface ausente**

```bash
uv run pytest tests/unit/test_bootstrap.py -q
```

Esperado: erro de importação de `reset_demo_data`.

- [ ] **Step 3: Implementar cópia explícita e reutilizável**

Alterar `src/banco_agil/repositories/bootstrap.py`:

```python
REPOSITORY_TYPES = (CustomerRepository, ScoreRangeRepository, CreditRequestRepository)


def initialize_demo_data(source: Path, destination: Path) -> None:
    """Copia dados fictícios somente na primeira execução, preservando alterações."""
    destination.mkdir(parents=True, exist_ok=True)
    for repository_type in REPOSITORY_TYPES:
        target = repository_type(destination)
        if not target.path.exists():
            target.write(repository_type(source).read())


def reset_demo_data(source: Path, destination: Path) -> None:
    """Restaura somente os CSVs conhecidos, preservando outros arquivos."""
    destination.mkdir(parents=True, exist_ok=True)
    for repository_type in REPOSITORY_TYPES:
        repository_type(destination).write(repository_type(source).read())
```

- [ ] **Step 4: Executar testes**

```bash
uv run pytest tests/unit/test_bootstrap.py tests/unit/test_repositories.py -q
uv run ruff check src/banco_agil/repositories tests/unit/test_bootstrap.py
uv run ruff format --check src/banco_agil/repositories tests/unit/test_bootstrap.py
```

Esperado: todos passam.

- [ ] **Step 5: Commit**

```bash
git add src/banco_agil/repositories/bootstrap.py tests/unit/test_bootstrap.py
git commit -m "feat(demo): permite restaurar os dados ficticios"
```

### Task 3: Confirmar reinício da sessão e reset da demonstração

**Files:**
- Modify: `app.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: `reset_demo_data(source: Path, destination: Path) -> None`, `Settings.data_dir`.
- Produces: confirmações separadas para reiniciar a sessão e restaurar os CSVs; nenhuma delas altera estado antes do segundo clique.

- [ ] **Step 1: Escrever teste de UI para restauração**

Adicionar a `tests/integration/test_ui.py`:

```python
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
    assert app.session_state.messages[0]["content"] == WELCOME


def test_new_conversation_requires_confirmation(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    flow = BankingFlow(data_dir)
    flow.state.authenticated = True
    flow.state.authenticated_customer_cpf = "00000000001"
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(flow, ScriptedProvider([]))
    app.run()

    app.button(key="request_new_conversation").click().run()
    assert app.session_state.conversation.flow.state.authenticated

    app.button(key="confirm_new_conversation").click().run()
    assert not app.session_state.conversation.flow.state.authenticated
    assert app.session_state.messages == [{"role": "assistant", "content": WELCOME}]
```

Adicionar imports de `CustomerRepository` e `WELCOME` ao teste.

- [ ] **Step 2: Executar o teste e confirmar falha por botão ausente**

```bash
uv run pytest tests/integration/test_ui.py::test_reset_demo_data_requires_confirmation -q
```

Esperado: falha porque os botões de confirmação ainda não existem.

- [ ] **Step 3: Implementar o fluxo de confirmação**

Em `app.py`, importar:

```python
from pathlib import Path

from banco_agil.repositories.bootstrap import reset_demo_data
```

Substituir o botão imediato “Nova conversa” por:

```python
if st.button("Nova conversa", key="request_new_conversation", icon=":material/add:"):
    st.session_state.confirm_new_conversation = True

if st.session_state.get("confirm_new_conversation", False):
    st.warning("A conversa atual será encerrada. Os dados persistidos não serão restaurados.")
    with st.container(horizontal=True):
        if st.button("Confirmar", key="confirm_new_conversation", type="primary"):
            st.session_state.pop("conversation", None)
            st.session_state.pop("messages", None)
            st.session_state.confirm_new_conversation = False
            st.rerun()
        if st.button("Cancelar", key="cancel_new_conversation"):
            st.session_state.confirm_new_conversation = False
            st.rerun()
```

Atualizar o teste existente que usa `key="new_conversation"` para clicar primeiro em
`request_new_conversation` e depois em `confirm_new_conversation`.

Adicionar à sidebar, depois desse bloco:

```python
if st.button(
    "Restaurar dados da demonstração",
    key="request_demo_reset",
    icon=":material/restart_alt:",
):
    st.session_state.confirm_demo_reset = True

if st.session_state.get("confirm_demo_reset", False):
    st.warning("Isso restaura limites, scores e solicitações dos clientes fictícios.")
    with st.container(horizontal=True):
        if st.button("Confirmar", key="confirm_demo_reset", type="primary"):
            reset_demo_data(Path(__file__).resolve().parent / "data", settings.data_dir)
            st.session_state.pop("conversation", None)
            st.session_state.pop("messages", None)
            st.session_state.confirm_demo_reset = False
            st.rerun()
        if st.button("Cancelar", key="cancel_demo_reset"):
            st.session_state.confirm_demo_reset = False
            st.rerun()
```

- [ ] **Step 4: Executar testes de UI**

```bash
uv run pytest tests/integration/test_ui.py -q
uv run ruff check app.py tests/integration/test_ui.py
uv run ruff format --check app.py tests/integration/test_ui.py
```

Esperado: todos passam.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/integration/test_ui.py
git commit -m "feat(interface): confirma reinicio e restauracao da demo"
```

### Task 4: Exibir privacidade e estado seguro da sessão

**Files:**
- Modify: `app.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: `SessionState.authenticated`, `SessionState.current_agent`.
- Produces: aviso visível de processamento pela Groq e status sem CPF ou dados financeiros.

- [ ] **Step 1: Escrever testes para aviso e status**

Adicionar a `tests/integration/test_ui.py`:

```python
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
    app.session_state["conversation"] = Conversation(flow, ScriptedProvider([]))
    app.run()
    rendered = " ".join(element.value for element in [*app.caption, *app.success])
    assert "Identidade confirmada" in rendered
    assert "00000000001" not in rendered
```

- [ ] **Step 2: Executar e confirmar falha**

```bash
uv run pytest \
  tests/integration/test_ui.py::test_privacy_notice_is_visible_before_chat \
  tests/integration/test_ui.py::test_authenticated_status_does_not_expose_cpf -q
```

Esperado: ambos falham por conteúdo ausente.

- [ ] **Step 3: Implementar textos seguros**

Em `app.py`, logo após o caption principal:

```python
st.caption(
    "Demonstração com dados fictícios. As mensagens do chat são processadas pela Groq."
)
```

Na sidebar, depois de obter `conversation`:

```python
if conversation.flow.state.authenticated:
    st.success("Identidade confirmada")
else:
    st.caption("Identidade ainda não confirmada")
```

Não exibir CPF, nascimento ou valores nesse bloco.

- [ ] **Step 4: Executar testes de UI e formatação**

```bash
uv run pytest tests/integration/test_ui.py -q
uv run ruff check app.py tests/integration/test_ui.py
uv run ruff format --check app.py tests/integration/test_ui.py
```

- [ ] **Step 5: Commit**

```bash
git add app.py tests/integration/test_ui.py
git commit -m "feat(interface): comunica privacidade e autenticacao"
```

### Task 5: Mostrar progresso da entrevista

**Files:**
- Modify: `src/banco_agil/models/state.py`
- Modify: `app.py`
- Modify: `tests/unit/test_models.py`
- Modify: `tests/integration/test_ui.py`

**Interfaces:**
- Consumes: campos de `CreditInterviewContext`.
- Produces: `CreditInterviewContext.completed_fields() -> int` e `CreditInterviewContext.total_fields() -> int`.

- [ ] **Step 1: Escrever testes do modelo**

Adicionar a `tests/unit/test_models.py`:

```python
def test_interview_progress_counts_only_confirmed_fields():
    context = CreditInterviewContext(monthly_income=1000, dependents=0)
    assert context.completed_fields() == 2
    assert context.total_fields() == 5
```

- [ ] **Step 2: Executar e confirmar falha por métodos ausentes**

```bash
uv run pytest tests/unit/test_models.py::test_interview_progress_counts_only_confirmed_fields -q
```

- [ ] **Step 3: Centralizar a lista de campos e implementar progresso**

Em `src/banco_agil/models/state.py`, adicionar `from typing import ClassVar` e alterar o contexto:

```python
class CreditInterviewContext(Model):
    FIELDS: ClassVar[tuple[str, ...]] = (
        "monthly_income",
        "employment_type",
        "fixed_expenses",
        "dependents",
        "has_active_debt",
    )

    # campos existentes permanecem iguais

    def next_missing_field(self) -> str | None:
        return next((field for field in self.FIELDS if getattr(self, field) is None), None)

    def completed_fields(self) -> int:
        return sum(getattr(self, field) is not None for field in self.FIELDS)

    @classmethod
    def total_fields(cls) -> int:
        return len(cls.FIELDS)
```

- [ ] **Step 4: Escrever teste de UI para etapa atual**

Adicionar a `tests/integration/test_ui.py`:

```python
def test_interview_progress_is_rendered(data_dir, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    flow = BankingFlow(data_dir)
    flow.state.authenticated = True
    flow.state.authenticated_customer_cpf = "00000000001"
    flow.state.current_agent = "credit_interview"
    flow.state.interview = CreditInterviewContext(monthly_income=10000)
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["conversation"] = Conversation(flow, ScriptedProvider([]))
    app.run()
    assert any("etapa 2 de 5" in item.value for item in app.caption)
    assert app.progress[0].value == 0.2
```

Adicionar o import de `CreditInterviewContext`.

- [ ] **Step 5: Implementar a apresentação do progresso**

Na sidebar de `app.py`:

```python
interview = conversation.flow.state.interview
if conversation.flow.state.current_agent == AgentType.INTERVIEW and interview is not None:
    completed = interview.completed_fields()
    total = interview.total_fields()
    current = min(completed + 1, total)
    st.caption(f"Entrevista financeira · etapa {current} de {total}")
    st.progress(completed / total)
```

- [ ] **Step 6: Executar testes**

```bash
uv run pytest tests/unit/test_models.py tests/integration/test_ui.py -q
uv run ruff check src/banco_agil/models/state.py app.py tests
uv run ruff format --check src/banco_agil/models/state.py app.py tests
```

- [ ] **Step 7: Commit**

```bash
git add src/banco_agil/models/state.py app.py tests/unit/test_models.py tests/integration/test_ui.py
git commit -m "feat(entrevista): exibe progresso sem dados sensiveis"
```

### Task 6: Explicar mudança de assunto com crédito incompleto

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `tests/flow/test_credit_exchange_flow.py`

**Interfaces:**
- Consumes: `CreditConversationContext.awaiting_requested_limit` durante `BankingFlow._exchange`.
- Produces: resposta cambial informa que a solicitação incompleta não foi enviada antes de limpar o contexto.

- [ ] **Step 1: Escrever teste do comportamento**

Adicionar a `tests/flow/test_credit_exchange_flow.py`:

```python
async def test_switching_to_exchange_explains_incomplete_credit_request(data_dir):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"EURBRL": {"bid": "6"}})
    )
    flow = BankingFlow(data_dir, ExchangeService(transport=transport))
    await authenticate(flow, "credit_limit_increase")
    assert flow.state.credit.awaiting_requested_limit

    reply = await flow.process(
        CreditTurnResult(transition_request="go_to_exchange", currency="EUR")
    )

    assert "pedido de aumento ainda não foi enviado" in reply
    assert not flow.state.credit.awaiting_requested_limit
    assert flow.state.current_agent == "triage"
```

- [ ] **Step 2: Executar e confirmar falha textual**

```bash
uv run pytest \
  tests/flow/test_credit_exchange_flow.py::test_switching_to_exchange_explains_incomplete_credit_request -q
```

- [ ] **Step 3: Implementar mensagem antes de limpar contexto**

Em `_exchange`, antes de `_complete_operation`, calcular:

```python
interrupted_credit = self.state.credit.awaiting_requested_limit
body = (
    f"**Cotação de {quote.currency}**\n\n"
    f"**1 {quote.currency} = R$ {quote.bid:.4f}**\n\n"
    f"Valor de compra em reais.{timestamp}"
)
if interrupted_credit:
    body += (
        "\n\nSeu pedido de aumento ainda não foi enviado. "
        "Quando quiser, podemos iniciar uma nova solicitação."
    )
return self._complete_operation(body)
```

- [ ] **Step 4: Executar testes de Flow**

```bash
uv run pytest tests/flow/test_credit_exchange_flow.py tests/flow/test_guards.py -q
uv run ruff check src/banco_agil/flow tests/flow
uv run ruff format --check src/banco_agil/flow tests/flow
```

- [ ] **Step 5: Commit**

```bash
git add src/banco_agil/flow/banking_flow.py tests/flow/test_credit_exchange_flow.py
git commit -m "fix(flow): esclarece troca de assunto no credito"
```

### Task 7: Fixar casos de borda do Flow e privacidade

**Files:**
- Modify: `src/banco_agil/flow/banking_flow.py`
- Modify: `tests/flow/test_authentication_flow.py`
- Modify: `tests/flow/test_interview_flow.py`
- Modify: `tests/integration/test_privacy_and_errors.py`

**Interfaces:**
- Consumes: `BankingFlow.process(TurnResult)`.
- Produces: output do tipo incompatível define `last_error_code="invalid_llm_output"`, registra falha e não altera o restante do estado.

- [ ] **Step 1: Escrever testes de autenticação incompleta e tipo incompatível**

Adicionar a `tests/flow/test_authentication_flow.py`:

```python
async def test_incomplete_authentication_does_not_consume_attempt(data_dir):
    flow = BankingFlow(data_dir)
    await flow.process(TriageTurnResult(cpf="00000000001"))
    await flow.process(TriageTurnResult())
    assert flow.state.authentication_attempts == 0
    assert flow.state.authentication.cpf == "00000000001"


async def test_incompatible_turn_result_records_controlled_error(data_dir):
    flow = BankingFlow(data_dir)
    before = flow.state.model_dump(exclude={"last_error_code"})
    response = await flow.process(CreditTurnResult(detected_intent="credit_limit_query"))
    assert response == LLMStructuredOutputError.user_message
    assert flow.state.last_error_code == "invalid_llm_output"
    assert flow.state.model_dump(exclude={"last_error_code"}) == before
```

Adicionar imports de `CreditTurnResult` e `LLMStructuredOutputError`.

- [ ] **Step 2: Escrever teste de aceite ambíguo após rejeição**

Adicionar a `tests/flow/test_interview_flow.py`:

```python
async def test_ambiguous_interview_answer_keeps_confirmation_pending(data_dir):
    flow = await rejected_flow(data_dir)
    response = await flow.process(CreditTurnResult(interview_accepted=None))
    assert flow.state.current_agent == "credit"
    assert flow.state.credit.awaiting_interview_confirmation
    assert flow.state.interview is None
    assert "sim" in response and "não" in response
```

- [ ] **Step 3: Escrever teste de log durante falha na entrevista**

Adicionar a `tests/integration/test_privacy_and_errors.py`:

```python
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
```

Adicionar imports de `CreditTurnResult`, `InterviewTurnResult` e `RepositoryError`.

- [ ] **Step 4: Executar testes e observar que somente o erro controlado falha**

```bash
uv run pytest \
  tests/flow/test_authentication_flow.py \
  tests/flow/test_interview_flow.py \
  tests/integration/test_privacy_and_errors.py -q
```

- [ ] **Step 5: Registrar output incompatível sem mutar o restante da sessão**

Alterar o início de `BankingFlow.process`:

```python
if not isinstance(result, OUTPUT_TYPES[self.state.current_agent]):
    self.state.last_error_code = LLMStructuredOutputError.code
    record(
        Event.OPERATION_FAILED,
        self.state.session_id,
        error_code=LLMStructuredOutputError.code,
    )
    return LLMStructuredOutputError.user_message
```

- [ ] **Step 6: Executar testes e qualidade**

```bash
uv run pytest tests/flow tests/integration/test_privacy_and_errors.py -q
uv run ruff check src/banco_agil/flow tests/flow tests/integration/test_privacy_and_errors.py
uv run ruff format --check src/banco_agil/flow tests/flow tests/integration/test_privacy_and_errors.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  src/banco_agil/flow/banking_flow.py \
  tests/flow/test_authentication_flow.py \
  tests/flow/test_interview_flow.py \
  tests/integration/test_privacy_and_errors.py
git commit -m "fix(flow): registra falhas estruturadas com seguranca"
```

### Task 8: Adicionar cobertura e CI reproduzível

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: comandos existentes de pytest e Ruff.
- Produces: check `CI / quality` para pushes e pull requests, com cobertura mínima de 85% sobre `src/banco_agil`.

- [ ] **Step 1: Adicionar pytest-cov e atualizar lock**

Alterar o grupo de desenvolvimento:

```toml
[dependency-groups]
dev = [
    "pytest>=8,<10",
    "pytest-asyncio>=1,<2",
    "pytest-cov>=6,<8",
    "ruff>=0.12,<1",
]
```

Executar:

```bash
uv lock
uv sync --locked
```

- [ ] **Step 2: Medir cobertura antes de fixar o gate**

```bash
uv run pytest -q --cov=src/banco_agil --cov-report=term-missing
```

Esperado: suíte verde e cobertura igual ou superior a 85%. Se o comando falhar no gate,
interromper a Task 8 e apresentar o relatório `term-missing` ao usuário; não reduzir o limite
nem usar `# pragma: no cover` em regras do projeto sem uma revisão explícita do plano.

- [ ] **Step 3: Criar workflow de CI**

Criar `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Install uv
        uses: astral-sh/setup-uv@v10
        with:
          enable-cache: true

      - name: Install Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --locked

      - name: Test with coverage
        run: >-
          uv run pytest -q
          --cov=src/banco_agil
          --cov-report=term-missing
          --cov-fail-under=85

      - name: Ruff lint
        run: uv run ruff check src tests app.py

      - name: Ruff format
        run: uv run ruff format --check src tests app.py
```

- [ ] **Step 4: Reproduzir localmente os comandos da CI**

```bash
uv sync --locked
uv run pytest -q --cov=src/banco_agil --cov-report=term-missing --cov-fail-under=85
uv run ruff check src tests app.py
uv run ruff format --check src tests app.py
```

Esperado: todos passam.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml
git commit -m "ci(projeto): automatiza testes cobertura e ruff"
```

### Task 9: Reorganizar o README conforme o desafio

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: comportamento confirmado pelas Tasks 1–8.
- Produces: README com as seis seções obrigatórias, badge de CI, roteiro reproduzível e sem contagem de testes que fique obsoleta.

- [ ] **Step 1: Adicionar badge e sumário obrigatório**

No topo, abaixo do título:

```markdown
[![CI](https://github.com/Brianrafs/Desafio-T4H/actions/workflows/ci.yml/badge.svg)](https://github.com/Brianrafs/Desafio-T4H/actions/workflows/ci.yml)

## Visão Geral
## Arquitetura do Sistema
## Funcionalidades Implementadas
## Desafios Enfrentados e Como Foram Resolvidos
## Escolhas Técnicas e Justificativas
## Tutorial de Execução e Testes
```

Os títulos devem aparecer literalmente, nessa ordem lógica, mesmo que subseções adicionais permaneçam.

- [ ] **Step 2: Reorganizar conteúdo existente sem duplicação**

Mover o conteúdo atual segundo este mapa:

| Destino | Conteúdo existente |
|---|---|
| Visão Geral | introdução, Lia, escopo e limitações do MVP |
| Arquitetura do Sistema | diagrama, Agents, Flow, Tools, Services, Repositories e sessão |
| Funcionalidades Implementadas | autenticação, crédito, entrevista, câmbio, encerramento e continuidade |
| Desafios Enfrentados e Como Foram Resolvidos | JSON da Groq, duas escritas CSV, rollback/checkpoints, privacidade e handoffs |
| Escolhas Técnicas e Justificativas | CrewAI Flow, Groq, Pydantic, Decimal, CSV, AwesomeAPI, Streamlit e testes offline |
| Tutorial de Execução e Testes | requisitos, instalação, configuração, comandos e roteiro de demo |

Remover a frase com número fixo de testes. Substituir por:

```markdown
A suíte automatizada cobre regras de domínio, transições do Flow, autorização das tools,
integrações simuladas e a interface Streamlit. O resultado atual é publicado pelo workflow CI.
```

- [ ] **Step 3: Atualizar configuração e demonstração**

Documentar exatamente:

- aviso de que mensagens do chat são processadas pela Groq;
- confirmação de “Nova conversa” e seu efeito somente sobre a sessão;
- botão “Restaurar dados da demonstração” e seu efeito sobre os três CSVs;
- indicador “Entrevista financeira · etapa X de 5”;
- Python 3.13 como requisito atual;
- uso exclusivo de dados fictícios;
- comando de cobertura da CI.

- [ ] **Step 4: Verificar links, headings e comandos**

```bash
rg -n '^## (Visão Geral|Arquitetura do Sistema|Funcionalidades Implementadas|Desafios Enfrentados e Como Foram Resolvidos|Escolhas Técnicas e Justificativas|Tutorial de Execução e Testes)$' README.md
rg -n '138 testes|113 testes' README.md
uv run pytest -q
```

Esperado:

- seis headings encontrados;
- nenhuma contagem fixa antiga;
- suíte verde.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(projeto): alinha readme aos requisitos do desafio"
```

### Task 10: Criar evidência visual e finalizar metadados

**Files:**
- Create: `docs/assets/banco-agil-home.png`
- Modify: `README.md`

**Interfaces:**
- Consumes: aplicação Streamlit validada e dados fictícios restaurados.
- Produces: screenshot sem secrets/PII real, referenciada pelo README; descrição e tópicos do repositório.

- [ ] **Step 1: Restaurar demo e iniciar a aplicação**

```bash
uv run streamlit run app.py
```

Usar a função de restauração antes da captura. Não exibir `.env`, chave, terminal ou dados reais.

- [ ] **Step 2: Capturar tela inicial em desktop**

Abrir `http://localhost:8501` em viewport aproximada de 1440×900, manter o expander de dados fictícios fechado e salvar a captura em:

```text
docs/assets/banco-agil-home.png
```

Verificar visualmente:

- título e identidade da Lia;
- aviso de dados fictícios/Groq;
- ações rápidas;
- sidebar sem dados sensíveis reais;
- ausência de cortes, sobreposições e tracebacks.

- [ ] **Step 3: Referenciar a captura no README**

Adicionar ao final da Visão Geral:

```markdown
![Tela inicial do atendimento do Banco Ágil](docs/assets/banco-agil-home.png)
```

- [ ] **Step 4: Atualizar metadados do GitHub sem mudar visibilidade ainda**

```bash
gh repo edit Brianrafs/Desafio-T4H \
  --description "Atendimento bancário multiagente com CrewAI Flow, Groq, Streamlit e regras determinísticas" \
  --add-topic crewai \
  --add-topic groq \
  --add-topic streamlit \
  --add-topic multi-agent \
  --add-topic pydantic \
  --add-topic ai-agents
```

- [ ] **Step 5: Revisar o asset e commit**

```bash
git status --short
git diff -- README.md
git add docs/assets/banco-agil-home.png README.md
git commit -m "docs(projeto): adiciona evidencia visual da interface"
```

### Task 11: Auditoria final, publicação e clone limpo

**Files:**
- No code changes expected; update `README.md` only if final verification reveals an inaccurate instruction.

**Interfaces:**
- Consumes: todos os commits anteriores.
- Produces: repositório público, CI verde e instalação confirmada a partir de clone novo.

- [ ] **Step 1: Auditar arquivos atuais e histórico por secrets**

```bash
git status --short
git ls-files | rg '(^|/)(\.env|id_rsa|credentials|secrets?)(\.|$)' || true
git grep -nEI '(gsk_[A-Za-z0-9_-]{20,}|api[_-]?key\s*[=:]\s*[^[:space:]]+)' -- . ':!uv.lock' || true
git log -p --all -- . ':!uv.lock' | rg -n '(gsk_[A-Za-z0-9_-]{20,}|api[_-]?key\s*[=:]\s*[^[:space:]]+)' || true
```

Esperado: somente nomes de variáveis, placeholders vazios ou documentação segura. Se aparecer um secret real, interromper a publicação, revogar a credencial e limpar o histórico antes de continuar.

- [ ] **Step 2: Executar verificação completa no worktree**

```bash
uv sync --locked
uv run pytest -q --cov=src/banco_agil --cov-report=term-missing --cov-fail-under=85
uv run ruff check src tests app.py
uv run ruff format --check src tests app.py
git status --short
```

Esperado: tudo verde e worktree limpo.

- [ ] **Step 3: Push da branch e confirmar CI**

```bash
git push -u origin HEAD
gh run list --workflow ci.yml --limit 1
```

Esperado: execução `completed` com conclusão `success`.

- [ ] **Step 4: Integrar a branch antes da publicação**

Invocar `superpowers:finishing-a-development-branch`, apresentar as opções de integração e
seguir a escolha do usuário. Somente continuar quando `main` contiver os commits deste plano
e o workflow de `main` estiver verde.

Confirmar:

```bash
gh api repos/Brianrafs/Desafio-T4H/branches/main --jq '.commit.sha'
gh run list --workflow ci.yml --branch main --limit 1
```

- [ ] **Step 5: Pausa de autorização antes da mudança de visibilidade**

Apresentar ao usuário:

```text
Auditoria de secrets concluída, suíte e CI verdes. O próximo comando tornará
Brianrafs/Desafio-T4H público. Confirma a mudança de visibilidade?
```

Não executar o próximo passo sem confirmação explícita.

- [ ] **Step 6: Tornar o repositório público após confirmação**

```bash
gh repo edit Brianrafs/Desafio-T4H \
  --visibility public \
  --accept-visibility-change-consequences
```

- [ ] **Step 7: Validar acesso anônimo em clone limpo**

```bash
validation_dir="$(mktemp -d)"
git clone https://github.com/Brianrafs/Desafio-T4H.git "$validation_dir/Desafio-T4H"
cd "$validation_dir/Desafio-T4H"
uv sync --locked
uv run pytest -q --cov=src/banco_agil --cov-fail-under=85
uv run ruff check src tests app.py
uv run ruff format --check src tests app.py
```

Esperado: clone sem autenticação e todas as verificações verdes.

- [ ] **Step 8: Executar smoke test manual da interface**

Validar, usando os dados fictícios:

1. M01 - consulta de limite da Ana;
2. M04 - rejeição, cinco perguntas e reanálise;
3. M05 - uma cotação cambial;
4. M09 - terceira falha de autenticação encerra;
5. M39 - restauração da demo retorna os CSVs ao estado inicial;
6. viewport desktop e mobile sem corte evidente.

- [ ] **Step 9: Registrar resultado final sem inventar números**

Se alguma instrução do README divergir do clone limpo, corrigi-la e criar:

```bash
git add README.md
git commit -m "docs(projeto): ajusta validacao final da entrega"
git push
```

Se nenhuma correção for necessária, não criar commit vazio.

## Final Acceptance Checklist

- [ ] Repositório público somente após auditoria de secrets.
- [ ] Seis seções obrigatórias explícitas no README.
- [ ] CI verde no commit final.
- [ ] Cobertura de `src/banco_agil` igual ou superior a 85%.
- [ ] Faixas de score cobrem 0 a 1000 sem lacunas.
- [ ] Reset restaura os três CSVs e preserva arquivos alheios.
- [ ] UI informa processamento pela Groq e uso de dados fictícios.
- [ ] UI mostra autenticação sem CPF e progresso sem dados financeiros.
- [ ] Troca de assunto explica o destino do pedido incompleto.
- [ ] Screenshot usa somente dados fictícios e não expõe secrets.
- [ ] Clone anônimo instala e passa pytest/Ruff.
- [ ] Golden path, falha de autenticação, câmbio e reset passam manualmente.
