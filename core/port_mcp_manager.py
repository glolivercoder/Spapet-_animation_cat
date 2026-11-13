"""Módulo 1/5 — portas nativas (psutil/socket) e trava determinística de MCPs."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES = ROOT / ".claude" / "capabilities.yml"
MCP_CONFIG = ROOT / "workspace" / "mcp.json"
CATALOG = ("context7", "playwright", "reui", "devmaster-mcp", "21dev", "figma", "browse-user")
MAX_MCPS = len(CATALOG)
ALWAYS_ACTIVE = "context7"

# Serviços essenciais protegidos contra interrupção ou encerramento
ESSENTIAL_PORTS = {8000, 4096, 20128, 3008}
ESSENTIAL_PROCESS_PATTERNS = (
    "opencode",
    "omniroute",
    "gitea",
    "uvicorn",
    "fastapi",
    "antigravity",
    "cursor",
    "vscode",
    "code.exe",
    "powershell",
    "pwsh",
    "cmd.exe",
    "conhost",
    "windowsterminal",
)

# Registro em memória de ações pendentes de autorização do usuário
PENDING_RESOURCE_ACTIONS: dict[str, dict[str, Any]] = {}


def is_essential_service(port: int | None = None, pid: int | None = None, name: str = "") -> tuple[bool, str]:
    """Verifica se o serviço, porta ou PID é essencial para a infraestrutura do DevMaster."""
    # 1. Processo pai / host do FastAPI ou ancestrais do terminal/IDE
    if pid is not None:
        if pid == os.getpid():
            return True, "Processo host do FastAPI/DevMaster (PID atual)"
        try:
            current_proc = psutil.Process()
            # Bloquear encerramento de qualquer processo ancestral (terminal, shell, IDE)
            ancestor_pids = {p.pid for p in current_proc.parents()}
            if pid in ancestor_pids:
                return True, f"Processo ancestral do terminal ou IDE (PID {pid})"
        except Exception:
            pass

    # 2. Portas essenciais conhecidas
    if port is not None and port in ESSENTIAL_PORTS:
        names_map = {
            8000: "FastAPI Web Host (:8000)",
            4096: "OpenCode Server Engine (:4096)",
            20128: "OmniRoute Gateway (:20128)",
            3008: "Gitea Local Git Service (:3008)",
        }
        return True, names_map.get(port, f"Porta essencial reservada :{port}")

    # 3. PID associado a conexões ou linhas de comando essenciais
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            pname = proc.name().lower()
            cmd_list = proc.cmdline()
            cmd = " ".join(cmd_list).lower()
            if any(pat in pname or pat in cmd for pat in ESSENTIAL_PROCESS_PATTERNS):
                return True, f"Processo protegido do sistema/IDE ({pname}, PID {pid})"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return False, ""

CATALOG_DETAILS: dict[str, dict[str, Any]] = {
    "context7": {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "available": True,
        "type": "stdio",
        "description": "Context7 - Upstash Vector / Document search MCP",
    },
    "playwright": {
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "available": True,
        "type": "stdio",
        "description": "Playwright - Browser Automation & E2E Testing MCP",
    },
    "reui": {
        "type": "remote",
        "url": "https://mcp.reui.io",
        "available": True,
        "description": "ReUI - Shadcn UI Component, Pro Block & Icon Registry",
    },
    "devmaster-mcp": {
        "type": "local",
        "command": "python",
        "args": ["-m", "backend.mcp.devmaster_mcp_server"],
        "available": True,
        "description": "DevMaster MCP - RAG, Agentes e Ferramentas Internas",
    },
    "21dev": {
        "command": None,
        "args": [],
        "available": False,
        "description": "21dev Magic Components (Comando não configurado no host)",
    },
    "figma": {
        "command": None,
        "args": [],
        "available": False,
        "description": "Figma Dev Mode API (Comando não configurado no host)",
    },
    "browse-user": {
        "command": None,
        "args": [],
        "available": False,
        "description": "Browse User Session MCP (Comando não configurado no host)",
    },
}


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    return not port_is_free(port, host)


def find_free_port(preferred: int = 3000, limit: int = 65535) -> int:
    if preferred < 1 or preferred > limit:
        raise ValueError("porta fora do intervalo")
    for port in range(preferred, limit + 1):
        if port_is_free(port):
            return port
    raise RuntimeError("nenhuma porta livre no intervalo")


def reallocate_ports(ports: list[int], limit: int = 65535) -> dict[int, int]:
    mapping: dict[int, int] = {}
    used: set[int] = set()
    for port in ports:
        if port_is_free(port) and port not in used:
            mapping[port] = port
            used.add(port)
            continue
        candidate = find_free_port(port + 1, limit)
        while candidate in used:
            candidate = find_free_port(candidate + 1, limit)
        mapping[port] = candidate
        used.add(candidate)
    return mapping


def scan_ports(start: int = 1, end: int = 65535, only_listening: bool = True) -> list[dict]:
    """Escaneia portas abertas no sistema. Por padrão filtra sockets em LISTEN para evitar TIME_WAIT efêmero."""
    rows: list[dict] = []
    seen: set[tuple[int, int | None]] = set()
    for conn in psutil.net_connections(kind="inet"):
        if not conn.laddr or not (start <= conn.laddr.port <= end):
            continue
        # Evita poluição por conexões efêmeras finalizadas (TIME_WAIT, CLOSE_WAIT)
        if only_listening and conn.status not in ("LISTEN", getattr(psutil, "CONN_LISTEN", "LISTEN")):
            continue
        key = (conn.laddr.port, conn.pid)
        if key in seen:
            continue
        seen.add(key)
        name = ""
        if conn.pid:
            try:
                name = psutil.Process(conn.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = ""
        rows.append(
            {
                "port": conn.laddr.port,
                "pid": conn.pid,
                "process": name,
                "status": conn.status,
                "address": conn.laddr.ip,
            }
        )
    return sorted(rows, key=lambda item: (item["port"], item["pid"] or 0))


def scan_dev_servers(filter_project: str | None = None) -> dict[str, Any]:
    """Escaneia servidores em LISTEN e processos de desenvolvimento (Node.js, Python, OpenCode, Vite, MCPs).
    Identifica o projeto de origem (este projeto vs outros projetos) e permite parada/reinício manual."""
    servers: list[dict[str, Any]] = []
    seen_keys: set[tuple[int | None, int]] = set()
    detected_projects: set[str] = set()

    current_root_str = str(ROOT).lower()
    current_proj_label = f"{ROOT.name} (Este Projeto)"
    detected_projects.add(current_proj_label)

    # 1. Mapeamento de portas LISTEN ativas por PID
    listening_by_pid: dict[int, list[int]] = {}
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status in ("LISTEN", getattr(psutil, "CONN_LISTEN", "LISTEN")) and conn.laddr and conn.pid:
                listening_by_pid.setdefault(conn.pid, []).append(conn.laddr.port)
    except Exception:
        pass

    # 2. Iterar processos para capturar Node.js, Python, OpenCode e servidores web
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            name = (proc.info["name"] or "").lower()
            cmdline_list = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline_list)
            cmd_lower = cmd_str.lower()

            is_node = "node" in name or "bun" in name or "deno" in name
            is_python = "python" in name
            is_opencode = "opencode" in name
            has_listen = pid in listening_by_pid

            is_dev = is_node or is_python or is_opencode or any(
                k in cmd_lower for k in ("uvicorn", "vite", "next", "fastapi", "mcp", "agent_")
            )
            if not is_dev and not has_listen:
                continue

            cwd = ""
            try:
                cwd = proc.cwd()
            except Exception:
                pass
            cwd_lower = cwd.lower()

            # Atribuição precisa do projeto de origem
            is_current = (
                (current_root_str in cwd_lower or current_root_str in cmd_lower or "app.py" in cmdline_list)
                and "agent_jarvis" not in cmd_lower
                and "agent_master" not in cmd_lower
            )

            if is_current:
                project_name = current_proj_label
            elif "agent_jarvis" in cmd_lower or "agent_jarvis" in cwd_lower:
                project_name = "Agent_Jarvis"
            elif "agent_master" in cmd_lower or "agent_master" in cwd_lower:
                project_name = "Agent_Master_V2"
            elif "opencode" in name or "opencode" in cmd_lower:
                project_name = "OpenCode Server"
            elif cwd and Path(cwd).name and Path(cwd).name not in ("System32", "Windows"):
                project_name = Path(cwd).name
            else:
                project_name = "Servidores Externos"

            detected_projects.add(project_name)

            # Filtro por dropdown
            if filter_project and filter_project != "ALL":
                if filter_project == "CURRENT" and not is_current:
                    continue
                elif filter_project != "CURRENT" and project_name.lower() != filter_project.lower():
                    continue

            ports = listening_by_pid.get(pid, [])
            runtime = "python" if is_python else ("node" if is_node else "other")

            # Resumo amigável do comando
            summary_cmd = cmd_str
            if "app.py" in cmd_str:
                summary_cmd = "FastAPI Backend (app.py)"
            elif "opencode-cli" in cmd_str or "serve" in cmd_str:
                summary_cmd = "OpenCode Server CLI"
            elif "vite" in cmd_lower:
                summary_cmd = "Vite Dev Server"
            elif "next" in cmd_lower:
                summary_cmd = "Next.js Dev Server"
            elif "context7" in cmd_lower:
                summary_cmd = "Context7 MCP Server"
            elif "mcp" in cmd_lower:
                summary_cmd = f"MCP Tool ({Path(cmdline_list[-1]).name if cmdline_list else 'mcp'})"
            elif len(summary_cmd) > 55:
                summary_cmd = summary_cmd[:52] + "..."

            if ports:
                for port in sorted(ports):
                    if (port, pid) in seen_keys:
                        continue
                    seen_keys.add((port, pid))
                    is_ess, ess_reason = is_essential_service(port=port, pid=pid, name=proc.info["name"])
                    servers.append({
                        "port": port,
                        "pid": pid,
                        "name": proc.info["name"],
                        "process": proc.info["name"],
                        "cmdline": cmd_str,
                        "summary": summary_cmd,
                        "cwd": cwd,
                        "project": project_name,
                        "is_current": is_current,
                        "runtime": runtime,
                        "status": "LISTEN",
                        "is_essential": is_ess,
                        "essential_reason": ess_reason,
                        "can_stop": not is_ess,
                        "can_restart": (not is_ess) and (is_current or bool(cmd_str)),
                    })
            elif is_dev and (is_current or "agent_" in cmd_lower or "mcp" in cmd_lower):
                if (None, pid) not in seen_keys:
                    seen_keys.add((None, pid))
                    is_ess, ess_reason = is_essential_service(port=None, pid=pid, name=proc.info["name"])
                    servers.append({
                        "port": None,
                        "pid": pid,
                        "name": proc.info["name"],
                        "process": proc.info["name"],
                        "cmdline": cmd_str,
                        "summary": summary_cmd,
                        "cwd": cwd,
                        "project": project_name,
                        "is_current": is_current,
                        "runtime": runtime,
                        "status": "RUNNING",
                        "is_essential": is_ess,
                        "essential_reason": ess_reason,
                        "can_stop": not is_ess,
                        "can_restart": (not is_ess) and bool(cmd_str),
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    def sort_key(s: dict) -> tuple:
        priority_port = 0 if s["port"] in (8000, 4096, 3000, 3008, 5173, 5678) else 1
        current_prio = 0 if s["is_current"] else 1
        port_num = s["port"] if s["port"] is not None else 999999
        return (priority_port, current_prio, port_num, s["pid"])

    servers.sort(key=sort_key)
    sorted_projs = sorted(list(detected_projects), key=lambda p: (0 if "Este Projeto" in p else 1, p))

    return {
        "status": "ok",
        "servers": servers,
        "projects": sorted_projs,
        "current_project_name": current_proj_label,
        "total": len(servers),
    }


def kill_dev_process(pid: int) -> dict[str, Any]:
    """Finaliza um processo pelo PID de forma segura com fallback para SIGKILL, bloqueando encerramento de serviços essenciais."""
    is_ess, reason = is_essential_service(pid=pid)
    if is_ess:
        return {
            "status": "error",
            "message": f"Operação bloqueada: {reason}. Serviços essenciais do sistema não podem ser encerrados.",
            "pid": pid,
            "is_essential": True,
        }

    try:
        proc = psutil.Process(pid)
        name = proc.name()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return {"status": "ok", "message": f"Processo {name} (PID {pid}) finalizado com sucesso.", "pid": pid}
    except psutil.NoSuchProcess:
        return {"status": "ok", "message": f"Processo PID {pid} já não se encontra em execução.", "pid": pid}
    except Exception as exc:
        return {"status": "error", "message": f"Erro ao finalizar PID {pid}: {exc}", "pid": pid}


def restart_dev_process(pid: int) -> dict[str, Any]:
    """Reinicia um servidor ou processo Node/Python com os mesmos parâmetros."""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        cmdline = proc.cmdline()
        cwd = proc.cwd()

        if pid == os.getpid():
            return {
                "status": "ok",
                "message": "O servidor FastAPI é gerenciado com auto-reload automático de código.",
                "pid": pid,
                "is_self": True,
            }

        if not cmdline:
            return {
                "status": "error",
                "message": f"Não foi possível obter a linha de comando do processo PID {pid} para reiniciá-lo.",
            }

        # Finalizar processo existente
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()

        # Aguardar 300ms para liberação de portas pelo SO
        import time
        time.sleep(0.3)

        new_proc = subprocess.Popen(
            cmdline,
            cwd=cwd or str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

        return {
            "status": "ok",
            "message": f"Servidor {name} reiniciado com sucesso! Novo PID: {new_proc.pid}.",
            "old_pid": pid,
            "new_pid": new_proc.pid,
        }
    except psutil.NoSuchProcess:
        return {"status": "error", "message": f"Processo PID {pid} não encontrado para reiniciar."}
    except Exception as exc:
        return {"status": "error", "message": f"Erro ao reiniciar processo PID {pid}: {exc}"}


def get_safe_port(preferred: int, service_name: str = "", project_name: str = "") -> dict[str, Any]:
    """Verificação mandatória de colisão de portas para o Orquestrador e Programador.
    Garante que todo servidor Node, Python, MCP ou serviço web nunca seja aberto em porta ocupada.
    Se a porta preferida já estiver alocada, retorna a próxima porta livre determinística."""
    is_busy = port_in_use(preferred)
    if not is_busy:
        return {
            "port": preferred,
            "was_in_use": False,
            "original_port": preferred,
            "service": service_name,
            "project": project_name,
            "message": f"Porta :{preferred} está livre e validada com segurança para {service_name or 'serviço'}.",
        }

    safe_port = find_free_port(preferred + 1)
    return {
        "port": safe_port,
        "was_in_use": True,
        "original_port": preferred,
        "service": service_name,
        "project": project_name,
        "message": f"Colisão evitada: Porta :{preferred} já ocupada! Alocada automaticamente a porta segura :{safe_port}.",
    }


def resolve_dev_server_ports_for_prompt(prompt_text: str) -> str:
    """Inspeciona menções a servidores (Vite, FastAPI, Next, etc.) e garante portas anti-colisão no prompt."""
    notes = []
    # Verificar portas comuns
    if any(k in prompt_text.lower() for k in ("vite", "react 19", "frontend", "5173")):
        chk = get_safe_port(5173, "Vite Dev Server")
        if chk["was_in_use"]:
            notes.append(f"- Vite/Frontend: Porta padrão :5173 OCUPADA. Use explicitamente `npm run dev -- --port {chk['port']}`.")

    if any(k in prompt_text.lower() for k in ("3000", "next", "spa_dashboard")):
        chk = get_safe_port(3000, "Web Server")
        if chk["was_in_use"]:
            notes.append(f"- Web Server: Porta padrão :3000 OCUPADA. Use explicitamente a porta :{chk['port']}.")

    if notes:
        header = "\n\n🛡️ **[AUTO-HEAL: VERIFICAÇÃO DE PORTAS ANTI-COLISÃO]**\n"
        return prompt_text + header + "\n".join(notes) + "\n"
    return prompt_text


def kill_orphan(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=3)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return False


def _minimal_yaml(text: str) -> dict:
    data: dict = {"global_rules": {}, "routes": []}
    route: dict | None = None
    in_routes = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("routes:"):
            in_routes = True
            continue
        if not in_routes:
            match = re.match(r"\s*([\w_]+):\s*(.+)$", line)
            if match:
                key, value = match.group(1), match.group(2).strip().strip('"')
                data["global_rules"][key] = value
            continue
        if stripped.startswith("- id:"):
            route = {"id": stripped.split(":", 1)[1].strip().strip('"')}
            data["routes"].append(route)
        elif route is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip().lstrip("- ").strip()
            value = value.strip().strip('"')
            if value.startswith("[") and value.endswith("]"):
                route[key] = [item.strip().strip('"') for item in value[1:-1].split(",") if item.strip()]
            else:
                route[key] = value
    return data


def load_capabilities(path: Path | None = None) -> dict:
    path = path or CAPABILITIES
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return _minimal_yaml(text)


def select_mcps(task: str, capabilities: dict | None = None) -> list[str]:
    caps = capabilities if capabilities is not None else load_capabilities()
    rules = caps.get("global_rules", {}) or {}
    max_active_val = rules.get("max_concurrent_mcps")
    max_active = int(max_active_val) if max_active_val is not None else len(CATALOG)
    always = str(rules.get("always_active_mcp", ALWAYS_ACTIVE))
    active = [always] if always in CATALOG else []
    lowered = task.lower()
    for route in caps.get("routes", []) or []:
        keywords = route.get("trigger_keywords", []) or []
        if isinstance(keywords, str):
            keywords = [keywords]
        if any(str(word).lower() in lowered for word in keywords):
            mcp = route.get("activate_mcp")
            if mcp in CATALOG and mcp not in active:
                active.append(mcp)
    if max_active > 0:
        return active[:max_active]
    return active


def rewrite_mcp_config(active: list[str], path: Path | None = None) -> Path:
    path = path or MCP_CONFIG
    chosen: list[str] = []
    for name in active:
        if name in CATALOG and name not in chosen:
            chosen.append(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    mcp_servers: dict[str, Any] = {}
    for name in chosen:
        meta = CATALOG_DETAILS.get(name, {})
        entry: dict[str, Any] = {
            "enabled": True,
            "source": "concio-studio",
            "available": meta.get("available", False),
            "description": meta.get("description", name),
        }
        if meta.get("command"):
            entry["command"] = meta["command"]
            entry["args"] = meta.get("args", [])
        if meta.get("url"):
            entry["type"] = meta.get("type", "remote")
            entry["url"] = meta["url"]
        mcp_servers[name] = entry
    payload = {"mcpServers": mcp_servers}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_mcp_config(path: Path | None = None) -> list[str]:
    path = path or MCP_CONFIG
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    return [name for name, cfg in servers.items() if cfg.get("enabled")]


def audit_and_reconcile_resources(
    prompt: str = "",
    touched_files: list[str] | None = None,
    auto_activate: bool = True,
    scan_dev_services: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Audita dinamicamente os recursos do sistema, portas e MCPs demandados pelo prompt ou código.
    - Ativa automaticamente os MCPs necessários sem limitação artificial.
    - Identifica serviços e MCPs ociosos para desativação, MAS NUNCA interrompe serviços essenciais.
    - Exige autorização explícita do usuário antes de desativar qualquer serviço ou MCP.
    """
    import time
    import uuid

    prompt_low = (prompt or "").lower()
    touched = [str(f).lower() for f in (touched_files or [])]

    # 1. MCPs necessários identificados pelo prompt e código
    needed_mcps: set[str] = set()

    # Playwright: testes, browser, e2e, scraping
    if any(k in prompt_low for k in ("teste", "test", "e2e", "playwright", "browser", "navegador", "scraping")) or any(
        f.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js")) or "test_" in f for f in touched
    ):
        needed_mcps.add("playwright")

    # ReUI: componentes shadcn, tailwind, UI, design blocks
    if any(k in prompt_low for k in ("reui", "shadcn", "componente", "tailwind", "ui", "pro blocks", "radix", "lucide", "estilo")) or any(
        f.endswith((".tsx", ".jsx", ".vue", "preview.html", "index.html")) for f in touched
    ):
        needed_mcps.add("reui")

    # 21dev: animações, magic ui, telas visuais
    if any(k in prompt_low for k in ("21dev", "magic ui", "animação", "efeito", "motion")):
        needed_mcps.add("21dev")

    # Context7: docs, vetores, pesquisa, documentação
    if any(k in prompt_low for k in ("context7", "doc", "documentação", "pesquisa", "vector", "upstash")):
        needed_mcps.add("context7")

    # DevMaster MCP: RAG, agentes, banco de dados, tools internas
    if any(k in prompt_low for k in ("rag", "agente", "sqlite", "devmaster", "api", "ferramenta", "tools")):
        needed_mcps.add("devmaster-mcp")

    # Figma: design mode, figma tokens
    if any(k in prompt_low for k in ("figma", "design system", "wireframe", "mockup")):
        needed_mcps.add("figma")

    # Browse-user: sessão do usuário, mercado
    if any(k in prompt_low for k in ("browse-user", "sessão", "mercado", "concorrente")):
        needed_mcps.add("browse-user")

    # Always active default
    needed_mcps.add(ALWAYS_ACTIVE)

    current_active = read_mcp_config()
    activated_now: list[str] = []

    # 2. Ativação automática de MCPs demandados (livre, sem teto artificial)
    if auto_activate:
        updated_active = list(current_active)
        for mcp in needed_mcps:
            if mcp in CATALOG and mcp not in updated_active:
                updated_active.append(mcp)
                activated_now.append(mcp)
        if activated_now:
            rewrite_mcp_config(updated_active)
            current_active = read_mcp_config()

    # 3. Propostas de desativação (MCPs ativos não demandados na tarefa atual)
    # REQUISITO CRÍTICO: NUNCA desativa automaticamente! Requer autorização prévia do usuário.
    proposed_deactivations: list[dict[str, Any]] = []

    for mcp in current_active:
        if mcp != ALWAYS_ACTIVE and mcp not in needed_mcps and prompt:
            proposed_deactivations.append({
                "type": "mcp",
                "id": mcp,
                "name": mcp,
                "reason": f"MCP '{mcp}' ativo, mas não demandado pela tarefa atual.",
                "requires_authorization": True,
            })

    # 4. Propostas de desativação de serviços de desenvolvimento ociosos e NÃO ESSENCIAIS
    if scan_dev_services:
        dev_scan = scan_dev_servers()
        for srv in dev_scan.get("servers", []):
            port = srv.get("port")
            pid = srv.get("pid")
            name = srv.get("name") or srv.get("process") or f"Porta {port}"

            # Verificar se é serviço essencial — NUNCA tocar em essenciais!
            is_ess, _ = is_essential_service(port=port, pid=pid, name=name)
            if is_ess:
                continue

            # Propor encerramento se for um servidor de outro projeto ou porta não padrão ociosa
            if srv.get("is_current") is False and port not in (8000, 3000, 5678, 5173):
                proposed_deactivations.append({
                    "type": "service",
                    "id": f"srv_{pid}",
                    "pid": pid,
                    "port": port,
                    "name": name,
                    "reason": f"Servidor de dev externo não essencial na porta :{port} (PID {pid}).",
                    "requires_authorization": True,
                })

    action_id: str | None = None
    if proposed_deactivations:
        action_id = f"act_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        PENDING_RESOURCE_ACTIONS[action_id] = {
            "action_id": action_id,
            "created_at": time.time(),
            "proposed_deactivations": proposed_deactivations,
            "status": "pending_user_approval",
        }
        # Registrar na fila de intervenções do SQLite para visibilidade no monitor
        try:
            from core import database
            for item in proposed_deactivations:
                task_desc = f"[AUTORIZAÇÃO]: Desativar {item['type']} '{item['name']}' ({item['reason']})?"
                database.enqueue_intervention(task=task_desc, agent="Orquestrador", path=db_path)
        except Exception:
            pass

    # Recursos do sistema
    sys_res = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
    }

    return {
        "status": "ok",
        "active_mcps": current_active,
        "activated_now": activated_now,
        "needed_mcps": list(needed_mcps),
        "proposed_deactivations": proposed_deactivations,
        "requires_user_approval": bool(proposed_deactivations),
        "action_id": action_id,
        "system_resources": sys_res,
    }


def confirm_resource_action(action_id: str, approved: bool, item_ids: list[str] | None = None) -> dict[str, Any]:
    """Confirma ou rejeita a desativação de MCPs/serviços com autorização expressa do usuário."""
    record = PENDING_RESOURCE_ACTIONS.get(action_id)
    if not record:
        return {"status": "error", "message": f"Ação de autorização '{action_id}' não encontrada ou expirada."}

    if not approved:
        record["status"] = "rejected_by_user"
        return {"status": "ok", "message": "Desativação cancelada pelo usuário. Nenhum serviço ou MCP foi interrompido.", "action_id": action_id}

    executed = []
    current_active = read_mcp_config()
    to_deactivate = record.get("proposed_deactivations", [])
    if item_ids:
        to_deactivate = [it for it in to_deactivate if it.get("id") in item_ids or it.get("name") in item_ids]

    mcp_to_remove = []
    for item in to_deactivate:
        if item["type"] == "mcp":
            mcp_to_remove.append(item["name"])
            executed.append(f"MCP '{item['name']}' desativado")
        elif item["type"] == "service":
            pid = item.get("pid")
            if pid:
                res = kill_dev_process(pid)
                if res.get("status") == "ok":
                    executed.append(f"Serviço '{item['name']}' (PID {pid}) finalizado")
                else:
                    executed.append(f"Bloqueio/Erro ao finalizar PID {pid}: {res.get('message')}")

    if mcp_to_remove:
        new_active = [m for m in current_active if m not in mcp_to_remove]
        rewrite_mcp_config(new_active)

    record["status"] = "executed"
    record["executed"] = executed
    return {
        "status": "ok",
        "action_id": action_id,
        "executed": executed,
        "active_mcps": read_mcp_config(),
    }
