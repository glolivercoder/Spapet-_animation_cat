# DESIGN_SYSTEM — Spa pet

- Vertical: `pequena_empresa` | Perfil: `custom`
- Dials do perfil: variance=3, density=7, motion=2
- Stack: Vite + React 19 + TS + Tailwind v4 + shadcn/ui + TanStack Router/Query + RHF + Zod + Supabase HOSPEDADO (RLS em 100%)

## Diretriz do Agente de Design
🎨 **[UI Designer - Brand Design Agent]**
Que missão deliciosa de trabalhar! 🐾😻 Vou montar o design system do Spa Pet já pensando nessa interação do gato + ponteiro-bolinha, que é o coração da experiência.

## 🎨 Design System — Spa Pet

### Cores (paleta acolhedora, não-clínica-fria)
- **Fundo base:** `#ffffff` puro + superfícies `#fbf9f6` (creme quente) e `#f5f5f7`
- **Acento primário — terracota suave:** `#e08d6d` (energia, calor, pet-friendly)
- **Acento secundário — verde-sálvia:** `#7fa88a` (natureza, tranquilidade de spa)
- **Dourado champanhe:** `#c5a059` (badges de certificação, toque premium)
- **Neutros texto:** `#1f1b16` (títulos) / `#6b6459` (corpo)
- **Bolinha do ponteiro:** `#e08d6d` com fio `#1f1b16` (2px) — bem destacada e lúdica

### Tipografia
- **Títulos:** *Fraunces* (serif com personalidade, mais quente que Playfair para petshop)
- **Corpo/UI:** *Plus Jakarta Sans* — limpo, arredondado, legível
- Escala: h1 56px / h2 40px / body 17px / micro 13px (tracking leve)

### Componentes
- **Cards de serviço:** fundo `#fbf9f6`, borda 1px `rgba(0,0,0,0.06)`, radius 20px
- **Botões:** pill (radius full), primário terracota, hover escurece 8%
- **Badges:** sálvia e dourado, pill com ícone paw
- **Header:** fixo, fundo branco translúcido com blur sutil

### Micro-interações (o show da casa 🎭)
- **Gato interativo:** SVG com olhos que seguem o cursor via `getBoundingClientRect` + interpolação suave (lerp), pata que "avança" quando o ponteiro se aproxima (detecção de raio ~180px)
- **Ponteiro-bolinha:** `cursor: none` na área do hero, elemento `div` com fio (pseudo-elemento linha) seguindo o mouse com `transform: translate` + leve física de pêndulo (CSS `transition` com easing customizado)
- **Cards:** `hover: translateY(-6px)` + sombra suave
- **Fotos:** `hover scale(1.04)` com `overflow:hidden`
- **Transições:** `cubic-bezier(0.22, 1, 0.36, 1)` — 300–450ms

Quer que eu já detalhe o **SVG do gato** (camadas de olhos/pata) ou parto direto para o **layout do hero** com essa interação montada? 🐱✨

## Tokens obrigatórios
- Cores: primitivas → semânticas → componentes (sem hex solto em componente).
- Tipografia: escala modular com no máximo 2 famílias.
- Espaçamento: grid de 4/8px; densidade conforme dials.
- Acessibilidade: contraste AA, foco visível, labels e navegação por teclado.
- Estados: loading, empty, error e success explícitos em cada tela.
