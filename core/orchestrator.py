"""Módulo 4/5 — Orquestrador determinístico: docs -> prompt -> harness -> teste -> auto-fix."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from core import database, llm_router, port_mcp_manager, security_lgpd

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "workspace" / "docs"
SKILLS = ROOT / "skills"
STATUS_PATH = DOCS / "STATUS.md"
PLAN_PATH = DOCS / "PLAN.md"

DEFAULT_MODULES = (
    {
        "num": 1,
        "pct": 20,
        "name": "Infraestrutura nativa: portas, MCPs e SQLite",
        "test": "python -m pytest tests/test_module1.py -q",
    },
    {
        "num": 2,
        "pct": 40,
        "name": "OmniRoute/LiteLLM, .env e RAG local",
        "test": "python -m pytest tests/test_module2.py -q",
    },
    {
        "num": 3,
        "pct": 60,
        "name": "Segurança determinística, LGPD e Concio Market",
        "test": "python -m pytest tests/test_module3.py -q",
    },
    {
        "num": 4,
        "pct": 80,
        "name": "Orquestrador, OpenCode/Claude e Onlook Bridge",
        "test": "python -m pytest tests/test_module4.py -q",
    },
    {
        "num": 5,
        "pct": 100,
        "name": "FastAPI e GUI completa",
        "test": "python -m pytest tests/test_module5.py -q",
    },
)


def bar(pct: int) -> str:
    filled = max(0, min(10, round(pct / 10)))
    return "[" + "#" * filled + "." * (10 - filled) + f"] {pct}%"


def _read(path: Path, limit: int = 3000) -> str:
    return path.read_text(encoding="utf-8")[:limit] if path.exists() else ""


def read_state(docs_dir: Path | None = None) -> str:
    docs = docs_dir or DOCS
    parts = []
    for name in ("brief.md", "market.md", "data-map.md", "PLAN.md", "DECISIONS.md"):
        text = _read(docs / name)
        if text:
            parts.append(f"## {name}\n{text}")
    return "\n\n".join(parts)


def build_prompt(
    module_name: str,
    agent: str = "opencode",
    extra: str = "",
    docs_dir: Path | None = None,
    db_path: Path | None = None,
    rag_context: str = "",
) -> str:
    skill = _read(SKILLS / "ponytail-core.md", 1500)
    lessons = database.top_lessons(module_name, 3, db_path)
    lesson_text = "\n".join(f"- {item['error']} -> {item['solution']}" for item in lessons) or "- nenhuma"
    state = read_state(docs_dir)
    sections = [
        "# PAPEL",
        "Você é o executor do Concio Studio V2. Siga Ponytail: menor código, zero abstração inútil.",
        skill,
        "# MÓDULO",
        module_name,
        "# ESTADO (arquivos, sem histórico bruto)",
        state or "(docs vazios)",
        "# LIÇÕES APRENDIDAS",
        lesson_text,
    ]
    if rag_context:
        sections += ["# CONTEXTO RAG LOCAL", rag_context]
    else:
        # Tenta resolver APIs públicas/governamentais recomendadas para o módulo
        try:
            from core import api_catalog_rag
            matched_apis = api_catalog_rag.resolve_apis_for_task(f"{module_name} {extra}")
            if matched_apis:
                api_ctx_lines = [f"- {a['name']} ({a['id']}): {a['base_url']} (Status: {a.get('status')})" for a in matched_apis]
                sections += ["# APIS PÚBLICAS & GOVERNAMENTAIS RECOMENDADAS (RAG)", "\n".join(api_ctx_lines)]
        except Exception:
            pass
    if extra:
        sections += ["# INTERVENÇÕES DO USUÁRIO (consumir sem interromper)", extra]
    sections += [
        "# ENTREGA",
        "Implemente apenas o módulo. Rode os testes. Se falhar, corrija. Atualize STATUS.md.",
    ]
    return "\n\n".join(section for section in sections if section.strip())


def resolve_apis_for_module(module_name: str, task_desc: str = "") -> list[dict]:
    """Resolve APIs públicas e governamentais adequadas para o módulo ou tarefa atual."""
    from core import api_catalog_rag
    return api_catalog_rag.resolve_apis_for_task(f"{module_name} {task_desc}")


def _read_pct(path: Path) -> int:
    if not path.exists():
        return 0
    match = re.search(r"(\d{1,3})%", path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else 0


def write_status(pct: int, module_name: str = "", note: str = "", path: Path | None = None) -> Path:
    path = path or STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    pct = max(_read_pct(path), pct)
    lines = [
        "# STATUS — Concio Studio V2",
        "",
        f"Progresso: {bar(pct)}",
        f"Módulo: {module_name or '- '}",
        "Exit code: 0",
        "",
    ]
    if note:
        lines += ["## Observação", note, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def update_plan(module_index: int, checked: bool = True, path: Path | None = None) -> Path:
    path = path or PLAN_PATH
    if not path.exists():
        return path
    text = path.read_text(encoding="utf-8")
    mark = "x" if checked else " "
    text = text.replace(f"- [ ] {module_index}/5", f"- [{mark}] {module_index}/5")
    path.write_text(text, encoding="utf-8")
    return path


def consume_interventions(max_items: int = 3, db_path: Path | None = None) -> list[dict]:
    consumed: list[dict] = []
    for _ in range(max_items):
        item = database.next_intervention(db_path)
        if not item:
            break
        consumed.append(item)
    return consumed


def run_harness(
    agent: str,
    prompt: str,
    module: str = "",
    cwd: Path | None = None,
    timeout: int = 300,
    db_path: Path | None = None,
) -> dict:
    harness = "claude" if agent.lower().startswith("claude") else "opencode"
    args = ["claude", "-p", prompt] if harness == "claude" else ["opencode", "run", prompt]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        result = {
            "harness": harness,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-6000:],
            "stderr": (proc.stderr or "")[-4000:],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001 — CLI ausente não derruba o orquestrador
        result = {
            "harness": harness,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    database.add_harness_prompt(
        harness,
        prompt,
        module,
        response=result["stdout"] or result["stderr"],
        exit_code=result["exit_code"],
        duration_ms=result["duration_ms"],
        path=db_path,
    )
    return result


def run_test(command: str, cwd: Path | None = None, timeout: int = 300) -> dict:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-6000:],
            "stderr": (proc.stderr or "")[-4000:],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "command": command,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _module(module_index: int) -> dict:
    if 1 <= module_index <= len(DEFAULT_MODULES):
        return DEFAULT_MODULES[module_index - 1]
    raise ValueError("módulo inválido")


def run_autofix(
    module_index: int,
    agent: str = "opencode",
    max_attempts: int = 3,
    dry_run: bool = False,
    docs_dir: Path | None = None,
    db_path: Path | None = None,
    test_cmd: str | None = None,
) -> dict:
    module = _module(module_index)
    docs = docs_dir or DOCS
    attempts: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        consumed = consume_interventions(db_path=db_path)
        extra = "\n".join(f"- {item['task']}" for item in consumed)
        prompt = build_prompt(module["name"], agent, extra, docs, db_path)
        if dry_run:
            harness = {"harness": agent, "exit_code": 0, "stdout": "dry-run", "stderr": "", "duration_ms": 0}
        else:
            harness = run_harness(agent, prompt, module["name"], db_path=db_path)
        for item in consumed:
            database.finish_intervention(item["id"], "done", db_path)
        if harness["exit_code"] != 0:
            error = llm_router.summarize_log(harness["stderr"] or harness["stdout"] or "harness falhou")
            attempts.append({"attempt": attempt, "harness": harness, "test": None})
            database.add_lesson(module["name"], error, "Corrigir falha do harness ou instalar o CLI.", db_path)
            continue
        test = run_test(test_cmd or module["test"])
        attempts.append({"attempt": attempt, "harness": harness, "test": test})
        if test["exit_code"] == 0:
            write_status(
                module["pct"],
                module["name"],
                f"Auto-fix OK na tentativa {attempt}. MCPs: {', '.join(port_mcp_manager.select_mcps(module['name']))}",
                docs / "STATUS.md",
            )
            update_plan(module_index, True, docs / "PLAN.md")
            return {
                "success": True,
                "module": module,
                "attempts": attempts,
                "progress": bar(module["pct"]),
            }
        error = llm_router.summarize_log(test["stderr"] or test["stdout"])
        database.add_lesson(module["name"], error, "Corrigir erro indicado e repetir o teste.", db_path)
    write_status(
        module["pct"],
        module["name"],
        f"Falha no auto-fix após {max_attempts} tentativas.",
        docs / "STATUS.md",
    )
    return {
        "success": False,
        "module": module,
        "attempts": attempts,
        "progress": bar(module["pct"]),
    }


def run_module(module_index: int, agent: str = "opencode", dry_run: bool = False, **kwargs: Any) -> dict:
    return run_autofix(module_index, agent=agent, dry_run=dry_run, **kwargs)


def run_all(agent: str = "opencode", dry_run: bool = True, docs_dir: Path | None = None, db_path: Path | None = None) -> list[dict]:
    results = []
    for index in range(1, len(DEFAULT_MODULES) + 1):
        results.append(run_autofix(index, agent=agent, dry_run=dry_run, docs_dir=docs_dir, db_path=db_path))
    return results


def security_gate(root: Path | None = None, docs_dir: Path | None = None) -> dict:
    base = root or ROOT
    findings = security_lgpd.scan_secrets(base)
    migrations: list[dict] = []
    for directory in (base / "supabase" / "migrations", base / "workspace" / "migrations"):
        if directory.exists():
            migrations.extend(security_lgpd.validate_migrations_dir(directory))
    return {"secrets": findings, "migrations": migrations, "env_ignored": security_lgpd.env_ignored()}


def record_decision(title: str, decision: str, reason: str, docs_dir: Path | None = None) -> Path:
    docs = docs_dir or DOCS
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "DECISIONS.md"
    current = path.read_text(encoding="utf-8") if path.exists() else "# DECISIONS\n\n"
    current += f"## {title}\n- Decisão: {decision}\n- Motivo: {reason}\n\n"
    path.write_text(current, encoding="utf-8")
    return path
