"""Módulo de Mapeamento de Domínio (Odoo Pareto 20%).

Gera workspace/docs/domain-map.md com adaptação do Odoo CRM para o stack moderno
(TypeScript + Supabase RLS + React/shadcn) sem violação de LGPLv3 (código zero cópia,
apenas modelo de fluxo e domínio).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = ROOT / "workspace" / "docs"

VERTICAL_TRANSLATIONS: dict[str, dict[str, Any]] = {
    "medico": {
        "lead_term": "Paciente em Potencial",
        "opp_term": "Consulta / Procedimento Agendado",
        "contact_term": "Paciente",
        "funnel_name": "Jornada do Paciente",
        "stages": [
            ("Novo Contato", 10),
            ("Triagem / Pré-Consulta", 30),
            ("Consulta Agendada", 60),
            ("Procedimento / Tratamento", 80),
            ("Tratamento Concluído (Ganho)", 100),
            ("Desistência / Não Compareceu (Perdido)", 0),
        ],
        "roles": ["Diretor Clínico", "Médico / Especialista", "Recepcionista / Atendente"],
    },
    "dentista": {
        "lead_term": "Paciente Interessado",
        "opp_term": "Orçamento Odontológico / Plano de Tratamento",
        "contact_term": "Paciente",
        "funnel_name": "Jornada Odontológica",
        "stages": [
            ("Primeiro Contato", 10),
            ("Avaliação Clínica Agendada", 35),
            ("Orçamento em Negociação", 65),
            ("Tratamento em Execução", 85),
            ("Alta Clínica / Manutenção (Ganho)", 100),
            ("Orçamento Recusado (Perdido)", 0),
        ],
        "roles": ["Dentista Responsável", "Dentista Parceiro", "Secretária"],
    },
    "veterinario": {
        "lead_term": "Tutor Interessado",
        "opp_term": "Atendimento Pet / Plano Preventivo",
        "contact_term": "Tutor (com vínculos Pet)",
        "funnel_name": "Funil Veterinário",
        "stages": [
            ("Contato Inicial", 15),
            ("Consulta Agendada", 40),
            ("Exames / Procedimento", 70),
            ("Tratamento em Curso", 90),
            ("Paciente Recuperado / Alta (Ganho)", 100),
            ("Cancelado (Perdido)", 0),
        ],
        "roles": ["Médico Veterinário Chefe", "Veterinário Plantonista", "Atendente"],
    },
    "advogado": {
        "lead_term": "Cliente Potencial / Consulta Jurídica",
        "opp_term": "Proposta de Honorários / Ação Judicial",
        "contact_term": "Cliente / Parte",
        "funnel_name": "Esteira Jurídica",
        "stages": [
            ("Primeira Consulta", 15),
            ("Análise de Viabilidade", 35),
            ("Proposta de Honorários Enviada", 65),
            ("Contrato Assinado / Procuração", 90),
            ("Caso Vencido / Acordo (Ganho)", 100),
            ("Honorários Declinados (Perdido)", 0),
        ],
        "roles": ["Sócio Administrador", "Advogado Associado", "Assistente Jurídico"],
    },
    "pequena_empresa": {
        "lead_term": "Lead Comercial",
        "opp_term": "Oportunidade de Venda",
        "contact_term": "Cliente / Empresa",
        "funnel_name": "Funil de Vendas",
        "stages": [
            ("Prospecção / Inbound", 10),
            ("Qualificação BANT", 30),
            ("Proposta Comercial", 60),
            ("Negociação e Fechamento", 85),
            ("Venda Concluída (Ganho)", 100),
            ("Perdido para Concorrência", 0),
        ],
        "roles": ["Gerente Comercial", "Vendedor / Closer", "SDR / Pré-vendedor"],
    },
}


def generate_domain_map(profile_data: dict[str, Any]) -> str:
    vertical_data = profile_data.get("vertical") or {}
    v_id = vertical_data.get("id") or profile_data.get("vertical_id") or "pequena_empresa"
    profile_id = profile_data.get("profile_id", "crm_vertical")
    vt = VERTICAL_TRANSLATIONS.get(v_id, VERTICAL_TRANSLATIONS["pequena_empresa"])

    particularidades = vertical_data.get("particularidades", [])
    compliance_notes = vertical_data.get("compliance_notes") or profile_data.get("compliance_notes", "LGPD Art. 7.")
    odoo_refs = vertical_data.get("odoo_ref", ["contacts", "crm", "calendar", "sale"])

    stages_table = "\n".join(
        f"| {s[0]} | {s[1]}% | {'Conclusão positiva' if s[1] == 100 else ('Descarte justificado' if s[1] == 0 else 'Em progresso')} |"
        for s in vt["stages"]
    )

    parts_list = "\n".join(f"- **{p}**: Requisito essencial da vertical {v_id}." for p in particularidades) or "- Padrão comercial adaptado."

    doc = f"""# Domain Map — CRM Especializado ({v_id.upper()})
*Referência Conceitual Odoo CRM (Pareto 20%) — Arquitetura TypeScript + Supabase RLS*

> **Aviso de Propriedade Intelectual & Licença:**  
> A referência ao Odoo (LGPLv3) é estritamente conceitual e arquitetural.  
> Todo o código, schemas Supabase, migrations e componentes React/shadcn são desenvolvidos do zero em TypeScript sem cópia de código-fonte.

---

## 1. Entidades e Campos em pt-BR

### 1.1 {vt['contact_term']} / {vt['lead_term']} (`contatos`)
- `id`: UUID (Primary Key)
- `tenant_id`: UUID (Identificador da organização/clínica)
- `nome_completo`: VARCHAR(255) — Obrigatório
- `documento_fiscal`: VARCHAR(32) — CPF ou CNPJ (higienizado)
- `email`: VARCHAR(255)
- `telefone_whatsapp`: VARCHAR(32)
- `tags`: TEXT[] (ex.: `["VIP", "Retorno"]`)
- `metadados`: JSONB (campos específicos da vertical)
- `created_at`, `updated_at`: TIMESTAMPTZ

### 1.2 {vt['opp_term']} (`oportunidades`)
- `id`: UUID (Primary Key)
- `tenant_id`: UUID
- `contato_id`: UUID (FK `contatos.id`)
- `titulo`: VARCHAR(255) (ex.: "Tratamento Canal + Coroa")
- `valor_estimado`: DECIMAL(12, 2)
- `estagio`: VARCHAR(64) — Etapa da {vt['funnel_name']}
- `probabilidade`: INT (0 a 100)
- `data_prevista_fechamento`: DATE
- `motivo_perda`: VARCHAR(128) (preenchido se perdido)
- `responsavel_id`: UUID (FK `usuarios.id`)
- `created_at`, `updated_at`: TIMESTAMPTZ

### 1.3 Atividade Agendada (`atividades`)
- `id`: UUID
- `tenant_id`: UUID
- `oportunidade_id`: UUID (FK `oportunidades.id`, nullable)
- `contato_id`: UUID (FK `contatos.id`)
- `tipo`: VARCHAR(32) (`reuniao`, `consulta`, `ligacao`, `email`, `whatsapp`, `tarefa`)
- `titulo`: VARCHAR(255)
- `data_vencimento`: TIMESTAMPTZ
- `concluida`: BOOLEAN DEFAULT FALSE
- `notas`: TEXT

---

## 2. Máquina de Estados — {vt['funnel_name']}

| Estágio | Probabilidade | Comportamento |
| :--- | :--- | :--- |
{stages_table}

### Regras de Transição:
1. Um registro só transita para **Perdido** mediante preenchimento obrigatório do campo `motivo_perda`.
2. A transição para estágios avançados aciona verificação de campos obrigatórios (ex.: proposta de tratamento ou valor).
3. A mudança de estágio dispara webhooks assíncronos no n8n para comunicação (ex.: lembrete de consulta ou mensagem WhatsApp).

---

## 3. Matriz de Permissões por Papel (Supabase RLS)

| Papel | Leitura (`SELECT`) | Criação (`INSERT`) | Edição (`UPDATE`) | Exclusão (`DELETE`) |
| :--- | :--- | :--- | :--- | :--- |
| **{vt['roles'][0]}** (Gestor) | Todos os registros da tenant | Todos os registros | Todos os registros | Permitido com auditoria |
| **{vt['roles'][1]}** (Profissional) | Registros sob sua responsabilidade ou da equipe | Próprios registros | Próprios registros | Não permitido |
| **{vt['roles'][2]}** (Atendimento) | Contatos e agenda geral | Novos contatos/atividades | Status de agendamento | Não permitido |

### Políticas Supabase RLS Exigidas:
```sql
ALTER TABLE contatos ENABLE ROW LEVEL SECURITY;
ALTER TABLE oportunidades ENABLE ROW LEVEL SECURITY;
ALTER TABLE atividades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_contatos" ON contatos
  FOR ALL USING (tenant_id = auth.jwt() ->> 'tenant_id');
```

---

## 4. Telas Classificadas (Pareto 80/20)

### Telas P0 (Essenciais - 1º Ciclo de Entrega)
- **- [x] P0 Kanban da {vt['funnel_name']}**: Visualização em colunas por estágio com drag-and-drop e totalizadores.
- **- [x] P0 Ficha Unificada do {vt['contact_term']}**: Dados cadastrais, linha do tempo de atividades e oportunidades ativas.
- **- [x] P0 Modal de Agendamento Rápido**: Criação de atividade com data, tipo e responsável.
- **- [x] P0 Modal de Registro de Perda**: Seleção do motivo e comentário para arquivamento.

### Telas P1 (2º Ciclo)
- **- [ ] P1 Agenda / Calendário**: Visão semanal e diária de compromissos com filtro por profissional.
- **- [ ] P1 Tabela com Filtros Avançados**: Listagem tabular com busca rápida, ordenação e exportação CSV.

### Telas P2 (3º Ciclo / Desejáveis)
- **- [ ] P2 Painel de Indicadores (Dashboard)**: Taxa de conversão por estágio e previsão de faturamento.
- **- [ ] P2 Configuração de Motivos de Perda**: Gestão de opções pelo administrador da clínica/escritório.

---

## 5. O que foi Cortado do Odoo (Pareto 80/20) e Por Quê

1. **Módulo de Faturamento Contábil / Fiscal Completo (account/l10n)**:
   - *Justificativa*: Alta complexidade regulatória; a maioria dos clientes emite NF via sistema legado próprio ou prefeitura. Cortado para manter o app leve.
2. **Multi-moeda e Reavaliação Cambial**:
   - *Justificativa*: Irrelevante para operações locais na vertical {v_id}.
3. **Controle de Ponto e Folha (hr_timesheet complexo)**:
   - *Justificativa*: Substituído por simples atribuição de atividades e horas na oportunidade.
4. **Vendas em Grade / Matriz de Atributos de Varejo (sale_product_matrix)**:
   - *Justificativa*: Desnecessário em serviços especializados e consultorias.

---

## 6. Particularidades do Vertical & Compliance ({v_id.upper()})

### Particularidades Técnicas:
{parts_list}

### Diretrizes de Compliance & LGPD:
> **{compliance_notes}**  
> *Status: REVISÃO JURÍDICA PENDENTE conforme diretrizes de governança.*

---

## 7. Próximo Passo: GATE de Aprovação
O usuário deve validar este Domain Map antes da criação das migrations Supabase e geração dos componentes UI.
"""
    return doc


def write_domain_map(profile_data: dict[str, Any], docs_dir: Path | str = DEFAULT_DOCS) -> Path:
    p = Path(docs_dir)
    p.mkdir(parents=True, exist_ok=True)
    out_file = p / "domain-map.md"
    content = generate_domain_map(profile_data)
    out_file.write_text(content, encoding="utf-8")
    return out_file
