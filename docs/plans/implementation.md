# Plano de implementação — Banco Ágil

A especificação de referência é `2026-09-22-banco-agil-design.md`. Cada etapa abaixo representa uma unidade de entrega com validação própria. Funcionalidades independentes dentro de uma etapa devem receber commits separados assim que estiverem concluídas.

| Ordem | Entrega | Validação antes do commit | Mensagem sugerida |
|---|---|---|---|
| 1 | Estrutura Python, dependências, configuração de ambiente, pytest e Ruff | Instalação e execução das ferramentas; segredos ignorados | `chore(projeto): configura a base da aplicação` |
| 2 | Modelos Pydantic de domínio, estado, comandos, outputs e erros | Tipos, valores monetários, limites e contextos independentes | `feat(dominio): adiciona contratos e estado da sessão` |
| 3 | Repositories CSV e dados fictícios de demonstração | Leitura, atualização, faixas, arquivo malformado e escrita atômica | `feat(persistencia): implementa repositories CSV` |
| 4 | Autenticação por CPF e nascimento | Normalização, sucesso e credenciais incorretas | `feat(autenticacao): valida as credenciais do cliente` |
| 5 | Consulta de limite | Cliente existente e erros de repository | `feat(credito): permite consultar o limite atual` |
| 6 | Solicitação e avaliação de aumento | Pendente, aprovação, rejeição, fronteiras da faixa e atualização do limite | `feat(credito): avalia pedidos de aumento de limite` |
| 7 | Cálculo e persistência de score | Pesos, despesas zero, dependentes, dívida e limites de 0 a 1000 | `feat(entrevista): calcula e persiste o score financeiro` |
| 8 | Integração AwesomeAPI | HTTP simulado: sucesso, timeout, 404, 5xx e único retry | `feat(cambio): consulta cotações em reais` |
| 9 | Tools finas com autorização por sessão e agente | Acesso não autenticado, escopo e impossibilidade de escolher CPF protegido | `feat(tools): protege operações por sessão e escopo` |
| 10 | Flow com autenticação, intenção pendente e encerramento | Terceira falha, encerramento em estados ativos e bloqueio após fim | `feat(flow): controla autenticação e ciclo da sessão` |
| 11 | Flow de crédito e câmbio | Guardas, consulta, aumento e mudança de assunto autenticada | `feat(flow): orquestra crédito e câmbio` |
| 12 | Entrevista e reanálise automática | Rejeição e aceite prévios, coleta apenas do campo esperado, score persistido e nova solicitação | `feat(flow): conduz entrevista e reanálise de crédito` |
| 13 | Integração Groq e quatro agentes especializados | Outputs simulados, escopo de tools, um retry e preservação do estado em falhas | `feat(agentes): integra especialistas com a Groq` |
| 14 | Logs estruturados e tratamento integrado de falhas | Eventos sem dados pessoais; erros seguros e contexto preservado | `feat(observabilidade): registra eventos seguros da sessão` |
| 15 | Interface conversacional Streamlit | Inicialização, histórico, sessão entre reruns e fluxos pela UI | `feat(interface): adiciona atendimento pelo Streamlit` |
| 16 | Verificação integrada dos critérios de aceite | Golden path com CSVs temporários e integrações simuladas; suíte e Ruff | `test(integracao): valida os fluxos completos de atendimento` |
| 17 | README, arquitetura e roteiro de demonstração | Setup em ambiente limpo e instruções reproduzíveis | `docs(projeto): documenta instalação e demonstração` |

## Regras de execução

1. Inicializar o repositório Git antes da implementação e versionar o planejamento em um commit de documentação.
2. Conferir as APIs das versões instaladas antes de integrar CrewAI, Groq e Streamlit.
3. Implementar cada entrega com seus testes pertinentes; a etapa de integração não substitui testes por funcionalidade.
4. Executar os testes pertinentes e Ruff, revisar o diff e criar o commit imediatamente após concluir a funcionalidade.
5. Registrar correções posteriores em commits `fix`, sem reescrever o histórico por padrão.
6. Validar os critérios AC01–AC18 e a Definition of Done da especificação antes de considerar o MVP concluído.

## Pontos a verificar na implementação

- A substituição atômica de um CSV não torna alterações em dois arquivos transacionais. Testar falhas entre a atualização da solicitação e do cliente e definir recuperação consistente.
- As tools devem validar autorização e fase da conversa mesmo quando chamadas diretamente; o prompt não é uma barreira de segurança.
- Falhas de interpretação não devem executar operações financeiras nem perder autenticação ou progresso da entrevista.
- A validação automatizada deve funcionar sem internet; a demonstração real exige configuração da Groq e disponibilidade da AwesomeAPI.

## Estado da implementação

As etapas 1–16 foram implementadas e registradas em commits separados por funcionalidade. A documentação da etapa 17 está em `README.md`.

- 138 testes automatizados passaram após os ajustes da Lia, incluindo os fluxos pela interface com AppTest.
- Ruff passou para `src`, `tests` e `app.py`.
- A integração dos agentes foi exercitada com CrewAI real e respostas HTTP simuladas.
- A instalação em um segundo ambiente virtual limpo passou com `uv sync --locked --offline`, usando o cache local; os 113 testes e o Ruff também passaram nesse ambiente.
- Uma consulta manual real de USD à AwesomeAPI retornou cotação e horário.
- A demonstração manual com Groq real foi executada com autorização do usuário, dados financeiros fictícios e autenticação exclusivamente local, sem enviar CPF ou nascimento à API. Foram validados entrevista, reanálise, câmbio e continuidade.
- O histórico inclui correções para preservar etapas concluídas após falhas e a conexão das tools CrewAI executáveis ao Flow.

## Ajustes solicitados nos testes da aplicação

- Separar o contrato JSON da Groq das instruções ReAct do CrewAI; tratar `json_validate_failed` como falha estruturada com uma única repetição.
- Retornar à triagem após operações concluídas, preservando a identidade autenticada. Esta transição interna amplia a matriz da especificação original conforme o pedido de continuidade do usuário.
- Usar a última resposta como contexto mínimo para mensagens curtas, sem reenviar credenciais anteriores.
- Apresentar a assistente como **Lia**, com acolhimento contextual, Markdown, opções visíveis e atalhos de serviços.
- Manter os resultados financeiros determinísticos e distinguir limite de uso da API de falha na interpretação.
