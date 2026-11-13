# DEV_PROMPT — Spa pet

## 1. IDENTIDADE
- Projeto: **Spa pet** (`proj-spa-pet-1794335448`)
- Diretório de execução: `F:/Projetos2026/Sites/Spapet2`
- Documentação: `F:/Projetos2026/Sites/Spapet2/docs`
- Stack: Vite + React 19 + TS + Tailwind v4 + shadcn/ui + TanStack Router/Query + RHF + Zod + Supabase HOSPEDADO (RLS em 100%)
- Nota de maturação: 65/100 | Preset: Preset 1

## 2. OBJETIVO ÚNICO (escopo deste despacho)
gerar o site de um petshop como uma animação onde o gato persegue com os olhos o ponteiro do mouse e fica tentando pegar ele com a pata ( o ponteiro do mouse na tela vira uma bolinha pendurada no fio . o nome do petshop é  Spa Pet /;

## 3. DOCUMENTOS OBRIGATÓRIOS (ler antes de codar)
- `docs/PROJECT.md`
- `docs/MARKET_RESEARCH.md`
- `docs/DESIGN_SYSTEM.md`
- `docs/SECURITY_LGPD.md`
- `docs/ARCHITECTURE.md`
- `docs/PLAN.md`
- `docs/PROGRESS.md` (fonte única de progresso)

## 4. CONTRATO DE AÇÕES PREDEFINIDAS
Execute apenas estas ações, na ordem do plano:
- `[ACTION:READ_DOCS]`
- `[ACTION:IMPLEMENT_MODULE:<id>]`
- `[ACTION:TEST_MODULE:<id>]`
- `[ACTION:UPDATE_PROGRESS]`
- `[ACTION:REPORT_BLOCKER:<motivo>]`
- `[ACTION:DONE]`

Regras do contrato:
- Não solicite confirmação humana; avance até `[ACTION:DONE]`.
- Um módulo por vez: `IMPLEMENT_MODULE` → `TEST_MODULE` → `UPDATE_PROGRESS`.
- Se um teste falhar duas vezes pelo mesmo motivo, pare e emita `[ACTION:REPORT_BLOCKER:<motivo>]`.
- Este prompt é a única fonte de instrução. Não dependa de histórico de chat.

## 5. APIS DISPONÍVEIS (RAG + .env)
### Dog CEO API (`PUB-ENTERTAIN-001` / midia_demo)
- Base URL: `https://dog.ceo/api`
- Auth: `none` | CORS: True | Status: healthy
- `GET /breeds/image/random` — Retorna uma foto aleatória em alta resolução de cão. (params: nenhum)
- Snippet: `async function getDogImage() {
  const r = await fetch('https://dog.ceo/api/breeds/image/random');
  return (await r.json()).message; // url da imagem jpg
}`
### IBGE Serviços de Dados (`BR-GOV-004` / governo_estatistica)
- Base URL: `https://servicodados.ibge.gov.br/api`
- Auth: `none` | CORS: True | Status: healthy
- `GET /v1/localidades/estados` — Relação de todas as 27 Unidades Federativas do Brasil com siglas, IDs e regiões. (params: nenhum)
- `GET /v1/localidades/estados/{uf}/municipios` — Lista de todos os municípios de um determinado estado. (params: uf (ex: 35 para SP ou SP))
- `GET /v2/censos/nomes/{nome}` — Frequência e evolução histórica de prenomes masculinos e femininos no Brasil por décadas. (params: nome (ex: maria, joao))
- Snippet: `async function carregarEstados() {
  const res = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome');
  return await res.json(); // [{ id, sigla, nome, regiao }]
}`
### Portal de Dados Abertos (dados.gov.br) (`BR-GOV-001` / governo_catalogo)
- Base URL: `https://dados.gov.br/api/3/action`
- Auth: `oauth_token` | CORS: True | Status: alert_requires_auth
- Aviso: ⚠️ ALERTA DE AUTENTICAÇÃO: O endpoint do barramento CKAN do dados.gov.br retornou HTTP 401 e foi migrado para o Gov.br Gateway. Requer token de autenticação prévio.
- `GET /package_search?q={query}` — Busca textual de pacotes de dados abertos governamentais. (params: q, rows)
- Snippet: `// Requer token Gov.br após migração do portal
async function buscarDataset(query, token) {
  const r = await fetch(`https://dados.gov.br/api/3/action/package_search?q=${query}`, {
    headers: { 'Aut`
### BrasilAPI (`BR-UTIL-001` / utilidade_brasil)
- Base URL: `https://brasilapi.com.br/api`
- Auth: `none` | CORS: True | Status: healthy
- `GET /cep/v2/{cep}` — Consulta de CEP com dados de logradouro, bairro, cidade, estado e coordenadas geográficas (lat/long) via fallback múltiplo. (params: cep (8 dígitos))
- `GET /cnpj/v1/{cnpj}` — Consulta cadastral unificada de CNPJ diretamente na base da Receita Federal (razão social, CNAE, sócios, situação). (params: cnpj (14 dígitos))
- `GET /banks/v1` — Lista completa e oficial de bancos no Brasil com códigos COMPE e ISPB. (params: nenhum)
- `GET /taxas/v1` — Consulta taxas oficiais de juros e indicadores econômicos (Selic, CDI, IPCA). (params: nenhum)
- `GET /feriados/v1/{ano}` — Lista de feriados nacionais oficiais para o ano fornecido. (params: ano (ex: 2026))
- `GET /ddd/v1/{ddd}` — Retorna o estado e todas as cidades correspondentes ao código DDD. (params: ddd (ex: 11))
- Snippet: `// Autocompletar endereço por CEP via BrasilAPI
async function buscarCep(cep) {
  const res = await fetch(`https://brasilapi.com.br/api/cep/v2/${cep}`);
  if (!res.ok) throw new Error('CEP não encontr`

### Chaves presentes no `.env` (nunca hardcode valores)
- `ABACUS_API_KEY`
- `ANTHROPIC_API_KEY`
- `APIFY_API_KEY`
- `ATRIA_API_KEY`
- `BASEFY_API_KEY`
- `BRAVE_API_KEY`
- `COMPOSIO_API_KEY`
- `CONTEXT7_API_KEY`
- `CONTEXT_EXTREME_API_KEY`
- `DEEPSEEK_API_KEY`
- `ECHOTIK_API_KEY`
- `ELEVENLABS_API_KEY`
- `FINNHUB_API_KEY`
- `FMP_API_KEY`
- `FREEPIK_API_KEY`
- `GEMINI_API_KEY`
- `GITHUB_TOKEN`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `HOMEASSISTANT_TOKEN`
- `HUGGINGFACE_API_KEY`
- `LINKUP_API_KEY`
- `NINEROUTER_API_KEY`
- `NVIDIA_API_KEY`
- `OMNIROUTE_API_KEY`
- `OPENAI_API_KEY`
- `OPENCODE_OMNIROUTE_API_KEY`
- `OPENROUTER_API_KEY`
- `SUPERMEMORY_API_KEY`
- `TAVILY_API_KEY`
- `TESTSPRITE_API_KEY`
- `WAVESPEED_API_KEY`

## 6. SKILLS OBRIGATÓRIAS
- `structured-project-execution` — execução governada por PROGRESS.md/PLAN.md (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/structured-project-execution/SKILL.md`)
- `context-engineering` — contexto mínimo e curado por tarefa (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/context-engineering/SKILL.md`)
- `multi-agent-orchestration` — papéis e handoffs entre agentes (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/multi-agent-orchestration/SKILL.md`)
- `tdd-workflow` — testes antes/durante cada módulo (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/tdd-workflow/SKILL.md`)
- `market-research` — pesquisa de mercado e viabilidade (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/market-research/SKILL.md`)
- `frontend-design-systems` — design system e tokens (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/frontend-design-systems/SKILL.md`)
- `brand-design-agent` — identidade visual (`F:/Projetos2026/DevMaster_pythonV3/.opencode/skills/brand-design-agent/SKILL.md`)

## 7. MCPS ATIVOS
- `context7`
- `playwright`
- `21dev`

## 8. PLANO POR MÓDULO (% e testes)
| Módulo | Entrega | % acumulado | Teste de conclusão |
| ------ | ------- | ----------- | ------------------ |
| M1 | Fundação, contratos e tipos | 10% | build/lint sem erros; contratos e tipos validados |
| M2 | Cadastro, perfis e regras de acesso | 25% | fluxo de login/registro coberto por teste; rotas protegidas retornam 401 |
| M3 | Domínio principal e CRUD | 45% | CRUD completo com validação; testes de unidade do domínio |
| M4 | Integrações (APIs do RAG e .env) | 65% | integrações com fallback honesto; testes de contrato HTTP |
| M5 | UI/UX e design system | 85% | telas P0 responsivas; build de produção sem warnings |
| M6 | Testes, segurança e hardening | 100% | suíte completa verde; checklist LGPD/OWASP revisado |

## 9. QUALIDADE, SEGURANÇA E LGPD
- Tipagem estrita e validação de contratos em toda fronteira.
- RLS/autorização negando por padrão; segredos apenas no `.env`.
- Sem PII em logs; auditoria para ações sensíveis.
- Fallbacks honestos para APIs externas (sem mocks silenciosos).
- Atualizar `PROGRESS.md` e `PLAN.md` ao concluir cada módulo.

## 10. PROTOCOLO ANTI-LOOP E CONCLUSÃO
- Repetir o mesmo erro duas vezes no mesmo teste = bloqueio imediato.
- Nunca reescreva arquivos já estáveis sem necessidade comprovada por teste.
- Ao final, emitir `[ACTION:DONE]` com a lista de módulos concluídos e testes executados.
