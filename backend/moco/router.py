"""
backend/moco/router.py
FastAPI Router para Orquestração MOCO (Consenso, Failure Memory, Port Broker e Deploy).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.moco.failure_store import FailureMemoryStore
from backend.moco.topological_consensus import ConsensusEngine, ConsensusResult
from backend.moco.mcp_broker import MCPBroker, PortBroker
from backend.moco.deploy_matrix import DeployDecisionMatrix, DeployDecision
from backend.moco.gitea_manager import gitea_manager

router = APIRouter(prefix="/api/v1/moco", tags=["MOCO Orchestration"])

failure_store = FailureMemoryStore()
consensus_engine = ConsensusEngine()
port_broker = PortBroker()


class ConsensusRequest(BaseModel):
    project_title: str
    project_brief: str
    target_audience: str = "Geral"
    threshold: float = 7.0
    model: Optional[str] = None


class FailureRecordRequest(BaseModel):
    task: str
    target: str
    root_cause: str
    fix_applied: str
    rule_learned: str
    stack_tag: str = "general"
    severity: str = "medium"


class DeployRequest(BaseModel):
    app_name: str = "my-concio-app"
    has_websockets: bool = True
    uses_sqlite: bool = True
    is_pure_static: bool = False
    requires_supabase_rls: bool = False
    backend_port: int = 8000


@router.post("/consensus", response_model=ConsensusResult)
async def run_consensus_endpoint(req: ConsensusRequest):
    """Executa o consenso adversarial entre Skeptic e Improver avaliado pelo Architect Gatekeeper."""
    engine = ConsensusEngine(threshold=req.threshold)
    result = await engine.run_adversarial_consensus(
        project_title=req.project_title,
        project_brief=req.project_brief,
        target_audience=req.target_audience,
        model=req.model,
    )
    return result


@router.get("/failures")
async def get_failures_endpoint(target: str = "", stack_tag: str = "", limit: int = 50):
    """Consulta histórico de falhas e heurísticas aprendidas."""
    if target or stack_tag:
        items = failure_store.get_relevant_heuristics(target=target, stack_tag=stack_tag, limit=limit)
    else:
        items = failure_store.list_failures(limit=limit)
    return {"failures": items, "count": len(items)}


@router.post("/failures")
async def record_failure_endpoint(req: FailureRecordRequest):
    """Registra uma nova lição pós-mortem aprendida no Failure Store."""
    res = failure_store.record_failure(
        task=req.task,
        target=req.target,
        root_cause=req.root_cause,
        fix_applied=req.fix_applied,
        rule_learned=req.rule_learned,
        stack_tag=req.stack_tag,
        severity=req.severity,
    )
    return {"status": "RECORDED", "failure": res}


@router.get("/mcps")
async def get_phase_mcps_endpoint(phase: str = "ARCHITECT_WORKTREE"):
    """Retorna os MCPs filtrados sob demanda (Lazy Loading) para a fase solicitada."""
    mcps = MCPBroker.filter_mcps_for_phase(phase)
    return {"phase": phase, "active_mcps": mcps, "supported_phases": MCPBroker.get_all_supported_phases()}


@router.get("/ports")
async def get_ports_endpoint(check_port: Optional[int] = None):
    """Monitora alocações de portas e verifica disponibilidade sem colisão."""
    allocations = port_broker.get_allocations()
    is_free = None
    if check_port is not None:
        is_free = PortBroker.is_port_free(check_port)
    return {
        "allocations": allocations,
        "checked_port": check_port,
        "is_free": is_free,
    }


@router.post("/deploy-decision", response_model=DeployDecision)
async def evaluate_deploy_endpoint(req: DeployRequest):
    """Executa a Matriz de Decisão de Infraestrutura e gera os manifests IaC."""
    return DeployDecisionMatrix.evaluate(
        app_name=req.app_name,
        has_websockets=req.has_websockets,
        uses_sqlite=req.uses_sqlite,
        is_pure_static=req.is_pure_static,
        requires_supabase_rls=req.requires_supabase_rls,
        backend_port=req.backend_port,
    )


@router.get("/gitea/status")
async def get_gitea_status_endpoint():
    """Retorna status da instalação local do Gitea (Zero Docker)."""
    return gitea_manager.get_status()


@router.get("/gitea/commits")
async def get_gitea_commits_endpoint(limit: int = 15):
    """Retorna histórico de commits do repositório local versionado."""
    commits = gitea_manager.list_local_commits(limit=limit)
    return {"status": "ok", "count": len(commits), "commits": commits}


@router.post("/gitea/backup")
async def trigger_gitea_backup_endpoint():
    """Gera snapshot imediato de backup git bundle no repositório local."""
    res = gitea_manager.create_backup_snapshot()
    return res


class ProjectSyncRequest(BaseModel):
    message: Optional[str] = None


class ProjectInitRequest(BaseModel):
    name: Optional[str] = None
    folder_path: Optional[str] = None


@router.get("/gitea/projects/{project_id}/status")
async def get_project_gitea_status_endpoint(project_id: str):
    """Retorna status de versionamento, exclusões e monitoramento Gitea do projeto."""
    return gitea_manager.get_project_gitea_status(project_id)


@router.get("/gitea/projects/{project_id}/commits")
async def get_project_gitea_commits_endpoint(project_id: str, limit: int = 15):
    """Retorna histórico de commits do repositório isolado do projeto."""
    commits = gitea_manager.list_project_commits(project_id, limit=limit)
    return {"status": "ok", "project_id": project_id, "count": len(commits), "commits": commits}


@router.post("/gitea/projects/{project_id}/backup")
async def trigger_project_backup_endpoint(project_id: str):
    """Gera snapshot imediato git bundle na pasta backups do projeto."""
    return gitea_manager.create_project_backup(project_id)


@router.post("/gitea/projects/{project_id}/sync")
async def sync_project_endpoint(project_id: str, req: Optional[ProjectSyncRequest] = None):
    """Executa git add, commit automático e push para repositório do projeto."""
    msg = req.message if req else None
    return gitea_manager.sync_project(project_id, message=msg)


@router.post("/gitea/projects/{project_id}/init")
async def init_project_repo_endpoint(project_id: str, req: Optional[ProjectInitRequest] = None):
    """Inicializa ou re-anexa repositório Git, exclusões e watcher ao projeto."""
    name = req.name if req and req.name else project_id
    fpath = req.folder_path if req and req.folder_path else None
    return gitea_manager.init_project_repo(project_id=project_id, project_name=name, folder_path=fpath)



