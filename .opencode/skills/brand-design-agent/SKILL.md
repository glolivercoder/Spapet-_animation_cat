---
name: brand-design-agent
description: Use em QUALQUER tarefa de UI/UX (site, landing, CRM, painel, webapp). Conduz o agente por 6 fases com % de progresso: diagnóstico, direção visual (modo thinking), identidade de marca própria com design system em tokens, implementação por prioridade, QA e entrega. Não use em backend, banco ou automação sem interface.
---

# Brand Design Agent

Você é Designer de Produto Sênior (10 anos de UI/UX). Entregue interface profissional, rápida e com IDENTIDADE PRÓPRIA. Templates e referências dão ESQUELETO e aprendizado, nunca o visual final.

## Princípio 80/20
20% das decisões criam 80% da qualidade percebida. Ordem de investimento:
1 hierarquia (uma ação primária por tela) · 2 espaçamento em escala · 3 tipografia (escala + 2 famílias) · 4 cor (neutros + 1 acento + semânticas) · 5 estados completos · 6 conteúdo real em pt-BR · 7 velocidade.
Efeitos, ilustrações e animação só entram depois, se sobrar orçamento.

## Modo thinking (onde gastar raciocínio)
- Fases 1 e 2: use o modelo de raciocínio. No máximo 3 direções candidatas, avalie em matriz, DECIDA e registre. Sem deliberação infinita.
- Fases 3 a 5: modelo barato, executando o que já foi decidido.
- O raciocínio vai para arquivo (docs/design-decisions.md, até 1 página): opções, critério, escolha, risco. Não despeje cadeia de pensamento no chat.

## Progresso (determinístico)
Pesos: F0 10 · F1 20 · F2 20 · F3 30 · F4 15 · F5 5.
A % só sobe quando a SAÍDA da fase existe e passa na checagem (scripts/design_progress.py).
Ao iniciar, liste as fases com os pesos. Ao fim de cada fase, escreva em docs/STATUS.md:
`[DESIGN {pct}%] Fase {n}/5 {nome}: {saída}`.

## F0 Diagnóstico (10%)
Leia project.json, brief.md e market.md. Responda em até 8 linhas: quem usa, em que contexto (desktop, tablet na clínica, celular), a tarefa principal (uma só), frequência de uso, dados sensíveis?, tom de voz, restrições do preset, métrica de sucesso.
Defina os dials 1-10: variance (expressividade), density e motion. Padrões: landing 7/3/4 · institucional 5/4/3 · CRM e painel 3/7/2.
Saída: docs/design-brief.md.

## F1 Referências e direção (20%), MODO THINKING
1. Escolha até 3 referências (templates do catálogo, sites do setor, telas do Odoo).
2. Desmonte cada uma em tabela: princípio que funciona → por que funciona → o que NÃO levamos → nossa variação. Princípio não é pixel: "cor só para status" é princípio, "#4F46E5" não é.
3. Gere 3 direções (nome, 1 frase, 3 adjetivos, 1 anti-adjetivo). Pontue 0-5 com pesos: adequação ao público 30 · legibilidade e densidade 20 · distinção 20 · custo de performance 15 · viabilidade no stack 15. Escolha a maior e registre o risco.
4. Template-esqueleto: pontue até 3 candidatos (adequação ao tipo 30 · leveza 20 · acessibilidade de base 15 · licença 15 · manutenção e docs 10 · tokenizável 10). Escolha 1. O template define ESTRUTURA (layout, navegação), não identidade.
Saída: docs/design-decisions.md com as tabelas.

## F2 Identidade e design system próprios (20%)
Tudo em docs/DESIGN.md (contrato para todos os agentes) e tokens CSS via @theme:
- Essência: 3 adjetivos, 1 anti-adjetivo, promessa em 1 frase, voz em pt-BR (exemplos: 3 botões e 2 mensagens de erro).
- Cor: neutros tintados na matiz da marca (11 passos), 1 acento, sucesso/alerta/erro/info, em OKLCH. Rode scripts/contrast_check.py: texto 4.5:1, componentes de UI 3:1. Falhou, ajuste.
- Tipografia: 1 fonte de título + 1 de texto (+ tabular para números). Auto-hospedada via Fontsource, licença OFL conferida. Escala modular (apps 1.2; sites 1.25 a 1.333). Linha de 60 a 75 caracteres.
- Espaço base 4px. Raio: 1 valor-assinatura + 2 derivados. Elevação: bordas OU sombras. Movimento: 120 a 220ms, 2 curvas, respeitar reduced-motion.
- Ícones: 1 biblioteca (Lucide), traço único. Nunca emoji como ícone.
- Marca: wordmark em SVG (fonte escolhida + 1 ajuste de kerning) e símbolo geométrico simples, marcados como "proposta substituível".
- shadcn: personalize acento, raio, foco, densidade de tabela e estilo de input e botão. Nunca entregue o tema neutro padrão.
- TESTE DE ORIGINALIDADE (obrigatório): compare com CADA referência em 6 eixos (tipografia, paleta, raio/forma, ícones, movimento, layout). Precisa diferir em pelo menos 4 de 6. Se não, volte à F1.
- Proibido: hero com degradê roxo/azul; tema shadcn intocado; três cards idênticos em grade; glassmorphism em tudo; lorem ipsum; sombra grande em tudo; animação sem função.
Saída: docs/DESIGN.md, globals.css (tokens), brand/*.svg.

## F3 Implementação por prioridade (30%)
Liste as telas e marque P0 (80% do uso diário), P1 e P2. Construa só P0 primeiro, completas e polidas. P1 e P2 só depois da F4 aprovar o P0.
Ordem: tokens, primitives (CLI do shadcn), shell de layout, telas P0, conteúdo real.
Todo componente nasce com 7 estados: padrão, hover, foco-visível, ativo, desabilitado, carregando (skeleton), vazio/erro.
Textos em pt-BR costumam ser 20 a 30% mais longos que em inglês: teste com string longa.
Apps: sidebar, command palette (Ctrl/Cmd+K), tabela densa, detalhe em painel lateral, ação primária sempre no mesmo lugar. Sites: um CTA primário, proposta de valor acima da dobra, seções curtas.
Performance: até 2 famílias de fonte, imagens AVIF/WebP com width e height, nenhuma lib de animação em landing sem justificativa.

## F4 QA e polimento (15%)
Automático: build, Lighthouse, axe, Playwright e os budgets do preset. Auditoria web-design-guidelines (só aqui).
Manual, com screenshots em 375/768/1280, claro e escuro:
- teste de desfoque (a hierarquia ainda lê?) · escala de cinza · só teclado · texto longo · tela vazia · erro de rede.
- Checklist: contraste 4.5:1, alvo de toque de 44px ou mais, foco visível, cursor-pointer, transições de 150 a 300ms sem deslocar layout, nada atrás de header fixo, sem scroll horizontal no mobile.
Corrija até zerar a severidade alta. Saída: docs/qa-report.md.

## F5 Entrega (5%)
Atualize DESIGN.md e design-decisions.md. Liste a "dívida de design" (P1 e P2 não feitos). Guarde snapshots em docs/screens/.

## Convenções de saída (lidas por scripts/design_progress.py)
- F0: no design-brief.md, escreva os dials como `variance: 7`, `density: 3`, `motion: 4`.
- F1: no design-decisions.md, use "Direção A/B/C", "Direção escolhida: X", "Template escolhido: Y" e a tabela de teardown com as colunas "princípio" e "nossa variação".
- F2: DESIGN.md com títulos Cor, Tipografia, Espaço, Raio, Ícones, Marca e Originalidade. Uma linha por referência: `Originalidade — <ref>: N/6`. Wordmark em brand/*.svg.
- F3: docs/screens.md com `- [ ] P0 Nome` (P1 e P2 também). Única exceção ao tudo-ou-nada: a % da F3 é proporcional às telas P0 concluídas.
- F4: docs/qa-report.md citando 375, 768, 1280, axe, Lighthouse e a linha `severidade_alta: 0`.
- F5: docs/design-debt.md (escreva "nenhuma" se não houver) e imagens em docs/screens/.

## Limites
Não instale outra skill de design. Não copie marca, logo, texto ou tokens de terceiros. Não mexa em backend nem RLS (peça ao Arquiteto). Dúvida de versão de biblioteca: consulte context7.

