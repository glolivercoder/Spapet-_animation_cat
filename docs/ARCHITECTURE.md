# ARCHITECTURE — Spa pet

- Pasta de execução: `F:/Projetos2026/Sites/Spapet2`
- Stack: Vite + React 19 + TS + Tailwind v4 + shadcn/ui + TanStack Router/Query + RHF + Zod + Supabase HOSPEDADO (RLS em 100%)
- Fonte única de progresso: `docs/PROGRESS.md`

## Estratégia do Diretor
🎯 **[Diretor - Orquestrador Geral]**
Estratégia executiva montada, chefe! 🚀 Vou orquestrar em três frentes paralelas com a fila anti-colisão do OpenCode Server (4096) garantindo que ninguém pise no trabalho do outro.

**Concio (Arquiteto)** — Define a arquitetura: Astro + Tailwind (Preset 1 validado), estrutura de componentes isolando o `CatScene` (canvas/SVG com rastreamento de ponteiro), `YarnBall` (bolinha pendurada no fio via CSS/SVG + física leve), e API stub para agendamento de banho/tosa. Contrato de eventos entre camadas (mouse → olhos → pata) documentado antes de qualquer código.

**Designer (UI/UX)** — Constrói a identidade "Spa Pet" (paleta acolhedora, tipografia amigável), o layout cinematográfico da landing (hero com o gato interativo, seções de serviços, depoimentos, CTA de agendamento) e especifica microinterações: olhos que seguem o cursor com easing natural, pata que arremete quando a bolinha se aproxima, fio com leve oscilação pendular.

**Jorjão (Revisão)** — Valida performance (60fps no rastreamento), acessibilidade (fallback estático para `prefers-reduced-motion` e mobile sem hover), consistência da copy e checklist anti-bajulação: escopo enxuto, proposta de valor clara, sem features que o negócio ainda não validou (nota 65/100 exige foco).

Despachando agora para o OpenCode implementar a base:

[ACTION:DISPATCH_OPENCODE: Projeto "Spa Pet" — Landing page interativa em Astro + Tailwind CSS (Preset 1). ESTRUTURA: (1) Componente `CatScene` em canvas ou SVG inline, com gato estilizado que rastreia o ponteiro do mouse via easing suave nos olhos (pupilas deslocam proporcionalmente à posição do cursor, limitadas à órbita ocular); (2) Componente `YarnBall` — o cursor é substituído por uma bolinha de lã pendurada num fio (SVG path com leve oscilação pendular simulando gravidade), seguindo o mouse com pequeno atraso (lerp); (3) Interação "pata": quando a bolinha entra num raio de proximidade do gato, dispara animação de arremetida da pata (CSS transform + keyframes) e a bolinha escapa com pequeno bounce. SEÇÕES: hero com a cena interativa e nome "Spa Pet", serviços (banho, tosa, spa, táxi dog), diferenciais, depoimentos, CTA de agendamento, footer. RESPONSIVO: em mobile/touch, bolinha segue o toque e olhos rastreiam; fallback estático com `prefers-reduced-motion`. PERFORMANCE: requestAnimationFrame, 60fps, sem dependências pesadas. ACESSIBILIDADE: aria-labels, contraste AA, navegação por teclado no CTA. Não incluir backend real — apenas stub de formulário de agendamento (frontend-only, com validação). Entregar código limpo, componentizado e pronto para build Astro.]

## Estrutura técnica do Arquiteto
⚡ **[Concio Arquiteto - Infra & Banco]**
E aí, chefe! 😄 Vamos dar vida a esse gato perseguidor! Aqui vai a arquitetura técnica completa:

## 🐱 Arquitetura Técnica — Spa Pet

**Frontend (Next.js 14 + App Router)**
- `app/page.tsx` — landing com hero animado
- `components/CatScene.tsx` — canvas SVG/WebGL com o gato
- `components/YarnCursor.tsx` — bolinha + fio seguindo o mouse (substitui o cursor nativo via `cursor: none`)
- `hooks/useCatTracking.ts` — rastreia `mousemove`, calcula ângulo olho→ponteiro e IK da pata
- **Animação**: Framer Motion + React Spring para spring physics (olhos, pata, fio). Fio desenhado com `SVG path` usando catmull-rom + `requestAnimationFrame` para suavidade.

## 🗄️ Schemas (PostgreSQL + Prisma)

```prisma
model Pet { id, nome, especie, raca, tutorId, fotoUrl, createdAt }
model Tutor { id, nome, email, telefone, pets Pet[] }
model Servico { id, nome, duracaoMin, preco, descricao }
model Agendamento { id, petId, servicoId, dataHora, status, observacoes }
model Depoimento { id, tutorNome, texto, nota, aprovado, createdAt }
```

## 🔌 APIs (REST via Route Handlers)

- `GET/POST /api/pets` — CRUD pets
- `GET/POST /api/agendamentos` — agenda do petshop
- `GET /api/servicos` — catálogo (banho, tosa, spa)
- `GET /api/depoimentos` — depoimentos aprovados
- `POST /api/contato` — formulário + webhook WhatsApp

**Performance**: canvas com `will-change: transform`, throttling do `mousemove` a 60fps, fallback estático para `prefers-reduced-motion`. Quer que eu já detalhe o cálculo de IK da pata ou o schema do fio da bolinha primeiro? 🧶✨

## Regras de arquitetura
- Módulos com fronteiras explícitas; sem acoplamento circular.
- Contratos tipados entre frontend e backend; erros padronizados.
- Um módulo em execução por vez; atualizar PROGRESS.md ao concluir.
- Nenhuma decisão destrutiva sem aprovação; migrações versionadas.

## Skills de arquitetura
- `.opencode/skills/structured-project-execution/SKILL.md`
- `.opencode/skills/context-engineering/SKILL.md`
- `.opencode/skills/multi-agent-orchestration/SKILL.md`
