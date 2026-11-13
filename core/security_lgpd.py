"""Módulo 3/5 — Segurança determinística, LGPD, RLS e Concio Market."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "workspace" / "docs"

SECRET_PATTERNS = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("api_key_sk", re.compile(r"sk-[A-Za-z0-9-]{3,}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}")),
)

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "data", ".venv", "venv", "dist", "build"}
SKIP_FILES = {".env", "rag.db", "concio.db"}

DEFAULT_ENTITIES = (
    {
        "field": "prompts do usuário",
        "purpose": "orquestrar agentes",
        "legal_basis": "execução de contrato (Art. 7, V)",
        "retention": "enquanto necessário",
        "rights": "acesso, correção, exclusão (Art. 18)",
        "tooltip": "Usamos seu pedido apenas para executar a tarefa solicitada.",
    },
    {
        "field": "logs de harness",
        "purpose": "depuração e auto-fix",
        "legal_basis": "legítimo interesse (Art. 7, IX)",
        "retention": "30 dias",
        "rights": "acesso, correção, exclusão (Art. 18)",
        "tooltip": "Logs técnicos para corrigir falhas. Expurgados em 30 dias.",
    },
    {
        "field": "chaves de API (.env)",
        "purpose": "acesso a provedores",
        "legal_basis": "execução de contrato (Art. 7, V)",
        "retention": "até revogação",
        "rights": "exclusão (Art. 18, VI)",
        "tooltip": "Chaves ficam no backend e nunca são enviadas ao navegador.",
    },
)


class SecurityError(RuntimeError):
    pass


def scan_secrets(root: Path | None = None, max_findings: int = 50) -> list[dict]:
    base = root or ROOT
    findings: list[dict] = []
    for file in base.rglob("*"):
        if len(findings) >= max_findings:
            break
        if not file.is_file() or any(part in SKIP_DIRS for part in file.parts):
            continue
        if file.name in SKIP_FILES or file.name.startswith(".env.") or file.name.startswith("concio_studio_v2_"):
            continue
        try:
            if file.stat().st_size > 1_000_000:
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(
                        {
                            "file": str(file.relative_to(base)),
                            "line": lineno,
                            "type": kind,
                            "match": match.group(0)[:10] + "...",
                        }
                    )
                    if len(findings) >= max_findings:
                        break
    return findings


def env_ignored(path: Path | None = None) -> bool:
    gitignore = path or ROOT / ".gitignore"
    if not gitignore.exists():
        return False
    return ".env" in gitignore.read_text(encoding="utf-8").splitlines()


def _normalize_table(raw: str) -> str:
    return raw.strip().strip('"').strip("`")


def check_rls(sql: str, require_policy: bool = True) -> list[dict]:
    results: list[dict] = []
    for match in re.finditer(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)", sql, re.IGNORECASE
    ):
        table = _normalize_table(match.group(1))
        missing: list[str] = []
        rls = rf"alter\s+table\s+{re.escape(table)}\s+enable\s+row\s+level\s+security"
        if not re.search(rls, sql, re.IGNORECASE):
            missing.append("rls")
        if require_policy:
            policy = rf"create\s+policy\s+\S+\s+on\s+{re.escape(table)}"
            if not re.search(policy, sql, re.IGNORECASE):
                missing.append("policy")
        if missing:
            results.append({"table": table, "missing": missing})
    return results


def validate_migration(sql: str) -> None:
    problems = check_rls(sql)
    if problems:
        detail = ", ".join(f"{item['table']} ({'+'.join(item['missing'])})" for item in problems)
        raise SecurityError("migration bloqueada: RLS/policy ausente em " + detail)


def validate_migrations_dir(directory: Path) -> list[dict]:
    report: list[dict] = []
    for file in sorted(directory.rglob("*.sql")):
        try:
            validate_migration(file.read_text(encoding="utf-8", errors="ignore"))
            report.append({"file": str(file), "ok": True, "problems": []})
        except SecurityError as exc:
            report.append({"file": str(file), "ok": False, "problems": str(exc)})
    return report


def generate_data_map(project: str, entities: list[dict] | None = None) -> str:
    entities = entities or list(DEFAULT_ENTITIES)
    lines = [
        f"# Data Map — {project}",
        "",
        "Mapeamento LGPD: Art. 7 (bases legais) e Art. 18 (direitos do titular).",
        "",
        "| Campo | Finalidade | Base Legal (Art. 7) | Retenção | Direitos (Art. 18) | Tooltip |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entity in entities:
        lines.append(
            "| {field} | {purpose} | {legal_basis} | {retention} | {rights} | {tooltip} |".format(
                field=entity.get("field", "-"),
                purpose=entity.get("purpose", "-"),
                legal_basis=entity.get("legal_basis", "-"),
                retention=entity.get("retention", "-"),
                rights=entity.get("rights", "-"),
                tooltip=entity.get("tooltip", "-").replace("|", "/"),
            )
        )
    lines += ["", "Regra: toda tabela com dado pessoal exige RLS ativo e política de acesso."]
    return "\n".join(lines) + "\n"


def write_data_map(project: str, entities: list[dict] | None = None, path: Path | None = None) -> Path:
    path = path or DOCS / "data-map.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_data_map(project, entities), encoding="utf-8")
    return path


def choose_preset(requirements: str) -> dict:
    text = requirements.lower()
    public_seo = any(word in text for word in ("landing", "blog", "portfólio", "portfolio", "conteúdo", "conteudo", "seo", "marketing"))
    private_app = any(word in text for word in ("login", "dashboard", "painel", "crm", "saas interno", "app"))
    marketplace = any(word in text for word in ("marketplace", "loja", "ecommerce", "e-commerce", "checkout", "assinatura"))
    if private_app and not public_seo:
        return {
            "preset": "Preset 3",
            "stack": "Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query + React Hook Form/Zod + Supabase",
            "reason": "app privado com login/dashboard",
        }
    if marketplace or (public_seo and private_app):
        return {
            "preset": "Preset 2",
            "stack": "Next.js (App Router) + Tailwind + shadcn/ui + Supabase",
            "reason": "SEO público + área privada",
        }
    return {
        "preset": "Preset 1",
        "stack": "Astro + Tailwind CSS",
        "reason": "conteúdo público, SEO e performance",
    }


def _sources_from_brave(query: str, key: str) -> list[dict]:
    import httpx

    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=8,
    )
    data = response.json()
    return [
        {"title": item.get("title", ""), "snippet": item.get("description", ""), "url": item.get("url", "")}
        for item in data.get("web", {}).get("results", [])
    ]


def _sources_from_serpapi(query: str, key: str) -> list[dict]:
    import httpx

    response = httpx.get("https://serpapi.com/search.json", params={"q": query, "api_key": key}, timeout=8)
    data = response.json()
    return [
        {"title": item.get("title", ""), "snippet": item.get("snippet", ""), "url": item.get("link", "")}
        for item in data.get("organic_results", [])
    ]


def _maturity_score(query: str, sources: list[dict]) -> int:
    score = 25 + min(len(sources), 5) * 8
    lowered = query.lower()
    for word, weight in (("dor", 10), ("paga", 10), ("preço", 6), ("preco", 6), ("concorrente", 6), ("assinatura", 5), ("b2b", 4)):
        if word in lowered:
            score += weight
    return max(0, min(100, score))


def concio_market(
    query: str,
    docs_dir: Path | None = None,
    env_path: Path | None = None,
    api_key: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    from core import llm_router

    env = llm_router.load_env(env_path)
    key = api_key or env.get("BRAVE_API_KEY") or env.get("SERPAPI_KEY", "")
    chosen_provider = provider or ("brave" if env.get("BRAVE_API_KEY") else "serpapi")
    sources: list[dict] = []
    if key:
        try:
            sources = (
                _sources_from_brave(query, key)
                if chosen_provider == "brave"
                else _sources_from_serpapi(query, key)
            )
        except Exception:  # noqa: BLE001 — pesquisa externa é opcional
            sources = []

    score = _maturity_score(query, sources)
    preset = choose_preset(query)

    llm_analysis = ""
    is_llm_powered = False
    if sources:
        try:
            sources_summary = "\n".join(
                f"- Concorrente/Fonte: {s.get('title')} ({s.get('url')})\n  Snippet: {s.get('snippet', '')[:160]}"
                for s in sources[:6]
            )
            analyst_prompt = (
                f"Você é um analista sênior de mercado e viabilidade de startups. Analise criticamente, sem bajulação e com rigor a proposta: '{query}'.\n"
                f"Fontes reais de concorrentes identificadas:\n{sources_summary}\n\n"
                f"Apresente em 3 a 5 parágrafos curtos:\n"
                f"1. Concorrentes diretos e o que eles já oferecem.\n"
                f"2. Barreira de entrada e modelo de monetização.\n"
                f"3. Crítica objetiva sobre diferenciação e viabilidade comercial."
            )
            agent_reply, _ = llm_router.generate_agent_response(
                agent_name="Analista de Mercado",
                role="Analista de Viabilidade & Inteligência Competitiva",
                agent_id="analista_mercado",
                prompt=analyst_prompt,
                env_path=env_path,
            )
            if agent_reply and not agent_reply.startswith("[AVISO:"):
                llm_analysis = agent_reply.strip()
                is_llm_powered = True
        except Exception:
            llm_analysis = ""

    critique = [
        f"# Concio Market — {query}",
        "",
        f"## Nota de maturação (heurística): {score}/100",
        "",
    ]

    if is_llm_powered and llm_analysis:
        critique += [
            "## Crítica de Mercado com LLM (sem bajulação)",
            llm_analysis,
            "",
            f"- Fontes externas analisadas em tempo real: {len(sources)}.",
            "",
        ]
    else:
        critique += [
            "## Auto-avaliação Offline (sem bajulação)",
            "- Sem prova de dor paga comprovada por clientes, o projeto permanece uma aposta e não um negócio validado.",
            "- O entusiasmo técnico ou funcional não substitui a validação de tração financeira real.",
            "- Stack e estética não salvam proposta de valor inconsistente; simplifique o escopo inicial antes de expandir.",
            f"- Fontes externas consultadas: {len(sources)}.",
            "",
        ]

    if sources:
        critique += ["## Concorrentes / fontes"] + [
            f"- {item.get('title') or 'sem título'}: {item.get('snippet', '')[:180]}" for item in sources[:6]
        ] + [""]
    else:
        critique += ["## Fontes", "- Nenhuma fonte externa; análise offline determinística.", ""]
    critique += [
        "## Preset escolhido",
        f"- {preset['preset']}: {preset['stack']}",
        f"- Motivo: {preset['reason']}.",
        "",
    ]

    target_dir = docs_dir or DOCS
    target_dir.mkdir(parents=True, exist_ok=True)
    market_text = "\n".join(critique)
    (target_dir / "market.md").write_text(market_text, encoding="utf-8")
    (target_dir / "DECISIONS.md").write_text(
        f"# DECISIONS — {query}\n\n## Stack\n- {preset['preset']}: {preset['stack']}\n- Motivo: {preset['reason']}\n",
        encoding="utf-8",
    )
    return {
        "query": query,
        "score": score,
        "sources": sources,
        "preset": preset,
        "critique": market_text,
    }


def run_gitleaks(root: Path | None = None) -> dict:
    import shutil
    import subprocess

    binary = shutil.which("gitleaks")
    if not binary:
        return {"available": False, "findings": scan_secrets(root)}
    proc = subprocess.run(
        [binary, "detect", "--no-git", "--source", str(root or ROOT), "-f", "json", "--exit-code", "0"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"available": True, "stdout": proc.stdout[-4000:], "returncode": proc.returncode}
