# Banco Ágil

Atendimento bancário conversacional com quatro especialistas CrewAI, estado explícito e regras financeiras determinísticas. A interface Streamlit reúne autenticação, crédito, entrevista financeira e câmbio em uma conversa contínua.

## Requisitos e instalação

- Python 3.13.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Uma chave da Groq para conversar em linguagem natural.

Na raiz do projeto:

```powershell
uv sync --locked
Copy-Item .env.example .env
```

No Linux/macOS, substitua a segunda linha por `cp .env.example .env`.

Preencha `GROQ_API_KEY` no `.env` e execute:

```powershell
uv run streamlit run app.py
```

Acesse o endereço local exibido pelo Streamlit, normalmente `http://localhost:8501`. Sem chave, a interface abre com instruções de configuração e o chat desabilitado. Nunca coloque a chave no código, no chat ou no Git.

## Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `GROQ_API_KEY` | vazio | Credencial necessária para interpretação da conversa |
| `GROQ_MODEL` | `groq/llama-3.3-70b-versatile` | Modelo Groq, configurável conforme disponibilidade da conta |
| `AWESOME_API_KEY` | vazio | Chave opcional, enviada no header `x-api-key` |
| `DATA_DIR` | `runtime/data` | Diretório dos CSVs de trabalho |

`OTEL_SDK_DISABLED=true`, `CREWAI_TELEMETRY_ENABLED=false` e `CREWAI_TRACING_ENABLED=false` são aplicados antes de carregar CrewAI para impedir tracing e telemetria com dados da conversa. Os exemplos de ambiente refletem essa política; ela não é uma opção de ativação de tracing neste MVP.

Na primeira execução, os repositories copiam os dados fictícios de `data/` para `DATA_DIR`. Alterações de limite e score ficam na cópia de trabalho, ignorada pelo Git. “Nova conversa” reinicia somente a sessão; não restaura limites ou scores. Para repetir uma demonstração com dados iniciais, escolha outro diretório vazio em `DATA_DIR` e reinicie o aplicativo.

## Demonstrações

| Cliente fictício | CPF | Nascimento | Limite inicial | Score inicial |
|---|---|---|---|---|
| Ana | `00000000001` | `15/01/1990` | R$ 1.000,00 | 400 |
| Bruno | `00000000002` | `20/05/1985` | R$ 3.000,00 | 850 |

Os CPFs são identificadores sintéticos de teste. O MVP normaliza pontuação e compara CPF e nascimento com o CSV; não implementa autenticação bancária real.

### Aprovação direta

1. Envie “Quero aumentar meu limite para R$ 5.000”.
2. Informe o CPF e o nascimento de Bruno quando solicitados.
3. O pedido é aprovado e o novo limite é persistido.

### Rejeição, entrevista e reanálise

Com Ana e dados iniciais:

1. Consulte o limite e forneça CPF e nascimento.
2. Solicite um limite total de R$ 4.000.
3. Após a rejeição, aceite a entrevista explicitamente.
4. Responda, uma informação por turno: renda `10000`; emprego `CLT`; despesas `1000`; dependentes `0`; dívida ativa `não`.
5. O score passa a 800 e uma nova análise aprova o limite de R$ 4.000. O pedido rejeitado permanece no histórico.

### Câmbio e encerramento

- Após autenticar, pergunte “Quanto está o dólar?”, “E o euro?” ou “E a libra?”.
- A aplicação consulta o `bid` da AwesomeAPI, informa o valor em BRL e o horário UTC quando disponível.
- Uma cotação não encerra a sessão. É possível voltar a consultar crédito.
- “Encerrar”, “sair”, “fim” e o botão **Encerrar atendimento** funcionam mesmo se a Groq estiver indisponível. Outras formulações são interpretadas pelo agente.
- Três combinações incorretas de CPF e nascimento encerram a sessão. Dados ainda incompletos não contam como uma tentativa de autenticação.

## Arquitetura

```mermaid
flowchart TD
    UI[Streamlit e histórico da conversa] --> C[Conversation]
    C --> A[Quatro Agents CrewAI e Groq]
    A --> O[Output Pydantic validado]
    O --> F[CrewAI BankingFlow e SessionState]
    F --> G[Guardas de transição]
    F --> T[Tools CrewAI autorizadas por escopo e fase]
    T --> S[Services determinísticos]
    S --> R[Repositories CSV]
    S --> API[AwesomeAPI]
```

- **Agents:** triagem, crédito, entrevista e câmbio têm responsabilidades, schemas e conjuntos de tools próprios. Não recebem o CPF autenticado no contexto do prompt nem tabelas de decisão financeira.
- **GroqProvider:** usa `BaseLLM` do CrewAI com HTTP via `httpx`, temperatura 0,2 e JSON validado localmente. Há no máximo duas chamadas por turno: uma inicial e uma repetição por output inválido. HTTP 429 não é repetido.
- **Tools:** as mesmas tools tipadas são vinculadas aos agentes e ao Flow. Na fase de interpretação, executar uma tool é recusado. Após validar o turno, o Flow libera a chamada; a tool delega ao service e verifica novamente sessão, agente e etapa. O modelo não pode fornecer CPF a operações de crédito.
- **Flow:** preserva intenção antes da autenticação, controla a matriz de transições, aceita somente o campo aguardado na entrevista e reanalisa automaticamente o valor anterior. Não depende de frases exatas do LLM. Respostas operacionais usam resultados determinísticos para exibir valores e decisões.
- **Services:** comparam credenciais, avaliam crédito, calculam score e consultam câmbio. Valores monetários usam `Decimal`.
- **Repositories:** validam os CSVs e escrevem arquivos temporários no mesmo diretório, com `flush`, `fsync` e `os.replace`.
- **Sessão:** autenticação e progresso ficam no `SessionState`; o histórico exibido fica em `st.session_state.messages`. Nenhum dos dois substitui a persistência do domínio.

### Crédito e recuperação de falhas

Um aumento só é aprovado se o valor solicitado superar o limite atual e respeitar o teto da faixa de score. A solicitação nasce `pendente`. Para uma aprovação, o limite do cliente é gravado antes da conclusão do status; somente após ambas as escritas há uma resposta de aprovação.

Como dois CSVs não formam uma transação, pedidos pendentes são reconciliados antes de novas operações de crédito ou alterações de score. Se o cliente ainda tem o limite original, a avaliação é retomada; se já tem o limite solicitado, a aprovação é finalizada. Uma repetição imediata do mesmo pedido recuperado não cria outra linha. Um limite incompatível com ambos bloqueia a operação com erro controlado. Esse mecanismo pressupõe um único escritor e não oferece segurança para sessões concorrentes.

A entrevista persiste o score antes de retornar ao crédito. Se a reanálise falhar, os dados já confirmados e a etapa concluída são mantidos para permitir retomada.

### Câmbio e privacidade

O serviço aceita USD, EUR e GBP, com timeout de 5 segundos por tentativa. Timeouts, falhas de conexão e HTTP 5xx têm uma única repetição. HTTP 404 e demais 4xx não são repetidos. Payload inválido resulta em indisponibilidade controlada.

Logs JSON registram eventos e `session_id`, sem CPF, nascimento, renda, despesas, dívida, prompts ou segredos. O console detalhado do CrewAI e a coleta de métricas do Streamlit estão desabilitados. Mensagens digitadas são enviadas à Groq para interpretação e permanecem no histórico da sessão da UI; use somente os dados fictícios nesta demonstração.

## Estrutura

```text
app.py                     Interface Streamlit
data/                      CSVs fictícios versionados
docs/plans/                Especificação e plano
src/banco_agil/
  agents/                  Persona e fábrica dos quatro especialistas
  flow/                    Orquestração, guardas e transições
  models/                  Domínio, estado, outputs e erros
  providers/               Integração Groq
  repositories/            Acesso exclusivo a CSVs e inicialização
  services/                Regras determinísticas
  tools/                   Fachada e adapters CrewAI
  bootstrap.py             Composição da aplicação
  conversation.py          Ponte entre interpretação e Flow
  observability.py         Eventos estruturados
tests/                     Unitários, Flow, tools, integrações e UI
```

## Testes e qualidade

```powershell
uv run pytest -q
uv run ruff check src tests app.py
uv run ruff format --check src tests app.py
```

Os testes não precisam de chaves ou internet. Usam CSVs temporários, `httpx.MockTransport`, agentes CrewAI reais em testes de integração e Streamlit `AppTest` para interagir com o chat. Cobrem aprovação, rejeição, entrevista, matriz de guardas, escopos, falhas de escrita, tentativas de injetar campos protegidos e preservação de estado.

Os avisos de depreciação emitidos internamente pelo CrewAI 1.15.22 são mantidos visíveis. As versões resolvidas estão em `uv.lock`.

Validação em 22/09/2026: 113 testes passaram, Ruff e formatação passaram, e a instalação foi repetida em um ambiente virtual novo com `uv sync --locked --offline` usando o cache local. Uma consulta manual real de USD à AwesomeAPI retornou cotação positiva e horário; essa consulta não faz parte da suíte automatizada.

## Limitações e validação externa

- MVP demonstrável com CSVs; não usar como sistema bancário de produção.
- Escritas concorrentes entre sessões não são suportadas.
- O teste automatizado da UI usa integrações simuladas. A demonstração da conversa com a Groq real ainda precisa ser executada com uma credencial válida; não havia `GROQ_API_KEY` configurada durante a implementação.
- Não há banco transacional, painel administrativo, tracing distribuído ou autenticação de produção.

## Desenvolvimento

Seguir [AGENTS.md](AGENTS.md) e o [plano de implementação](docs/plans/implementation.md). Cada funcionalidade concluída e validada recebe um commit atômico em Conventional Commits, com uma ou duas frases curtas em português. Testes relacionados acompanham a implementação.

## Referências

- [Especificação aprovada](docs/plans/2026-09-22-banco-agil-design.md)
- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows)
- [CrewAI BaseLLM](https://docs.crewai.com/en/learn/custom-llm)
- [Groq API](https://console.groq.com/docs/api-reference)
- [AwesomeAPI — moedas](https://docs.awesomeapi.com.br/api-de-moedas)
- [AwesomeAPI — chave de API](https://docs.awesomeapi.com.br/instrucoes-api-key)
- [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing)
