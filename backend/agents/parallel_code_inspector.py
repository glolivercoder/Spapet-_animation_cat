"""Módulo de Análise Paralela de Código e Gerenciamento de Bloqueios de Workspace.
Permite aos agentes Devmaster inspecionar diffs em tempo real sem colisão com o OpenCode."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import httpx

from backend.integrations.opencode_orchestrator import ROOT, orchestrator


class WorkspaceLockManager:
    """Gerencia arquivos bloqueados ou em edição pelo OpenCode para prevenir colisões."""

    def __init__(self) -> None:
        self.manual_locks: dict[str, str] = {}  # file_path -> holder_id

    def _normalize(self, path: str | Path) -> str:
        try:
            rel = Path(path).resolve().relative_to(ROOT.resolve())
            return str(rel).replace("\\", "/").lower()
        except Exception:
            return str(path).replace("\\", "/").lower()

    async def get_locked_files(self, session_id: str | None = None) -> set[str]:
        """Obtém conjunto de caminhos relativos em uso pelo OpenCode a partir do diff ativo."""
        locked = set()
        diffs = await orchestrator.get_session_diff(session_id=session_id)
        for item in diffs:
            if isinstance(item, dict):
                f = item.get("file") or item.get("path")
                if f:
                    locked.add(self._normalize(f))
        for m in self.manual_locks:
            locked.add(self._normalize(m))
        return locked

    async def is_file_locked(self, file_path: str | Path, session_id: str | None = None) -> bool:
        """Verifica se um arquivo específico está em uso pelo OpenCode ou bloqueado manualmente."""
        norm = self._normalize(file_path)
        locked = await self.get_locked_files(session_id=session_id)
        return norm in locked

    def acquire_manual_lock(self, file_path: str | Path, holder: str = "DEVMASTER_AGENT") -> bool:
        norm = self._normalize(file_path)
        if norm in self.manual_locks and self.manual_locks[norm] != holder:
            return False
        self.manual_locks[norm] = holder
        return True

    def release_manual_lock(self, file_path: str | Path, holder: str = "DEVMASTER_AGENT") -> bool:
        norm = self._normalize(file_path)
        if self.manual_locks.get(norm) == holder:
            del self.manual_locks[norm]
            return True
        return False


class ParallelCodeInspector:
    """Inspeciona diffs gerados pelo OpenCode, detecta quebras de sintaxe e aciona correções automáticas."""

    def __init__(self, lock_manager: WorkspaceLockManager | None = None) -> None:
        self.lock_manager = lock_manager or WorkspaceLockManager()

    async def notify_toast(self, message: str, title: str = "Devmaster Monitor") -> bool:
        """Envia aviso toast para a tela do desenvolvedor no OpenCode."""
        try:
            async with httpx.AsyncClient(auth=orchestrator.auth, timeout=3.0) as client:
                await client.post(
                    orchestrator._resolve_url("tui/show-toast"),
                    json={"title": title, "message": message, "variant": "info"},
                )
                return True
        except Exception:
            return False

    async def inspect_session_diffs(self, session_id: str | None = None) -> dict[str, Any]:
        """Lê os diffs parciais da sessão do OpenCode e analisa sintaxe e integridade."""
        try:
            sid = session_id or await orchestrator.get_or_create_session()
            diffs = await orchestrator.get_session_diff(session_id=sid)
        except RuntimeError as exc:
            return {"status": "OFFLINE", "session_id": session_id, "diffs_count": 0, "message": str(exc)}

        if not diffs:
            return {"status": "CLEAN", "session_id": sid, "diffs_count": 0, "message": "Nenhum diff pendente."}

        errors_found = []
        for item in diffs:
            if not isinstance(item, dict):
                continue
            file_name = item.get("file") or item.get("path")
            patch_content = item.get("patch") or item.get("content") or ""

            if not file_name:
                continue

            target_file = ROOT / file_name
            # Se o arquivo existe no disco, ler o conteúdo integral para validação completa
            full_text = ""
            if target_file.exists():
                try:
                    full_text = target_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

            code_to_check = full_text or patch_content

            # 1. Validação de Sintaxe Python (ast.parse)
            if file_name.endswith(".py") and code_to_check:
                try:
                    ast.parse(code_to_check, filename=file_name)
                except SyntaxError as syn_err:
                    errors_found.append({
                        "file": file_name,
                        "error_type": "SyntaxError",
                        "message": str(syn_err),
                        "line": syn_err.lineno,
                    })

            # 2. Validação de Sintaxe JSON
            elif file_name.endswith(".json") and code_to_check:
                try:
                    json.loads(code_to_check)
                except Exception as json_err:
                    errors_found.append({
                        "file": file_name,
                        "error_type": "JSONDecodeError",
                        "message": str(json_err),
                    })

        # Se houver erro crítico detectado, despachar SuperPrompt na fila P1 (CRITICAL)
        if errors_found:
            err = errors_found[0]
            super_prompt = (
                f"🚨 [CRITICAL BUG FIX - QA AGENT]\n"
                f"Detectada inconsistência crítica de código no arquivo `{err['file']}`:\n"
                f"• Erro: {err['error_type']} - {err['message']}\n"
                f"Por favor, revise o arquivo e corrija a sintaxe imediatamente preservando o padrão do projeto."
            )

            enqueue_res = await orchestrator.enqueue_or_dispatch(
                prompt=super_prompt,
                session_id=sid,
                source_agent="QA_AGENT",
                priority=1,  # PRIORITY 1: CRITICAL
                sync_tui_chat=True,
            )

            await self.notify_toast(
                f"Bug detectado em {err['file']}. Prompt de correção P1 inserido na fila.",
                title="QA Auto-Healing",
            )

            return {
                "status": "CRITICAL_BUG_ENQUEUED",
                "session_id": sid,
                "error": err,
                "queue_info": enqueue_res,
            }

        return {
            "status": "CLEAN",
            "session_id": sid,
            "diffs_count": len(diffs),
            "message": "Todos os arquivos no diff passaram na inspeção de sintaxe e integridade.",
        }

    async def apply_safe_direct_patch(
        self,
        file_path: str | Path,
        content: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Aplica modificação direta em arquivo, garantindo ausência de colisão com o OpenCode."""
        sid = session_id or await orchestrator.get_or_create_session()
        is_locked = await self.lock_manager.is_file_locked(file_path, session_id=sid)

        if is_locked:
            return {
                "status": "COLLISION_PREVENTED",
                "file": str(file_path),
                "message": (
                    f"O arquivo '{file_path}' está no diff ativo do OpenCode. "
                    "Para evitar perda de dados, enfileire um prompt na fila inteligente em vez de aplicar o patch direto."
                ),
            }

        target = ROOT / file_path if not Path(file_path).is_absolute() else Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        # Notificar sincronização em tempo real do Plandex
        try:
            from backend.plandex.sandboxed_changeset import changeset_mgr
            rel_file = str(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target)
            await changeset_mgr.on_files_changed(
                files_touched=[rel_file],
                prompt_sent=f"Patch direto aplicado em {rel_file}",
                success=True,
                orchestrator=orchestrator,
            )
        except Exception:
            pass

        await self.notify_toast(f"Arquivo {target.name} atualizado pelo Agente Devmaster.", title="File Patch")

        return {
            "status": "PATCH_APPLIED",
            "file": str(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target),
            "bytes_written": len(content.encode("utf-8")),
        }


# Instâncias Singleton
lock_manager = WorkspaceLockManager()
code_inspector = ParallelCodeInspector(lock_manager=lock_manager)

