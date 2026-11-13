"""
backend/plandex/sandboxed_changeset.py
Gerenciador de Planos e Changesets Sandboxed (Padrão Plandex).
Divide a implementação da worktree em etapas atômicas, despacha ordenadamente para o OpenCode
e atualiza o status de cada passo continuamente a cada alteração ou término de execução.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.plandex.worktree_generator import ProjectWorktree, WorktreeNode, worktree_gen
from backend.moco.failure_store import FailureMemoryStore

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ROOT / "workspace" / "devmaster_history.db"


class PlanStep(BaseModel):
    step_number: int
    file_path: str
    operation: str = "CREATE"  # 'CREATE' | 'UPDATE' | 'VERIFY'
    description: str
    superprompt: str
    verification_cmd: str = ""
    status: str = "PENDING"  # 'PENDING' | 'QUEUED' | 'COMPLETED' | 'FAILED'
    executed_at: Optional[str] = None
    verification_output: str = ""
    verification_passed: bool = False


class PlandexPlan(BaseModel):
    plan_id: str
    worktree_id: str
    project_title: str
    steps: List[PlanStep] = Field(default_factory=list)
    status: str = "DRAFT"  # 'DRAFT' | 'EXECUTING' | 'COMPLETED' | 'FAILED'
    created_at: float = Field(default_factory=time.time)
    updated_at: Optional[str] = None
    completed_steps_count: int = 0


class PlandexChangesetManager:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.failure_store = FailureMemoryStore(self.db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plandex_plans (
                    plan_id TEXT PRIMARY KEY,
                    worktree_id TEXT NOT NULL,
                    project_title TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    total_steps INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            try:
                conn.execute("ALTER TABLE plandex_plans ADD COLUMN updated_at DATETIME;")
            except Exception:
                pass

    def create_plan_from_worktree(
        self,
        worktree: ProjectWorktree,
        heuristics_context: str = "",
    ) -> PlandexPlan:
        """Cria um plano multi-etapas atômicas a partir da Worktree gerada."""
        plan_id = f"plan_{int(time.time() * 1000)}"
        steps: List[PlanStep] = []

        for idx, node in enumerate(worktree.nodes, start=1):
            superprompt = (
                f"# SUPERPROMPT ATÔMICO PLANDEX — ETAPA {idx}/{len(worktree.nodes)}\n"
                f"**Arquivo:** `{node.path}`\n"
                f"**Propósito:** {node.purpose}\n"
                f"**Contrato de Interface:** {node.contract_interface}\n"
                f"**Dependências:** {', '.join(node.dependencies) or 'Nenhuma'}\n\n"
                f"## Diretrizes Ponytail & Anti-Overengineering:\n"
                f"- Escreva código direto e conciso com tipagem forte.\n"
                f"- Não crie arquivos adicionais além deste passo.\n"
                f"- O código deve passar imediatamente na validação: `{node.verification_test}`.\n"
            )
            if heuristics_context:
                superprompt += f"\n## Lições Aprendidas Anteriores (MOCO Failure Store):\n{heuristics_context}\n"

            steps.append(PlanStep(
                step_number=idx,
                file_path=node.path,
                operation="CREATE",
                description=node.purpose,
                superprompt=superprompt,
                verification_cmd=node.verification_test,
                status="PENDING",
            ))

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        plan = PlandexPlan(
            plan_id=plan_id,
            worktree_id=worktree.worktree_id,
            project_title=worktree.project_title,
            steps=steps,
            status="DRAFT",
            updated_at=now_str,
            completed_steps_count=0,
        )

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO plandex_plans (plan_id, worktree_id, project_title, steps_json, total_steps, status, updated_at)
                VALUES (?, ?, ?, ?, ?, 'DRAFT', ?)
            """, (plan_id, worktree.worktree_id, worktree.project_title, json.dumps([s.model_dump() for s in steps]), len(steps), now_str))

        return plan

    async def dispatch_plan_to_opencode(
        self,
        plan_id: str,
        orchestrator: Any,
        session_id: Optional[str] = None,
        priority: int = 2,
    ) -> Dict[str, Any]:
        """
        Enfileira cada etapa do plano atômico na fila inteligente do OpenCodeOrchestrator.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return {"status": "ERROR", "message": f"Plano {plan_id} não encontrado."}

        target_session = session_id or await orchestrator.get_or_create_session()
        queued_ids = []

        for step in plan.steps:
            res = await orchestrator.enqueue_or_dispatch(
                session_id=target_session,
                prompt=step.superprompt,
                source_agent="PLANDEX_ARCHITECT",
                priority=priority,
                sync_tui_chat=False,
            )
            step.status = "QUEUED"
            if "queue_id" in res:
                queued_ids.append(res["queue_id"])

        plan.status = "EXECUTING"
        self._update_plan_in_db(plan)

        return {
            "status": "DISPATCHED",
            "plan_id": plan_id,
            "session_id": target_session,
            "total_steps": len(plan.steps),
            "queued_ids": queued_ids,
        }

    async def on_files_changed(
        self,
        files_touched: List[str],
        prompt_sent: str = "",
        success: bool = True,
        orchestrator: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        MÉTODO CENTRAL DE ATUALIZAÇÃO CONTÍNUA DO PLANDEX.
        Chamado automaticamente pelo OpenCode Orchestrator ou pelo ParallelCodeInspector
        sempre que arquivos são tocados ou modificados.
        """
        normalized_touched = [
            f.replace("\\", "/").lower().strip() for f in files_touched
        ]
        updates_applied = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT plan_id FROM plandex_plans WHERE status IN ('EXECUTING', 'DRAFT') ORDER BY created_at DESC"
            )
            active_plan_rows = cursor.fetchall()

        if not active_plan_rows:
            # Sincroniza ao menos a worktree no disco
            worktree_gen.sync_worktree_with_disk()
            return []

        for row in active_plan_rows:
            plan = self.get_plan(row["plan_id"])
            if not plan:
                continue

            plan_dirty = False
            for step in plan.steps:
                norm_step_file = step.file_path.replace("\\", "/").lower().strip()
                
                # Checa se o arquivo deste passo foi tocado ou mencionado
                is_touched = any(
                    norm_step_file in t or t in norm_step_file for t in normalized_touched
                ) or (prompt_sent and step.file_path in prompt_sent)

                if is_touched and step.status != "COMPLETED":
                    plan_dirty = True
                    step.executed_at = time.strftime("%Y-%m-%d %H:%M:%S")

                    # Executa comando de teste de validação do Plandex se existir
                    test_ok = True
                    test_output = "Passo executado e verificado."

                    if step.verification_cmd:
                        try:
                            exec_cwd = ROOT
                            sub_env = dict(os.environ)
                            # Garante que imports de src/ em workspace/ ou subdiretórios sejam resolvidos
                            potential_paths = [str(ROOT), str(ROOT / "workspace"), str(ROOT / "workspace" / "app")]
                            cur_pypath = sub_env.get("PYTHONPATH", "")
                            sub_env["PYTHONPATH"] = os.pathsep.join(potential_paths) + (os.pathsep + cur_pypath if cur_pypath else "")

                            proc = subprocess.run(
                                step.verification_cmd,
                                shell=True,
                                timeout=15,
                                capture_output=True,
                                text=True,
                                cwd=str(exec_cwd),
                                env=sub_env,
                            )
                            test_ok = (proc.returncode == 0)
                            test_output = (proc.stdout or proc.stderr or "")[:400]
                        except Exception as test_err:
                            test_ok = False
                            test_output = f"Falha ao executar teste: {test_err}"

                    if test_ok:
                        step.status = "COMPLETED"
                        step.verification_passed = True
                        step.verification_output = test_output
                    else:
                        step.status = "FAILED"
                        step.verification_passed = False
                        step.verification_output = test_output
                        
                        # Reflexão MOCO: grava no Failure Store
                        self.failure_store.record_failure(
                            task=f"plandex_verify_{step.file_path}",
                            target=step.file_path,
                            root_cause=test_output[:250],
                            fix_applied="Enfileirado para auto-fix P1.",
                            rule_learned=f"Garantir conformidade contratual em {step.file_path}",
                            stack_tag="plandex",
                            severity="high",
                        )

                        # Auto-Fix P1 no OpenCode se orquestrador estiver disponível (em background)
                        if orchestrator and hasattr(orchestrator, "enqueue_or_dispatch"):
                            fix_prompt = (
                                f"🚨 [AUTO-FIX CRÍTICO PLANDEX] O teste `{step.verification_cmd}` falhou no arquivo `{step.file_path}`:\n"
                                f"Erro capturado:\n{test_output}\n\n"
                                f"Corrija o arquivo `{step.file_path}` imediatamente para fazer o teste passar."
                            )
                            try:
                                import asyncio
                                asyncio.create_task(orchestrator.enqueue_or_dispatch(
                                    session_id=None,
                                    prompt=fix_prompt,
                                    source_agent="QA_AGENT",
                                    priority=1,
                                    sync_tui_chat=False,
                                ))
                            except Exception as fix_err:
                                logger.warning(f"Erro ao disparar auto-fix P1: {fix_err}")

                    updates_applied.append({
                        "plan_id": plan.plan_id,
                        "step_number": step.step_number,
                        "file_path": step.file_path,
                        "status": step.status,
                        "test_ok": test_ok,
                    })

            if plan_dirty:
                self._update_plan_in_db(plan)
                # Sincroniza nós da worktree no disco
                worktree_gen.sync_worktree_with_disk(plan.worktree_id)

                if orchestrator and hasattr(orchestrator, "broadcast_ui"):
                    await orchestrator.broadcast_ui({
                        "event": "plandex_plan_updated",
                        "plan_id": plan.plan_id,
                        "status": plan.status,
                        "completed_steps": plan.completed_steps_count,
                        "total_steps": len(plan.steps),
                    })

        return updates_applied

    def record_step_result(
        self,
        plan_id: str,
        step_number: int,
        success: bool,
        error_log: str = "",
        failure_store: Optional[FailureMemoryStore] = None,
    ) -> Optional[PlanStep]:
        plan = self.get_plan(plan_id)
        if not plan:
            return None

        target_step: Optional[PlanStep] = None
        for step in plan.steps:
            if step.step_number == step_number:
                step.status = "COMPLETED" if success else "FAILED"
                step.executed_at = time.strftime("%Y-%m-%d %H:%M:%S")
                target_step = step
                break

        if not success and error_log and (failure_store or self.failure_store) and target_step:
            store = failure_store or self.failure_store
            store.record_failure(
                task=f"plandex_step_{target_step.file_path}",
                target=target_step.file_path,
                root_cause=error_log[:300],
                fix_applied="Plandex step marked for auto-fix retry.",
                rule_learned=f"Garantir imports e tipagem válida para {target_step.file_path}",
                stack_tag="plandex",
                severity="high",
            )

        self._update_plan_in_db(plan)
        return target_step

    def get_plan(self, plan_id: str) -> Optional[PlandexPlan]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plandex_plans WHERE plan_id = ?", (plan_id,))
            row = cursor.fetchone()
            if not row:
                return None
            raw_steps = json.loads(row["steps_json"])
            steps = [PlanStep(**s) for s in raw_steps]
            completed_count = sum(1 for s in steps if s.status == "COMPLETED")
            row_keys = row.keys()
            updated_at = row["updated_at"] if "updated_at" in row_keys else None
            return PlandexPlan(
                plan_id=row["plan_id"],
                worktree_id=row["worktree_id"],
                project_title=row["project_title"],
                steps=steps,
                status=row["status"],
                updated_at=updated_at,
                completed_steps_count=completed_count,
            )

    def get_active_plan(self) -> Optional[PlandexPlan]:
        """Retorna o plano em execução mais recente."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT plan_id FROM plandex_plans WHERE status IN ('EXECUTING', 'DRAFT') ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return self.get_plan(row["plan_id"])
            # Fallback para o mais recente geral
            cursor.execute("SELECT plan_id FROM plandex_plans ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            return self.get_plan(row["plan_id"]) if row else None

    def _update_plan_in_db(self, plan: PlandexPlan) -> None:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        all_completed = all(s.status == "COMPLETED" for s in plan.steps)
        any_failed = any(s.status == "FAILED" for s in plan.steps)

        if all_completed and plan.steps:
            plan.status = "COMPLETED"
        elif any_failed:
            plan.status = "FAILED"
        elif any(s.status in ("EXECUTING", "QUEUED", "COMPLETED") for s in plan.steps):
            plan.status = "EXECUTING"

        plan.updated_at = now_str
        plan.completed_steps_count = sum(1 for s in plan.steps if s.status == "COMPLETED")

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE plandex_plans 
                SET steps_json = ?, status = ?, updated_at = ?
                WHERE plan_id = ?
            """, (json.dumps([s.model_dump() for s in plan.steps]), plan.status, now_str, plan.plan_id))

    def list_plans(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT plan_id, worktree_id, project_title, total_steps, status, created_at, updated_at FROM plandex_plans ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]


changeset_mgr = PlandexChangesetManager()
