# Diretrizes do projeto

- Seguir a especificação em `docs/plans/2026-09-22-banco-agil-design.md`.
- Implementar em etapas pequenas, ordenadas conforme `docs/plans/implementation.md`.
- Criar um commit atômico após cada funcionalidade concluída e validada. Incluir implementação e testes relacionados no mesmo commit.
- Usar Conventional Commits: `tipo(escopo): descrição`.
- Escrever mensagens em português, com uma ou duas frases curtas. Preferir apenas o título.
- Não acumular funcionalidades independentes no mesmo commit nem criar commits com funcionalidades incompletas.
- Usar `feat` para funcionalidades, `fix` para correções, `refactor` para reorganizações sem mudança de comportamento, `test` para testes independentes, `docs` para documentação e `chore` para configuração.
- Executar verificações pertinentes antes de cada commit e revisar o diff para evitar arquivos alheios à mudança ou segredos.
- Manter decisões financeiras, autenticação e transições independentes do LLM.
- Testes automatizados devem usar dependências externas simuladas e arquivos temporários.
