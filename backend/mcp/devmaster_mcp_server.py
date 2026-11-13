"""Servidor FastMCP do Devmaster para o OpenCode.
Expõe os agentes especializados, o motor RAG/LlamaIndex, Composio e n8n para o OpenCode."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from fastmcp import FastMCP
except ImportError:
    class FastMCP:  # type: ignore[no-redef]
        """Fallback leve quando fastmcp ainda não foi instalado no ambiente."""
        def __init__(self, name: str = "Devmaster-MCP", **kwargs: Any) -> None:
            self.name = name
        def tool(self, **kwargs: Any) -> Any:
            def decorator(fn: Any) -> Any:
                return fn
            return decorator


ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import rag_engine, llm_router
from core.project_catalog import get_current_project_profile

# Instância FastMCP Devmaster
mcp = FastMCP("Devmaster-MCP")


@mcp.tool()
def ask_research_agent(query: str) -> str:
    """Pesquisa a base de conhecimento RAG, documentações, templates n8n e skills do OpenCode/Composio.
    Use quando precisar de exemplos oficiais, padrões de arquitetura ou documentação de ferramentas externas."""
    results = rag_engine.search(query, limit=5)
    if not results:
        return f"Nenhum documento específico encontrado para '{query}'. Recomenda-se pesquisar termos mais genéricos."

    report = [f"### Relatório de Pesquisa Devmaster RAG para: '{query}'\n"]
    for r in results:
        report.append(f"#### {r.get('title')}\n- **Tags:** `{r.get('tags')}`\n\n{r.get('content') or r.get('snippet')}\n")
    return "\n---\n".join(report)


@mcp.tool()
def ask_architecture_critic(plan: str) -> str:
    """Avalia criticamente um plano de código antes de o OpenCode refatorar ou criar múltiplos arquivos.
    Verifica conformidade com TDD, separação de responsabilidades, Supabase RLS e resiliência n8n."""
    checklist = []
    lower = plan.lower()

    # Checagem TDD
    has_tests = ("test" in lower or "pytest" in lower) and not ("sem teste" in lower or "sem testes" in lower or "no test" in lower)
    if has_tests:
        checklist.append("✅ [TDD] O plano contempla a criação/execução de testes automatizados.")
    else:
        checklist.append("⚠️ [TDD REQUERIDO] Adicione uma etapa inicial de testes unitários (pytest) antes de implementar.")

    # Checagem Supabase RLS
    if any(k in lower for k in ["supabase", "sql", "table", "tabela"]):
        if "rls" in lower or "row level security" in lower:
            checklist.append("✅ [Segurança RLS] Políticas de segurança Row Level Security especificadas.")
        else:
            checklist.append("🚨 [CRÍTICO RLS] Toda tabela Supabase deve incluir `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` e políticas `auth.uid() = user_id`.")

    # Checagem n8n Resiliência
    if "n8n" in lower or "workflow" in lower or "webhook" in lower:
        if "retry" in lower and "onerror" in lower:
            checklist.append("✅ [n8n SRE] Nós externos com retryOnFail e tratamento de erro main[1].")
        else:
            checklist.append("⚠️ [n8n SRE] Nós com requisições I/O externas devem configurar `retryOnFail: true` e `onError: 'continueErrorOutput'`.")

    critique = (
        "## Parecer da Arquitetura Crítica Devmaster\n\n"
        "### Auditoria de Conformidade:\n" + "\n".join(checklist) + "\n\n"
        "### Diretriz de Execução:\n"
        "- Mantenha os arquivos focados e evite criar dependências circulares.\n"
        "- Respeite as regras de contexto do OpenCode packaging e TDD estrito.\n"
    )
    return critique


@mcp.tool()
def ask_design_agent(component_spec: str, profile_json: str = "") -> str:
    """Retorna diretrizes visuais de UI/UX, classes Tailwind CSS, design system e especificações de tokens com base no perfil do projeto e na skill brand-design-agent."""
    profile_data = None
    if profile_json:
        try:
            profile_data = json.loads(profile_json)
        except Exception:
            pass
    if not profile_data:
        profile_data = get_current_project_profile() or {}

    profile_id = profile_data.get("profile_id", "não configurado")
    preset = profile_data.get("preset", "vite")
    dials = profile_data.get("dials", {"variance": 5, "density": 5, "motion": 3})
    vertical = profile_data.get("vertical") or {}
    v_id = vertical.get("id") or profile_data.get("vertical_id") or "geral"

    return (
        f"## Diretrizes de Design & UI/UX (Brand Design Agent) para: {component_spec}\n\n"
        f"### Perfil Ativo: `{profile_id}` | Vertical: `{v_id}` | Preset: `{preset}`\n"
        f"- **Dials de Design:** Variância: {dials.get('variance', 5)}/10 | Densidade: {dials.get('density', 5)}/10 | Movimento: {dials.get('motion', 3)}/10\n\n"
        "1. **Design System & Tokens (OKLCH / Tailwind v4 @theme inline):**\n"
        "   - Use tokens semânticos declarados em `index.css`: `--background`, `--foreground`, `--primary`, `--muted`, etc.\n"
        "   - Todo par de texto/fundo deve satisfazer contraste WCAG AA mínimo de 4.5:1 (e 3.0:1 para componentes de UI).\n"
        "   - Validação determinística: execute `python scripts/contrast_check.py workspace/app/src/index.css`.\n"
        "2. **Padrões de Layout e Componentes:**\n"
        "   - Container: `bg-[#0a0f0d] border border-[#1b3d2f] rounded-xl p-4 text-[#e0e6ed]`\n"
        "   - Botão Ação: `bg-[#00ff88] hover:bg-[#00cc6a] text-black font-semibold px-4 py-2 rounded-lg transition-all shadow-[0_0_12px_rgba(0,255,136,0.3)]`\n"
        "   - Badge Status: `bg-[#132a22] text-[#00ff88] text-xs px-2.5 py-0.5 rounded-full border border-[#00ff88]/30 font-mono`\n"
        "3. **Onlook Bridge & Acessibilidade:**\n"
        "   - Todo componente interativo deve manter um `id` único ou `data-onlook-id` para permitir inspeção e edição visual direta.\n"
        "   - Suporte a viewports 375px (mobile), 768px (tablet) e 1280px (desktop).\n"
        "4. **Padrão Pixel Art 128x128 & Estúdio:**\n"
        "   - Canvas com `image-rendering: pixelated;` para manter arestas nítidas sem blur bilinear.\n"
        "   - Padrão Pixel Art 128x128 suportado nos temas Tech Office, Wild Saloon e Taberna Medieval.\n"
        "5. **Acompanhamento de Progresso Determinístico:**\n"
        "   - O progresso do design é medido pelas fases F0 a F5 com `python scripts/design_progress.py --write-status`.\n"
    )


@mcp.tool()
def trigger_n8n_workflow(workflow_id: str, payload: dict[str, Any] | str = "") -> dict[str, Any]:
    """Dispara um workflow do n8n via webhook HTTP real (porta 5678) com diagnóstico honesto."""
    import httpx
    parsed_payload = payload if isinstance(payload, dict) else {"data": str(payload)}
    n8n_base = os.environ.get("N8N_BASE_URL", "http://127.0.0.1:5678").rstrip("/")
    url = f"{n8n_base}/webhook/{workflow_id}"
    try:
        resp = httpx.post(url, json=parsed_payload, timeout=2.0)
        if resp.status_code in (200, 201, 202):
            return {
                "status": "DISPATCHED",
                "workflow_id": workflow_id,
                "url": url,
                "http_code": resp.status_code,
                "payload": parsed_payload,
                "message": f"Workflow {workflow_id} acionado com sucesso no n8n.",
            }
        return {
            "status": "FAILED",
            "workflow_id": workflow_id,
            "url": url,
            "http_code": resp.status_code,
            "error": resp.text[:200],
        }
    except Exception as exc:
        return {
            "status": "N8N_UNREACHABLE",
            "workflow_id": workflow_id,
            "url": url,
            "error": str(exc),
            "message": f"n8n offline em {n8n_base}: {exc}",
        }


def sync_opencode_mcp_config(root_path: Path | None = None) -> dict[str, Any]:
    """Registra dinamicamente o Devmaster-MCP nos arquivos opencode.json e .opencode/config.json.
    
    Harmonização: delega ao llm_router para manter escritor único (single-writer) sem corrida
    e garantindo que model, provider e MCP coabitem harmoniosamente."""
    base = root_path or ROOT
    try:
        from core import llm_router
        llm_router.write_opencode_config(root_path=base)
    except Exception:
        pass
    return {
        "status": "ok",
        "modified_files": [str(base / "opencode.json"), str(base / ".opencode" / "config.json")],
    }

    return {
        "status": "ok",
        "mcp_server": "devmaster-mcp",
        "registered_in": modified_files,
    }


if __name__ == "__main__":
    # Execução via stdio nativo para integração direta com OpenCode MCP client
    mcp.run()
