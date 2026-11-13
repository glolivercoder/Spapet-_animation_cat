"""
backend/plandex/router.py
FastAPI Router para Worktrees e Planos Atômicos Sandboxed estilo Plandex / Arquify.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.plandex.worktree_generator import PlandexWorktreeGenerator, ProjectWorktree
from backend.plandex.sandboxed_changeset import PlandexChangesetManager, PlandexPlan
from backend.moco.failure_store import FailureMemoryStore
from backend.integrations.opencode_orchestrator import orchestrator as opencode_orchestrator

router = APIRouter(prefix="/api/v1/plandex", tags=["Plandex Integration"])

worktree_gen = PlandexWorktreeGenerator()
changeset_mgr = PlandexChangesetManager()
failure_store = FailureMemoryStore()


class WorktreeGenerateRequest(BaseModel):
    project_title: str
    project_brief: str
    stack: str = "fastapi_react_sqlite"
    guidelines: Optional[List[str]] = None
    model: Optional[str] = None


class PlanCreateRequest(BaseModel):
    worktree_id: str
    include_heuristics: bool = True


class PlanDispatchRequest(BaseModel):
    plan_id: str
    session_id: Optional[str] = None
    priority: int = 2


@router.post("/worktree/generate", response_model=ProjectWorktree)
async def generate_worktree_endpoint(req: WorktreeGenerateRequest):
    """Gera uma árvore de diretórios e arquivos (Worktree) tipada e determinística."""
    return worktree_gen.generate_worktree(
        project_title=req.project_title,
        project_brief=req.project_brief,
        stack=req.stack,
        guidelines=req.guidelines,
        model=req.model,
    )


@router.get("/worktrees")
async def list_worktrees_endpoint(limit: int = 20):
    return {"worktrees": worktree_gen.list_worktrees(limit=limit)}


@router.get("/worktree/{worktree_id}")
async def get_worktree_endpoint(worktree_id: str):
    wt = worktree_gen.get_worktree(worktree_id)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree não encontrada.")
    return wt


@router.post("/plan/create", response_model=PlandexPlan)
async def create_plan_endpoint(req: PlanCreateRequest):
    """Cria um plano de execução multi-etapas atômicas a partir de uma Worktree."""
    wt = worktree_gen.get_worktree(req.worktree_id)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree não encontrada.")

    heuristics_text = ""
    if req.include_heuristics:
        heuristics_text = failure_store.format_heuristics_prompt(target="fastapi", stack_tag="fastapi")

    return changeset_mgr.create_plan_from_worktree(wt, heuristics_context=heuristics_text)


@router.post("/plan/dispatch")
async def dispatch_plan_endpoint(req: PlanDispatchRequest):
    """Despacha as etapas atômicas do plano sequencialmente para a fila do OpenCode."""
    result = await changeset_mgr.dispatch_plan_to_opencode(
        plan_id=req.plan_id,
        orchestrator=opencode_orchestrator,
        session_id=req.session_id,
        priority=req.priority,
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.get("/plans")
async def list_plans_endpoint(limit: int = 20):
    return {"plans": changeset_mgr.list_plans(limit=limit)}


@router.get("/plan/{plan_id}")
async def get_plan_endpoint(plan_id: str):
    plan = changeset_mgr.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")
    return plan


@router.get("/plan-active")
async def get_active_plan_endpoint():
    """Retorna o plano ativo e seu progresso em tempo real."""
    plan = changeset_mgr.get_active_plan()
    if not plan:
        return {"active": False, "plan": None}
    return {"active": True, "plan": plan}


@router.post("/sync")
async def sync_plandex_endpoint(worktree_id: Optional[str] = None):
    """Força sincronização imediata da Worktree com o sistema de arquivos no disco."""
    synced_wt = worktree_gen.sync_worktree_with_disk(worktree_id)
    active_plan = changeset_mgr.get_active_plan()
    return {
        "status": "SYNCED",
        "worktree": synced_wt,
        "active_plan": active_plan,
    }


