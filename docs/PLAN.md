# PLAN — Spa pet

**Missão:** gerar o site de um petshop como uma animação onde o gato persegue com os olhos o ponteiro do mouse e fica tentando pegar ele com a pata ( o ponteiro do mouse na tela vira uma bolinha pendurada no fio . o nome do petshop é  Spa Pet /;

| Módulo | Entrega | % acumulado | Teste de conclusão |
| ------ | ------- | ----------- | ------------------ |
| M1 | Fundação, contratos e tipos | 10% | build/lint sem erros; contratos e tipos validados |
| M2 | Cadastro, perfis e regras de acesso | 25% | fluxo de login/registro coberto por teste; rotas protegidas retornam 401 |
| M3 | Domínio principal e CRUD | 45% | CRUD completo com validação; testes de unidade do domínio |
| M4 | Integrações (APIs do RAG e .env) | 65% | integrações com fallback honesto; testes de contrato HTTP |
| M5 | UI/UX e design system | 85% | telas P0 responsivas; build de produção sem warnings |
| M6 | Testes, segurança e hardening | 100% | suíte completa verde; checklist LGPD/OWASP revisado |

## Checklist de execução
- [ ] M1 — Fundação, contratos e tipos (10%)
- [ ] M2 — Cadastro, perfis e regras de acesso (25%)
- [ ] M3 — Domínio principal e CRUD (45%)
- [ ] M4 — Integrações (APIs do RAG e .env) (65%)
- [ ] M5 — UI/UX e design system (85%)
- [ ] M6 — Testes, segurança e hardening (100%)

## Regra de avanço
Um módulo só é marcado como concluído quando o teste correspondente passa.
Falha repetida duas vezes no mesmo teste exige `[ACTION:REPORT_BLOCKER:<motivo>]`.
