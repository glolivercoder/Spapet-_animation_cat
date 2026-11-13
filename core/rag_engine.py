"""Módulo 2/5 — RAG local Zero Docker (SQLite FTS5; LanceDB opcional)."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "workspace" / "rag.db"
N8N_TEMPLATES_DIR = Path(r"F:\Projetos2026\N8N Templates 2026")
OPENCODE_SKILLS_DIR = ROOT / ".opencode" / "skills"
OPENCODE_FALLBACK_DIR = ROOT / "workspace" / "skills" / "opencode-skills" / "skills"

_FTS_READY: dict[str, bool] = {}

N8N_ARCHITECT_RULES = {
    "title": "n8n Architecture: Schemas, Expressions & Node Standards",
    "tags": "n8n architect regras boas_praticas expressoes schemas typeversion",
    "content": """# n8n Architecture Standards & Heuristics (n8n-architect)

### 1. Regras de Schemas & Parâmetros dos Nós
- Nunca invente parâmetros ou propriedades inexistentes na especificação oficial do nó.
- Verifique a versão exata do pacote do nó (`typeVersion`). Ex: `n8n-nodes-base.httpRequest` utiliza `typeVersion: 4.2`; `n8n-nodes-base.errorTrigger` utiliza `typeVersion: 1`.
- Em nós de integração externa (Google Sheets, Gmail, Slack, Telegram, APIs REST), respeite os formatos exigidos de credencial e autenticação.

### 2. Expressões Seguras com Coalescência Nula
- No n8n, dados nulos ou indefinidos de webhooks e APIs quebram fluxos se acessados diretamente.
- OBRIGATÓRIO utilizar optional chaining e nullish coalescing:
  * Correto: `{{ $json?.campo ?? 'valor_padrao' }}`
  * Array: `{{ $json.items?.[0]?.id ?? null }}`
  * Data/Hora: `{{ $json?.timestamp ? DateTime.fromISO($json.timestamp).toFormat('dd/MM/yyyy') : $now.toISO() }}`

### 3. Roteamento de Conexões e Tratamento de Erros
- Conexão `main[0]`: saída padrão de sucesso.
- Conexão `main[1]`: saída exclusiva de erro quando `onError: "continueErrorOutput"` estiver ativado.
- Rota de Fallback: conecte a saída `main[1]` a nós de notificação (Slack/Telegram) ou IA de diagnóstico para não interromper a esteira silenciosamente.

### 4. Boas Práticas em Nós de Código (JavaScript / Python)
- Retorne sempre um array de objetos compatíveis com a estrutura n8n:
  `return items.map(item => ({ json: { ...item.json, processado: true } }));`
- Ou na sintaxe moderna:
  `return $input.all().map(item => ({ json: { ...item.json, status: 'ok' } }));`
"""
}

N8N_RESILIENCE_PATTERNS = {
    "title": "n8n SRE Standard: Retry on Fail, Error Output & Self-Healing",
    "tags": "n8n sre resiliencia retry onError self_heal fallback sentinela",
    "content": """# n8n Resilience, Error Output & Self-Healing Standard

### 1. Configuração Obrigatória em Nós Críticos de I/O Externo
Todo nó que realiza chamadas para serviços externos (HTTP Request, Banco de Dados, LLMs, Webhooks de terceiros) DEVE ter as seguintes propriedades configuradas no nível raiz do nó:
```json
{
  "retryOnFail": true,
  "maxTries": 3,
  "waitBetweenTries": 2000,
  "onError": "continueErrorOutput"
}
```

### 2. Roteamento no Objeto `connections`
Quando `onError` é definido como `continueErrorOutput`, o nó passa a ter duas saídas no n8n:
- `main[0]`: Prossegue com o fluxo feliz se a execução for bem-sucedida.
- `main[1]`: Encaminha os dados do erro (`$json.error.message`, `$json.error.stack`) para um nó de fallback, fila de retry ou alerta ao time.

### 3. Workflow Sentinela Global (`settings.errorWorkflow`)
Todo workflow em ambiente produtivo deve vincular o ID do Workflow Sentinela Global em suas configurações:
```json
{
  "settings": {
    "executionOrder": "v1",
    "errorWorkflow": "<ID_DO_WORKFLOW_SENTINELA_GLOBAL>"
  }
}
```

### 4. Protocolo SRE de Auto-Cura (Self-Healing)
Quando uma falha é detectada pelo Error Trigger, o agente executor deve classificar o erro:
- **Caso A (Erro de Expressão / Schema / Mapeamento JSON):**
  Ajustar a expressão JavaScript com coalescência nula (`?.`, `??`) ou corrigir o parâmetro do nó via `update_workflow`.
- **Caso B (Timeout / Rate Limit 429 / 502 / 503 temporário):**
  Preservar a lógica e aplicar retry com backoff: `retryOnFail: true`, `maxTries: 5`, `waitBetweenTries: 5000`.
- **Caso C (Credencial Expirada / 401 Unauthorized):**
  Gerar relatório com o nome da credencial que precisa ser renovada manualmente no painel pelo operador humano.
"""
}

N8N_GLOBAL_SENTINEL_TEMPLATE = {
    "title": "n8n Workflow Sentinela Global: Error Trigger & Self-Healing Webhook",
    "tags": "n8n sentinela errorTrigger self_heal webhook slack alerta template",
    "content": """# Workflow Sentinela Global: Alerta de Quebra & Auto-Cura IA

Este workflow monitora todos os workflows da instância vinculados em `settings.errorWorkflow`. Ao ocorrer uma falha, dispara simultaneamente o alerta no Slack/Webhook e aciona o endpoint `/api/self-heal` da aplicação Python para diagnóstico autônomo.

### JSON Estruturado do Workflow Sentinela:
```json
{
  "name": "[SENTINELA GLOBAL] Alerta de Quebra e Auto-Cura IA",
  "nodes": [
    {
      "parameters": {},
      "id": "e1b2c3d4-0001-4000-8000-000000000001",
      "name": "Quando Qualquer Fluxo Quebrar",
      "type": "n8n-nodes-base.errorTrigger",
      "typeVersion": 1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://127.0.0.1:8000/api/self-heal",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "x-n8n-secret",
              "value": "devmaster-self-heal-secret"
            }
          ]
        },
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ execution: $json.execution, workflow: $json.workflow }) }}",
        "options": {
          "timeout": 10000
        }
      },
      "id": "e1b2c3d4-0002-4000-8000-000000000002",
      "name": "Acionar Agente Python Self-Heal",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [520, 220],
      "retryOnFail": true,
      "maxTries": 3,
      "waitBetweenTries": 2000,
      "onError": "continueRegularOutput"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://hooks.slack.com/services/SEU/WEBHOOK/SLACK",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ text: `🚨 *Quebra de Fluxo Detectada no n8n!*\\n• *Workflow:* ${$json.workflow.name} (ID: ${$json.workflow.id})\\n• *Nó com Falha:* ${$json.execution.lastNodeExecuted}\\n• *Erro:* ${$json.execution.error.message}\\n• *Link da Execução:* ${$json.execution.url}\\n🤖 _O Agente Especialista Python foi acionado via MCP para diagnosticar e corrigir automaticamente._` }) }}"
      },
      "id": "e1b2c3d4-0003-4000-8000-000000000003",
      "name": "Aviso Imediato de Quebra (Slack/Webhook)",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [520, 400],
      "retryOnFail": true,
      "maxTries": 3,
      "waitBetweenTries": 2000,
      "onError": "continueRegularOutput"
    }
  ],
  "connections": {
    "Quando Qualquer Fluxo Quebrar": {
      "main": [
        [
          {
            "node": "Acionar Agente Python Self-Heal",
            "type": "main",
            "index": 0
          },
          {
            "node": "Aviso Imediato de Quebra (Slack/Webhook)",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "settings": {
    "executionOrder": "v1"
  }
}
```
"""
}

COMPOSIO_CLI_GUIDE = {
    "title": "Composio CLI: Execution Protocol, Safe Loop & Toolkits",
    "tags": "composio cli execution loop schema dry_run link tools actions triggers opencode",
    "content": """# Composio CLI Master Guide & Safe Execution Loop

O Composio CLI é a interface unificada de terminal para mais de 1000 ferramentas SaaS (Slack, GitHub, Gmail, Notion, Linear, Discord, Google Sheets, HubSpot, etc.) com gerenciamento seguro de autenticação.

### 1. Comandos Essenciais de Setup & Verificação
```bash
composio --version
composio login           # Autenticação via navegador (interativo)
composio whoami          # Confirma identidade e workspace ativo
composio apps            # Lista todos os aplicativos suportados
composio connections list # Lista contas ativas conectadas
```

### 2. O Ciclo Obrigatório de Execução Segura (The Execution Loop)
**Regra de Ouro:** NUNCA adivinhe um slug de ferramenta; NUNCA execute sem inspecionar o schema e garantir a conexão da conta.

1. **Descobrir o Slug Real (Never guess):**
   - Busca em linguagem natural: `composio search "send a slack message" --human`
   - Busca por toolkit: `composio search "create issue" --toolkits github`
   - Listar todas as ferramentas de um app: `composio tools list github`
   - Inspecionar ferramenta: `composio tools info GITHUB_CREATE_AN_ISSUE`

2. **Inspecionar o Schema antes de invocar:**
   - Obter parâmetros obrigatórios e tipos: `composio execute GITHUB_CREATE_AN_ISSUE --get-schema`
   - Mapeie a intenção aos campos exigidos. Se faltar dado obrigatório, solicite ao usuário — nunca invente parâmetros.

3. **Garantir a Conexão da Conta:**
   - Verificar conexão: `composio link github --list` ou `composio connections list`
   - Se desconectado: `composio link github` (fluxo interativo no browser)

4. **Dry-Run e Execução Segura:**
   - Dry-Run obrigatório para escritas/modificações:
     `composio execute GITHUB_CREATE_AN_ISSUE --dry-run -d '{"owner":"acme","repo":"api","title":"Bug"}'`
   - Execução real:
     `composio execute GITHUB_CREATE_AN_ISSUE -d '{"owner":"acme","repo":"api","title":"Bug"}'`
   - Execução via arquivo JSON para payloads extensos:
     `composio execute SLUG -d @payload.json`
   - Execução paralela:
     `composio execute -p SLUG_A -d '...' SLUG_B -d '...'`

### 3. Outros Recursos Avançados
- **Chamada Proxy Autenticada:** `composio proxy <URL> --toolkit <tk> -X POST -d '{...}'`
- **Assinatura de Triggers/Webhooks:** `composio triggers list <tk>` → `composio listen <TRIGGER_SLUG> --timeout 5m`
- **Workflows Scriptados:** `composio run --file ./workflow.ts`
- **Geração de Tipos SDK:** `composio generate ts --toolkits github gmail`
"""
}

CONCIO_OPENCODE_INTEGRATION_GUIDE = {
    "title": "Concio Studio & OpenCode: Multi-Agent Architecture & Skill Contract",
    "tags": "concio opencode integracao arquitetura multi_agent harness rag sqlite intervention",
    "content": """# Concio Studio & OpenCode Integration Architecture

Este documento define o contrato de integração e orquestração entre o Concio Studio V2 (backend FastAPI, SQLite e RAG FTS5) e o harness autônomo OpenCode com suporte a Composio CLI.

### 1. Topologia e Pontos de Contato
- **Configuração:** O arquivo `.opencode/config.json` é gerado dinamicamente por `core.llm_router.write_opencode_config()`, apontando para os modelos e roteadores ativos (OmniRoute / LiteLLM / Gemini).
- **Harness CLI:** `core.orchestrator.run_agent_cli(agent="opencode", prompt=...)` invoca `opencode run "<prompt>"`, registrando tempos, códigos de saída e consumo no SQLite (`workspace/devmaster.db`).
- **Diretório de Skills:** OpenCode carrega automaticamente habilidades a partir de `.opencode/skills/` (cada pasta contendo seu respectivo `SKILL.md` com metadados YAML `name` e `description`).

### 2. Ciclo de Handoff Multi-Agente
1. O usuário submete uma intenção no Concio Studio (via chat UI, STT ou API).
2. A mensagem é persistida na tabela `chat` e enfileirada em `interventions` no SQLite.
3. O contexto de arquitetura e skills é recuperado do RAG via `rag_engine.search()`.
4. O harness OpenCode é acionado com o contexto indexado e executa a implementação mantendo conformidade com TDD e design system.
5. Se ações externas forem requeridas (disparar issue no GitHub, e-mail no Gmail, mensagem no Slack), o agente aciona o Composio CLI de acordo com o safe loop.
"""
}

OPENCODE_SKILL_AUTHORING_GUIDE = {
    "title": "OpenCode Skills Standard: Architecture, Frontmatter & Triggers",
    "tags": "opencode skill_doc_authoring frontmatter trigger contract metadata",
    "content": """# OpenCode Skills: Padrão de Autoria e Especificação Técnica

Skills no OpenCode são pacotes modulares de procedimentos que ensinam agentes a executar tarefas repetíveis com alto padrão de qualidade.

### 1. Contrato de Arquivos
- Cada skill reside em sua própria pasta em `.opencode/skills/<nome-da-skill>/`.
- O nome da pasta e o campo `name:` no frontmatter DEVEM ser idênticos (letras minúsculas e hífens, <= 64 caracteres).
- O arquivo DEVE se chamar exatamente `SKILL.md` (sensível a maiúsculas).
- O frontmatter contém exatamente duas chaves:
  * `name`: identificador único (<= 64 caracteres).
  * `description`: resumo claro em terceira pessoa que serve de GATILHO (<= 1024 caracteres). Deve conter explicitamente: "Use when the user asks to...".

### 2. Estrutura do Corpo da Skill
```markdown
---
name: minha-skill
description: Executa tal ação. Use when the user asks to...
---
# Título da Skill
## When to use
## Procedure / The loop
## Quality bar
## Anti-patterns
```

### 3. Carregamento Progressivo
O OpenCode carrega primeiro apenas os metadados (nome e descrição). O corpo completo só é lido quando a tarefa do usuário coincide com o gatilho da descrição.
"""
}

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content, tags, content='docs', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts(rowid, title, content, tags) VALUES (new.id, new.title, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, tags) VALUES ('delete', old.id, old.title, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, tags) VALUES ('delete', old.id, old.title, old.content, old.tags);
    INSERT INTO docs_fts(rowid, title, content, tags) VALUES (new.id, new.title, new.content, new.tags);
END;
"""

TEMPLATES = (
    {
        "title": "n8n webhook receiver",
        "content": "Fluxo n8n: Webhook -> Function (validar payload) -> HTTP Request Supabase -> Respond to Webhook. Sempre validar assinatura e limitar payload.",
        "tags": "n8n webhook automacao",
    },
    {
        "title": "n8n email + WhatsApp",
        "content": "Fluxo n8n: Trigger formulário -> IF opt-in LGPD -> Email -> WhatsApp Cloud API. Registrar consentimento em data-map.",
        "tags": "n8n email whatsapp lgpd",
    },
    {
        "title": "Composio integration",
        "content": "Composio: conectar Gmail, Slack e GitHub via actions. Guardar credenciais no backend/.env. Nunca expor API key no frontend.",
        "tags": "composio integracao gmail slack github",
    },
    {
        "title": "Supabase RLS policy",
        "content": "Toda tabela Supabase exige ALTER TABLE ... ENABLE ROW LEVEL SECURITY e CREATE POLICY com auth.uid() = user_id para SELECT/INSERT/UPDATE.",
        "tags": "supabase rls seguranca lgpd",
    },
    {
        "title": "Onlook visual edit",
        "content": "Onlook Bridge: clique no preview, edite texto/cor/classe e persista no HTML/TSX. Usar seletores com id e validar caminho dentro do projeto.",
        "tags": "onlook ui frontend tailwind",
    },
)


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or RAG_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_rag(path: Path | None = None) -> bool:
    path = path or RAG_DB
    key = str(path.resolve())
    if key in _FTS_READY:
        return _FTS_READY[key]
    conn = connect(path)
    try:
        conn.executescript(CORE_SCHEMA)
        try:
            conn.executescript(FTS_SCHEMA)
            ready = True
        except sqlite3.OperationalError:
            ready = False
        conn.commit()
    finally:
        conn.close()
    _FTS_READY[key] = ready
    return ready


def _has_fts(path: Path | None = None) -> bool:
    return init_rag(path)


def index_document(title: str, content: str, tags: str = "", path: Path | None = None) -> int:
    init_rag(path)
    conn = connect(path)
    try:
        existing = conn.execute("SELECT id FROM docs WHERE title=?", (title,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE docs SET content=?, tags=? WHERE id=?", (content, tags, existing["id"])
            )
            conn.commit()
            return int(existing["id"])
        cur = conn.execute("INSERT INTO docs(title, content, tags) VALUES(?,?,?)", (title, content, tags))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def seed_templates(path: Path | None = None) -> int:
    inserted = 0
    for item in TEMPLATES:
        conn = connect(path)
        try:
            exists = conn.execute("SELECT id FROM docs WHERE title=?", (item["title"],)).fetchone()
        finally:
            conn.close()
        if not exists:
            index_document(item["title"], item["content"], item["tags"], path)
            inserted += 1
    # Ingerir e manter sincronizadas as regras de arquitetura e templates 2026
    ingest_n8n_knowledge_and_templates(path=path)
    # Ingerir e manter sincronizadas as skills do OpenCode e Composio CLI
    ingest_opencode_skills(path=path)
    # Ingerir catálogo de APIs Públicas e Governamentais auditadas
    try:
        from core import api_catalog_rag
        api_catalog_rag.ingest_api_catalog_to_rag(path=path)
    except Exception as exc:
        print(f"[RAG Ingest Warning] Erro ao ingerir catálogo de APIs: {exc}")
    return inserted


def ingest_n8n_knowledge_and_templates(templates_dir: Path | None = None, path: Path | None = None) -> dict:
    """Ingere no RAG local todas as regras de arquitetura n8n, padrões de resiliência e os 14 templates oficiais/reais."""
    init_rag(path)
    inserted_rules = 0
    inserted_templates = 0

    # 1. Ingerir regras arquiteturais e padrões de SRE / Self-Healing
    for rule in (N8N_ARCHITECT_RULES, N8N_RESILIENCE_PATTERNS, N8N_GLOBAL_SENTINEL_TEMPLATE):
        index_document(rule["title"], rule["content"], rule["tags"], path)
        inserted_rules += 1

    # 2. Ingerir templates da pasta F:\Projetos2026\N8N Templates 2026
    target_dir = templates_dir or N8N_TEMPLATES_DIR
    if target_dir.exists():
        for file_path in sorted(target_dir.glob("*.txt")):
            try:
                raw_text = file_path.read_text(encoding="utf-8", errors="ignore")

                # Caso 1: Template de Workflow JSON
                try:
                    wf_data = json.loads(raw_text)
                    raw_name = wf_data.get("name") or file_path.stem
                    clean_name = raw_name.strip("{} \t\r\n")
                    nodes = wf_data.get("nodes", [])
                    node_types = sorted(list(set(n.get("type", "") for n in nodes if n.get("type"))))
                    triggers = [n.get("name") for n in nodes if "trigger" in n.get("type", "").lower() or "webhook" in n.get("type", "").lower()]

                    # Detecção inteligente de categoria
                    lower_name = clean_name.lower()
                    if any(k in lower_name for k in ["veo", "video", "personagens", "ugc", "vídeo"]):
                        cat = "Vídeo & IA Criativa"
                        cat_tag = "video ai criacao"
                    elif any(k in lower_name for k in ["leads", "maps", "calendly"]):
                        cat = "Geração de Leads & CRM"
                        cat_tag = "leads crm vendas"
                    elif any(k in lower_name for k in ["woocommerce", "loja", "ecommerce", "telegram"]):
                        cat = "E-Commerce & Chatbot IA"
                        cat_tag = "ecommerce woocommerce telegram chatbot"
                    elif any(k in lower_name for k in ["spend", "llm", "orçamento", "avaliações", "review"]):
                        cat = "FinOps, SRE & Sentimento"
                        cat_tag = "finops sre monitoramento sentimento"
                    elif any(k in lower_name for k in ["gmail", "email", "aniversário", "milestone"]):
                        cat = "Email Marketing & Outreach"
                        cat_tag = "email marketing coldmail outreach"
                    elif any(k in lower_name for k in ["sociais", "preflight", "social"]):
                        cat = "Automação de Redes Sociais"
                        cat_tag = "redes_sociais preflight publicacao"
                    else:
                        cat = "Automação Geral n8n"
                        cat_tag = "automacao geral"

                    summary_md = (
                        f"# Template n8n: {clean_name}\n\n"
                        f"- **Categoria:** {cat}\n"
                        f"- **Arquivo Origem:** `{file_path.name}`\n"
                        f"- **Total de Nós:** {len(nodes)}\n"
                        f"- **Gatilhos (Triggers):** {', '.join(triggers) if triggers else 'Nenhum / Manual'}\n"
                        f"- **Nós & Integrações:** {', '.join(node_types[:10])}\n\n"
                        f"### Resumo Arquitetural do Fluxo:\n"
                        f"Este workflow orquestra a automação ponta a ponta para {clean_name.lower()}, integrando {len(node_types)} tipos de nós.\n\n"
                        f"### JSON Estruturado do Workflow n8n:\n"
                        f"```json\n{json.dumps(wf_data, indent=2, ensure_ascii=False)}\n```\n"
                    )

                    tags = f"n8n template {cat_tag} {file_path.stem.lower()[:30]}"
                    index_document(f"n8n Template: {clean_name}", summary_md, tags, path)
                    inserted_templates += 1

                except json.JSONDecodeError:
                    # Caso 2: Brief Estratégico ou Código / Documentação (ex: quero q crie uma aplicação para mar.txt)
                    title = "n8n Template & Strategy: TikTok Shop & Kalodata Affiliate Intelligence Hub"
                    tags = "n8n template strategy tiktok kalodata afiliados marketing scraper"
                    brief_md = (
                        f"# {title}\n\n"
                        f"- **Categoria:** Estratégia de Afiliados & Automação TikTok\n"
                        f"- **Arquivo Origem:** `{file_path.name}`\n"
                        f"- **Tamanho:** {len(raw_text)} caracteres\n\n"
                        f"### Resumo da Aplicação & Automação:\n"
                        f"{raw_text[:2500]}\n...\n"
                    )
                    index_document(title, brief_md, tags, path)
                    inserted_templates += 1

            except Exception as e:
                print(f"[RAG Ingest Warning] Erro ao ingerir {file_path.name}: {e}")

    return {
        "status": "ok",
        "rules_ingested": inserted_rules,
        "templates_ingested": inserted_templates,
        "total_docs": stats(path)["docs"]
    }


def list_n8n_templates(category: str | None = None, path: Path | None = None) -> list[dict]:
    """Lista todos os templates do n8n salvos no RAG com metadados."""
    init_rag(path)
    conn = connect(path)
    try:
        if category:
            like = f"%{category.lower()}%"
            rows = conn.execute(
                "SELECT id, title, tags, substr(content, 1, 350) AS summary FROM docs "
                "WHERE tags LIKE '%n8n%' AND tags LIKE '%template%' AND (tags LIKE ? OR title LIKE ?) "
                "ORDER BY id ASC",
                (like, like)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, tags, substr(content, 1, 350) AS summary FROM docs "
                "WHERE tags LIKE '%n8n%' AND tags LIKE '%template%' ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _terms(query: str) -> list[str]:
    return [term for term in re.findall(r"\w+", query.lower()) if len(term) > 1]


def ingest_opencode_skills(skills_dir: Path | None = None, path: Path | None = None) -> dict:
    """Ingere no RAG local todas as skills do OpenCode (.opencode/skills e repositório),
    guias mestres do Composio CLI e a arquitetura de integração Concio-OpenCode."""
    init_rag(path)
    inserted_guides = 0
    inserted_skills = 0

    # 1. Ingerir Guias Mestres
    for guide in (COMPOSIO_CLI_GUIDE, CONCIO_OPENCODE_INTEGRATION_GUIDE, OPENCODE_SKILL_AUTHORING_GUIDE):
        index_document(guide["title"], guide["content"], guide["tags"], path)
        inserted_guides += 1

    # 2. Localizar diretório de skills
    target_dirs = []
    if skills_dir and skills_dir.exists():
        target_dirs.append(skills_dir)
    else:
        if OPENCODE_SKILLS_DIR.exists():
            target_dirs.append(OPENCODE_SKILLS_DIR)
        if OPENCODE_FALLBACK_DIR.exists():
            target_dirs.append(OPENCODE_FALLBACK_DIR)

    seen_skills = set()
    for base_dir in target_dirs:
        for skill_file in sorted(base_dir.glob("*/SKILL.md")):
            skill_folder_name = skill_file.parent.name
            if skill_folder_name in seen_skills:
                continue
            seen_skills.add(skill_folder_name)

            try:
                raw_text = skill_file.read_text(encoding="utf-8", errors="ignore")

                # Extrair frontmatter se existir
                name = skill_folder_name
                description = ""
                fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_text, re.DOTALL)
                body = raw_text
                if fm_match:
                    fm_block = fm_match.group(1)
                    body = fm_match.group(2).strip()
                    for line in fm_block.splitlines():
                        if line.startswith("name:"):
                            name = line.replace("name:", "").strip().strip('"').strip("'")
                        elif line.startswith("description:"):
                            description = line.replace("description:", "").strip().strip('"').strip("'")

                doc_title = f"OpenCode Skill: {name}"
                clean_tags = f"opencode skill {name} composio {' '.join(_terms(description)[:10])}".strip()

                formatted_content = (
                    f"# OpenCode Skill: {name}\n\n"
                    f"- **Identificador:** `{name}`\n"
                    f"- **Gatilho / Descrição:** {description or 'Nenhuma descrição fornecida'}\n\n"
                    f"## Conteúdo da Skill:\n\n{body}\n"
                )

                index_document(doc_title, formatted_content, clean_tags, path)
                inserted_skills += 1
            except Exception as e:
                print(f"[RAG Ingest Warning] Erro ao ingerir skill {skill_file.name}: {e}")

    # Também indexar README do opencode-skills se existir
    readme_path = ROOT / "workspace" / "skills" / "opencode-skills" / "README.md"
    if readme_path.exists():
        try:
            rm_text = readme_path.read_text(encoding="utf-8", errors="ignore")
            index_document(
                "OpenCode Skills Repository & Catalog Overview",
                rm_text,
                "opencode skills catalog composio readme documentacao",
                path,
            )
            inserted_guides += 1
        except Exception:
            pass

    return {
        "status": "ok",
        "guides_ingested": inserted_guides,
        "skills_ingested": inserted_skills,
        "total_docs": stats(path)["docs"],
    }


def list_opencode_skills(query: str | None = None, path: Path | None = None) -> list[dict]:
    """Lista as skills do OpenCode indexadas no RAG local."""
    init_rag(path)
    conn = connect(path)
    try:
        if query:
            like = f"%{query.lower()}%"
            rows = conn.execute(
                "SELECT id, title, tags, substr(content, 1, 350) AS summary FROM docs "
                "WHERE tags LIKE '%opencode%' AND tags LIKE '%skill%' AND (tags LIKE ? OR title LIKE ?) "
                "ORDER BY title ASC",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, tags, substr(content, 1, 350) AS summary FROM docs "
                "WHERE tags LIKE '%opencode%' AND tags LIKE '%skill%' ORDER BY title ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search(query: str, limit: int = 3, path: Path | None = None) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []
    conn = connect(path)
    try:
        if _has_fts(path):
            match = " OR ".join(f'"{term}"' for term in terms)
            try:
                cur = conn.execute(
                    """SELECT d.id, d.title, d.content, d.tags,
                              snippet(docs_fts, 1, '[', ']', '...', 12) AS snippet
                       FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid
                       WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?""",
                    (match, limit),
                )
                rows = [dict(row) for row in cur.fetchall()]
                if rows:
                    return rows
            except sqlite3.OperationalError:
                pass
        like = f"%{terms[0]}%"
        cur = conn.execute(
            "SELECT id, title, content, tags, substr(content,1,220) AS snippet FROM docs "
            "WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY id DESC LIMIT ?",
            (like, like, like, limit),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def build_context(query: str, limit: int = 3, path: Path | None = None) -> str:
    rows = search(query, limit, path)
    return "\n\n".join(f"# {row['title']}\n{row['snippet']}" for row in rows)


def index_file(file_path: Path, path: Path | None = None) -> int:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return index_document(file_path.name, text, file_path.suffix.lstrip("."), path)


def index_directory(directory: Path, patterns: tuple[str, ...] = ("*.md", "*.json", "*.txt"), path: Path | None = None) -> int:
    total = 0
    for pattern in patterns:
        for file in directory.rglob(pattern):
            if any(part in {".git", "__pycache__", "node_modules", "data"} for part in file.parts):
                continue
            index_file(file, path)
            total += 1
    return total


def stats(path: Path | None = None) -> dict[str, int]:
    init_rag(path)
    conn = connect(path)
    try:
        total_docs = int(conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0])
        api_docs = int(conn.execute("SELECT COUNT(*) FROM docs WHERE tags LIKE '%api%'").fetchone()[0])
        return {
            "docs": total_docs,
            "api_docs": api_docs,
            "fts": 1 if _has_fts(path) else 0,
        }
    finally:
        conn.close()


def list_apis(category: str | None = None, status: str | None = None, path: Path | None = None) -> list[dict]:
    """Lista as especificações de APIs registradas no RAG."""
    init_rag(path)
    conn = connect(path)
    try:
        query = "SELECT id, title, tags, substr(content, 1, 350) AS summary FROM docs WHERE tags LIKE '%api%' AND tags LIKE '%rest%'"
        params: list[Any] = []
        if category:
            query += " AND tags LIKE ?"
            params.append(f"%{category.lower()}%")
        if status:
            query += " AND tags LIKE ?"
            params.append(f"%{status.lower()}%")
        query += " ORDER BY id ASC"
        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_apis_for_task(task_or_prompt: str, limit: int = 3, path: Path | None = None) -> list[dict]:
    """Atalho para resolução inteligente de APIs recomendadas para uma tarefa ou prompt."""
    from core import api_catalog_rag
    return api_catalog_rag.resolve_apis_for_task(task_or_prompt, limit=limit, path=path)
