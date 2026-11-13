# SECURITY_LGPD — Spa pet

## Diretriz do Arquiteto
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

## LGPD
- Base legal e finalidade documentadas por tabela; minimização de dados pessoais.

## Regras preventivas obrigatórias
- RLS/authorization em toda tabela e rota; negar por padrão.
- Nenhum segredo em código, log ou resposta; segredos somente via `.env`.
- Validação de entrada com Zod/Pydantic em toda fronteira (API e formulário).
- Rate limiting e timeout em endpoints públicos e integrações externas.
- Headers de segurança, CORS restrito e cookies HttpOnly/SameSite.
- Logs de auditoria imutáveis para ações sensíveis; sem PII em logs.
- Dependências auditadas (`npm audit` / `pip-audit`) antes de concluir.
- Testes negativos: acesso indevido, payload inválido e vazamento de dados.
