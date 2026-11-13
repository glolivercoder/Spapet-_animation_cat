"""Orquestrador e Cliente Unificado para o OpenCode Server e Fila Anti-Colisão."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("devmaster.opencode")

ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DB = ROOT / "workspace" / "devmaster_history.db"
DEFAULT_OPENCODE_URL = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
DEFAULT_OPENCODE_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "devmaster_opencode_2026")


class PromptEnqueueRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    session_title: str | None = None
    priority: int = 2  # 1: CRITICAL, 2: USER, 3: AGENT_SUGGESTION
    source_agent: str = "USER"
    sync_tui_chat: bool = True
    wait_seconds: int | None = None


class OpenCodeOrchestrator:
    """Gerenciador central de comunicação com OpenCode Server (porta 4096),
    fila inteligente anti-colisão com PriorityQueue e persistência em SQLite."""

    def __init__(
        self,
        base_url: str = DEFAULT_OPENCODE_URL,
        password: str | None = DEFAULT_OPENCODE_PASSWORD,
        db_path: Path | str = HISTORY_DB,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.auth = ("opencode", password) if password else None
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_status: dict[str, str] = {}  # session_id -> 'idle' | 'working'
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.active_session_id: str | None = None
        self.ui_subscribers: list[WebSocket] = []
        self._worker_task: asyncio.Task | None = None
        self._server_process: subprocess.Popen | None = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS opencode_chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    model_used TEXT,
                    prompt_sent TEXT NOT NULL,
                    llm_conversational_response TEXT NOT NULL,
                    files_touched_json TEXT,
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    execution_duration_ms INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS opencode_prompt_queue (
                    queue_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 2,
                    source_agent TEXT NOT NULL,
                    prompt_payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'QUEUED',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME
                )
                """
            )
            conn.commit()

    def ensure_worker_started(self) -> None:
        """Garante que o worker assíncrono em background esteja executando."""
        if self._worker_task is None or self._worker_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._worker_task = loop.create_task(self.queue_worker_loop())
            except RuntimeError:
                pass

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(auth=self.auth, timeout=timeout)

    def _resolve_url(self, path: str) -> str:
        p = path.lstrip("/")
        if p.startswith("api/"):
            return f"{self.base_url}/{p}"
        if p.startswith(("session", "tui", "app", "config", "event", "global", "project", "permission", "pair", "command")):
            # Contrato validado ao vivo contra `opencode serve` v200+: rotas sob /api/
            return f"{self.base_url}/api/{p}"
        return f"{self.base_url}/{p}"

    async def ensure_server_started(self) -> dict[str, Any]:
        """No startup: verifica o OpenCode Server e, se offline, tenta levantá-lo de verdade.
        Retorna um diagnóstico honesto (nunca finge que está de pé)."""
        health = await self.check_health()
        if health.get("connected"):
            return {**health, "provisioned": True}
        if os.environ.get("OPENCODE_AUTO_START", "1") == "0":
            return {**health, "provisioned": False, "warning": "auto-start desabilitado via OPENCODE_AUTO_START=0"}
        started = await asyncio.to_thread(self.start_server_process)
        if started:
            health2 = await self.check_health()
            return {**health2, "provisioned": True, "spawned": True}
        return {
            **health,
            "provisioned": False,
            "warning": f"Falha ao iniciar `opencode serve` na porta 4096 (CLI ausente ou sem permissão).",
        }

    async def check_health(self) -> dict[str, Any]:
        """Testa a conectividade com o OpenCode Server."""
        try:
            async with self._client(timeout=3.0) as client:
                resp = await client.get(self._resolve_url("session"))
                if resp.status_code in (200, 204):
                    return {"connected": True, "base_url": self.base_url, "status": "ONLINE"}
        except Exception as exc:
            return {"connected": False, "base_url": self.base_url, "error": str(exc), "status": "OFFLINE"}
        return {"connected": False, "base_url": self.base_url, "status": "UNKNOWN"}

    async def get_or_create_session(
        self,
        directory: str | None = None,
        title: str | None = None,
        force_new: bool = False,
        model: str | dict[str, str] | None = None,
    ) -> str:
        """Localiza a sessão ativa pelo título do projeto ou cria uma nova no OpenCode.

        Honestidade: nunca fabrica IDs — se o OpenCode estiver indisponível, levanta erro.
        Garante que novas sessões nasçam com modelo resolvido válido (não model=/).
        """
        target_dir = directory or str(ROOT)
        desired_title = (title or "").strip()
        try:
            async with self._client(timeout=5.0) as client:
                resp = await client.get(self._resolve_url("session"))
                if resp.status_code == 200:
                    data = resp.json()
                    sessions = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    if not force_new and desired_title:
                        for s in sessions:
                            s_title = (s.get("title") or "").strip()
                            loc = s.get("location", {}).get("directory", "")
                            same_dir = not loc or os.path.normpath(loc).lower() == os.path.normpath(target_dir).lower()
                            if same_dir and s_title.lower() == desired_title.lower():
                                self.active_session_id = s.get("id")
                                return self.active_session_id

                    if not force_new and not desired_title:
                        if self.active_session_id and any(s.get("id") == self.active_session_id for s in sessions):
                            return self.active_session_id
                        if sessions:
                            self.active_session_id = sessions[0].get("id")
                            return self.active_session_id

                session_title = desired_title or "DevMaster Workspace Session"
                
                # Resolução explícita de modelo para a sessão (evita cair no default global quebrado)
                model_ref: dict[str, str] | None = None
                raw_model = model or os.environ.get("OPENCODE_MODEL") or "omniroute/Low_cust_code"
                if isinstance(raw_model, dict):
                    model_ref = raw_model
                elif isinstance(raw_model, str) and raw_model:
                    if "/" in raw_model:
                        p_id, m_id = raw_model.split("/", 1)
                        model_ref = {"providerID": p_id, "id": m_id}
                    else:
                        model_ref = {"providerID": "opencode", "id": raw_model}

                create_payload: dict[str, Any] = {
                    "title": session_title,
                    "location": {"directory": target_dir},
                }
                if model_ref:
                    create_payload["model"] = model_ref

                create_resp = await client.post(
                    self._resolve_url("session"),
                    json=create_payload,
                )
                if create_resp.status_code in (200, 201):
                    session_data = create_resp.json().get("data", {})
                    new_id = session_data.get("id") or ""
                    if not str(new_id).startswith("ses"):
                        raise RuntimeError(f"OpenCode retornou session_id inválido: {new_id!r}")
                    self.active_session_id = new_id
                    return self.active_session_id
                raise RuntimeError(
                    f"OpenCode recusou criação de sessão (HTTP {create_resp.status_code}): {create_resp.text[:200]}"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"OpenCode Server indisponível em {self.base_url}: {exc}") from exc

    async def is_opencode_busy(self, session_id: str) -> bool:
        """Verifica em tempo real se a sessão está em execução ('working')."""
        # 1. Checagem em memória
        if self.session_status.get(session_id) == "working":
            return True

        # 2. Checagem via API do OpenCode
        try:
            async with self._client(timeout=4.0) as client:
                resp = await client.get(self._resolve_url(f"session/{session_id}"))
                if resp.status_code == 200:
                    data = resp.json()
                    t = data.get("time", {})
                    busy_time = t.get("busy", 0) or 0
                    idle_time = t.get("idle", 0) or 0
                    # Se busy for mais recente que idle, a sessão está executando
                    is_busy = busy_time > idle_time
                    self.session_status[session_id] = "working" if is_busy else "idle"
                    return is_busy
        except Exception:
            pass

        return self.session_status.get(session_id, "idle") == "working"

    async def get_session_diff(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Obtém o diff de arquivos alterados na sessão do OpenCode."""
        sid = session_id or await self.get_or_create_session()
        try:
            async with self._client(timeout=8.0) as client:
                resp = await client.get(self._resolve_url(f"session/{sid}/diff"))
                if resp.status_code == 200:
                    diff_data = resp.json()
                    if isinstance(diff_data, list):
                        return diff_data
                    if isinstance(diff_data, dict) and "data" in diff_data:
                        return diff_data["data"]
        except Exception:
            pass
        return []

    async def enqueue_or_dispatch(
        self,
        prompt: str,
        session_id: str | None = None,
        session_title: str | None = None,
        source_agent: str = "USER",
        priority: int = 2,
        sync_tui_chat: bool = True,
        wait_seconds: int | None = None,
        model: str | dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Insere o prompt na fila inteligente com prioridade se o OpenCode estiver ocupado,
        ou despacha imediatamente caso esteja ocioso."""
        self.ensure_worker_started()
        sid = session_id or await self.get_or_create_session(title=session_title, model=model)
        queue_id = f"q_{time.time_ns()}_{os.urandom(3).hex()}"

        busy = await self.is_opencode_busy(sid)
        queue_not_empty = not self.queue.empty()

        if busy or queue_not_empty:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO opencode_prompt_queue 
                    (queue_id, session_id, priority, source_agent, prompt_payload, status) 
                    VALUES (?, ?, ?, ?, ?, 'QUEUED')
                    """,
                    (queue_id, sid, priority, source_agent, prompt),
                )
                conn.commit()

            # Enfileirar na PriorityQueue assíncrona (menor número = maior prioridade)
            await self.queue.put((priority, time.time(), {
                "queue_id": queue_id,
                "session_id": sid,
                "prompt": prompt,
                "source_agent": source_agent,
                "sync_tui_chat": sync_tui_chat,
                "wait_seconds": wait_seconds,
            }))

            await self.broadcast_ui({
                "event": "queue_updated",
                "status": "QUEUED",
                "queue_id": queue_id,
                "priority": priority,
                "source_agent": source_agent,
                "prompt": prompt[:120],
            })

            return {
                "status": "QUEUED",
                "queue_id": queue_id,
                "priority": priority,
                "session_id": sid,
                "message": "OpenCode está ocupado ou fila ativa. Prompt posicionado com segurança.",
            }

        # Despacho direto se estiver idle
        return await self._execute_prompt(
            session_id=sid,
            prompt=prompt,
            source_agent=source_agent,
            sync_tui_chat=sync_tui_chat,
            queue_id=queue_id,
            wait_seconds=wait_seconds,
        )

    @staticmethod
    def _extract_assistant_text(msg: dict[str, Any]) -> str:
        """Extrai o texto real de uma mensagem do assistente conforme o contrato do OpenCode."""
        # Formas conhecidas: parts[], content[], payload.text
        for key in ("parts", "content"):
            blocks = msg.get(key)
            if isinstance(blocks, list):
                texts = []
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") in ("text", None) and b.get("text"):
                        texts.append(str(b["text"]))
                if texts:
                    return "\n".join(texts).strip()
        payload = msg.get("payload", {})
        if isinstance(payload, dict) and payload.get("text"):
            return str(payload["text"]).strip()
        return ""

    async def _collect_final_response(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        prior_assistant_ids: set[str],
        wait_seconds: int,
    ) -> tuple[str, str, bool, str]:
        """Aguarda a execução assíncrona do OpenCode e coleta o texto real do assistente.

        Retorna (texto, model_used, success, motivo). Sem fabricar resposta: se nada real
        chegar no prazo, devolve falha com o motivo exato.
        """
        deadline = time.monotonic() + wait_seconds
        last_assistant: dict[str, Any] | None = None
        pending_idle_polls = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)

            # Sempre que houver nova mensagem do assistente concluída, captura
            try:
                m_resp = await client.get(self._resolve_url(f"session/{session_id}/message"))
                if m_resp.status_code == 200:
                    messages = m_resp.json().get("data", []) or []
                    for m in reversed(messages):
                        if not isinstance(m, dict) or m.get("type") != "assistant" or m.get("id") in prior_assistant_ids:
                            continue
                        completed = (m.get("time") or {}).get("completed")
                        finish = m.get("finish")
                        if (completed or finish) and finish != "aborted":
                            last_assistant = m
            except Exception:
                pass

            if last_assistant is not None:
                finish = last_assistant.get("finish")
                if finish == "error":
                    err = last_assistant.get("error") or {}
                    cause = err.get("message") or json.dumps(err)[:300] if isinstance(err, dict) else str(err)
                    return "", self._model_ref(last_assistant), False, f"OpenCode agent falhou: {cause}"
                if finish in ("stop", "aborted", "switch") and (last_assistant.get("time") or {}).get("completed"):
                    text = self._extract_assistant_text(last_assistant)
                    if text:
                        return text, self._model_ref(last_assistant), True, "ok"

            # Sessão ociosa sem mensagem de assistente nova: confirma por 3 polls seguidos
            if not await self.is_opencode_busy(session_id):
                pending_idle_polls += 1
                if pending_idle_polls >= 3 and last_assistant is None:
                    return "", "opencode-agent", False, "OpenCode ficou ocioso sem retornar mensagem do assistente."
            else:
                pending_idle_polls = 0

        if last_assistant is not None:
            finish = last_assistant.get("finish")
            if finish == "error":
                err = last_assistant.get("error") or {}
                cause = err.get("message") or "erro desconhecido"
                return "", self._model_ref(last_assistant), False, f"OpenCode agent falhou: {cause}"
            text = self._extract_assistant_text(last_assistant)
            if text:
                return text, self._model_ref(last_assistant), True, "ok (coletado no limite de espera)"
        return "", "opencode-agent", False, f"Timeout aguardando execução do OpenCode ({wait_seconds}s)."

    @staticmethod
    def _model_ref(msg: dict[str, Any] | None) -> str:
        if not msg:
            return "opencode-agent"
        model = msg.get("model") or {}
        if isinstance(model, dict) and model.get("id"):
            return f"{model.get('providerID', 'unknown')}/{model['id']}"
        return "opencode-agent"

    async def _execute_prompt(
        self,
        session_id: str,
        prompt: str,
        source_agent: str,
        sync_tui_chat: bool,
        queue_id: str,
        wait_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Executa o prompt na sessão do OpenCode, AGUARDA a execução, coleta a resposta
        real do assistente e persiste status honesto (COMPLETED | FAILED)."""
        if wait_seconds is None:
            wait_seconds = int(os.environ.get("OPENCODE_WAIT_SECONDS", "240"))

        start_ms = int(time.time() * 1000)
        self.session_status[session_id] = "working"
        await self.broadcast_ui({
            "event": "session_status_changed",
            "session_id": session_id,
            "status": "working",
            "active_prompt": prompt[:120],
        })

        llm_response_text = ""
        failure_reason = ""
        execution_ok = False
        files_touched: list[str] = []
        model_used = "opencode-agent"

        try:
            async with self._client(timeout=30.0) as client:
                # 1. Sincronizar na interface TUI SOMENTE se explicitamente habilitado
                # (as rotas /api/tui/* existem apenas em instâncias com TUI; no `serve` vHTTP dão 404)
                if sync_tui_chat and os.environ.get("OPENCODE_TUI_SYNC", "0") == "1":
                    try:
                        await client.post(self._resolve_url("tui/clear-prompt"))
                        await client.post(self._resolve_url("tui/append-prompt"), json={"text": prompt})
                        await client.post(self._resolve_url("tui/submit-prompt"))
                    except Exception:
                        logger.info("TUI sync indisponível nesta instância (rotas ausentes).")

                # 2. Baseline de mensagens do assistente (para reconhecer a resposta NOVA)
                prior_assistant_ids: set[str] = set()
                try:
                    m_resp = await client.get(self._resolve_url(f"session/{session_id}/message"))
                    if m_resp.status_code == 200:
                        for m in (m_resp.json().get("data", []) or []):
                            if isinstance(m, dict) and m.get("type") == "assistant":
                                prior_assistant_ids.add(m.get("id"))
                except Exception:
                    pass

                # 3. Despachar o prompt (contrato validado ao vivo: {"text": ...} → 200, execução assíncrona)
                resp = await client.post(self._resolve_url(f"session/{session_id}/prompt"), json={"text": prompt})
                if resp.status_code not in (200, 201):
                    failure_reason = f"OpenCode recusou o prompt (HTTP {resp.status_code}): {resp.text[:300]}"
                else:
                    # 4. Aguardar e coletar a resposta real do assistente
                    llm_response_text, model_used, execution_ok, failure_reason = await self._collect_final_response(
                        client, session_id, prior_assistant_ids, wait_seconds
                    )
        except Exception as err:
            execution_ok = False
            failure_reason = failure_reason or f"OpenCode Server inacessível: {err}"

        # 5. Diffs capturados APÓS a conclusão (para alimentar QA/Plandex com dados reais)
        if execution_ok:
            try:
                async with self._client(timeout=15.0) as client:
                    diff_resp = await client.get(self._resolve_url(f"session/{session_id}/diff"))
                    if diff_resp.status_code == 200:
                        diff_items = diff_resp.json().get("data", []) or diff_resp.json()
                        if isinstance(diff_items, list):
                            for d in diff_items:
                                if isinstance(d, dict):
                                    f = d.get("file") or d.get("path")
                                    if f:
                                        files_touched.append(str(f))
            except Exception:
                pass

        duration_ms = int(time.time() * 1000) - start_ms
        self.session_status[session_id] = "idle"

        final_status = "COMPLETED" if execution_ok else "FAILED"
        if not execution_ok and not llm_response_text:
            llm_response_text = f"[FALHA DE EXECUÇÃO] {failure_reason}"
        else:
            llm_response_text = f"{llm_response_text}\n\n---\n_motivo do encerramento: {failure_reason or 'concluído'}_"

        # 6. Histórico real + status honesto no SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO opencode_chat_history
                (session_id, source_agent, model_used, prompt_sent, llm_conversational_response, files_touched_json, execution_duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    source_agent,
                    model_used,
                    prompt,
                    llm_response_text,
                    json.dumps(files_touched),
                    duration_ms,
                ),
            )
            conn.execute(
                """
                UPDATE opencode_prompt_queue
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE queue_id = ?
                """,
                (final_status, queue_id),
            )
            conn.commit()

        # 6.1 Sincronização automática contínua com o Plandex (apenas com resultado real)
        try:
            from backend.plandex.sandboxed_changeset import changeset_mgr
            await changeset_mgr.on_files_changed(
                files_touched=files_touched,
                prompt_sent=prompt,
                success=execution_ok,
                orchestrator=self,
            )
        except Exception as p_err:
            logger.info(f"[Plandex Sync] Notice: {p_err}")

        # 7. Broadcast para a interface do Devmaster
        await self.broadcast_ui({
            "event": "history_updated",
            "session_id": session_id,
            "source_agent": source_agent,
            "prompt": prompt,
            "response": llm_response_text,
            "status": final_status,
            "files_touched": files_touched,
            "duration_ms": duration_ms,
        })
        await self.broadcast_ui({
            "event": "session_status_changed",
            "session_id": session_id,
            "status": "idle",
        })
        if not execution_ok:
            await self.broadcast_ui({
                "event": "queue_error",
                "queue_id": queue_id,
                "error": failure_reason,
            })

        return {
            "status": final_status,
            "queue_id": queue_id,
            "session_id": session_id,
            "model_used": model_used,
            "response": llm_response_text,
            "reason": failure_reason,
            "files_touched": files_touched,
            "duration_ms": duration_ms,
        }

    async def queue_worker_loop(self) -> None:
        """Worker em background que processa a fila respeitando o estado e debounce do OpenCode."""
        while True:
            try:
                priority, timestamp, item = await self.queue.get()
                session_id = item["session_id"]
                queue_id = item["queue_id"]

                # Verificar se o item foi cancelado enquanto estava na fila
                with sqlite3.connect(self.db_path) as conn:
                    row = conn.execute("SELECT status FROM opencode_prompt_queue WHERE queue_id=?", (queue_id,)).fetchone()
                    if row and row[0] == "CANCELLED":
                        self.queue.task_done()
                        continue

                # Aguardar OpenCode ficar livre com debounce de 1.5s
                while await self.is_opencode_busy(session_id):
                    await asyncio.sleep(1.5)

                # Debounce de segurança
                await asyncio.sleep(1.0)

                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("UPDATE opencode_prompt_queue SET status = 'PROCESSING' WHERE queue_id = ?", (queue_id,))
                    conn.commit()

                try:
                    await self._execute_prompt(
                        session_id=session_id,
                        prompt=item["prompt"],
                        source_agent=item["source_agent"],
                        sync_tui_chat=item.get("sync_tui_chat", True),
                        queue_id=queue_id,
                        wait_seconds=item.get("wait_seconds"),
                    )
                except Exception as exc:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("UPDATE opencode_prompt_queue SET status = 'FAILED' WHERE queue_id = ?", (queue_id,))
                        conn.commit()
                    await self.broadcast_ui({
                        "event": "queue_error",
                        "queue_id": queue_id,
                        "error": str(exc),
                    })
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(1.0)

    def cancel_queue_item(self, queue_id: str) -> bool:
        """Cancela um item enfileirado no SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE opencode_prompt_queue SET status = 'CANCELLED' WHERE queue_id = ? AND status = 'QUEUED'",
                (queue_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        """Lista os itens da fila de prompts com filtros opcionais."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM opencode_prompt_queue WHERE status = ? ORDER BY priority ASC, created_at ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM opencode_prompt_queue ORDER BY CASE status WHEN 'PROCESSING' THEN 0 WHEN 'QUEUED' THEN 1 ELSE 2 END, priority ASC, created_at DESC LIMIT 50"
                ).fetchall()
            return [dict(r) for r in rows]

    def list_history(
        self,
        limit: int = 50,
        query: str | None = None,
        source_agent: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista o histórico intelectual de conversas e prompts enviados ao OpenCode."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            clauses = []
            params = []
            if query:
                clauses.append("(prompt_sent LIKE ? OR llm_conversational_response LIKE ?)")
                like = f"%{query}%"
                params.extend([like, like])
            if source_agent:
                clauses.append("source_agent = ?")
                params.append(source_agent)

            where_str = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = f"SELECT * FROM opencode_chat_history {where_str} ORDER BY id DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, tuple(params)).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                if item.get("files_touched_json"):
                    try:
                        item["files_touched"] = json.loads(item["files_touched_json"])
                    except Exception:
                        item["files_touched"] = []
                else:
                    item["files_touched"] = []
                out.append(item)
            return out

    def start_server_process(self, port: int = 4096) -> bool:
        """Inicia o processo nativo `opencode serve` em background caso não esteja rodando."""
        opencode_bin = shutil.which("opencode") or shutil.which("opencode.cmd") or "opencode"
        env = dict(os.environ)
        if self.password:
            env["OPENCODE_SERVER_PASSWORD"] = self.password

        cmd = [opencode_bin, "serve", "--hostname", "127.0.0.1", "--port", str(port)]
        is_win_script = os.name == "nt" and str(opencode_bin).lower().endswith((".cmd", ".bat"))
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self._server_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=is_win_script,
                **kwargs,
            )
            # Aguardar até 5 segundos para bind da porta
            for _ in range(10):
                time.sleep(0.5)
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        return True
        except Exception:
            pass
        return False

    def stop_server_process(self) -> bool:
        """Encerra o processo do OpenCode gerenciado se estiver ativo."""
        if self._server_process and self._server_process.poll() is None:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=3)
            except Exception:
                self._server_process.kill()
            self._server_process = None
            return True
        return False

    async def register_ui_subscriber(self, ws: WebSocket) -> None:
        self.ui_subscribers.append(ws)

    def unregister_ui_subscriber(self, ws: WebSocket) -> None:
        if ws in self.ui_subscribers:
            self.ui_subscribers.remove(ws)

    async def broadcast_ui(self, payload: dict[str, Any]) -> None:
        for ws in list(self.ui_subscribers):
            try:
                await ws.send_json(payload)
            except Exception:
                self.unregister_ui_subscriber(ws)


# Instância Singleton do Orquestrador
orchestrator = OpenCodeOrchestrator()
router = APIRouter(prefix="/api/v1/opencode", tags=["OpenCode Integration"])


@router.get("/status")
async def get_opencode_status() -> dict[str, Any]:
    health = await orchestrator.check_health()
    active_sid = None
    busy = False
    if health.get("connected"):
        try:
            active_sid = await orchestrator.get_or_create_session()
            busy = await orchestrator.is_opencode_busy(active_sid)
        except Exception:
            active_sid = None
            busy = False
    queue_items = orchestrator.list_queue(status="QUEUED")
    return {
        "server": health,
        "active_session_id": active_sid,
        "is_busy": busy,
        "queue_size": len(queue_items),
        "queue_pending": len(queue_items),
    }


@router.get("/pair")
async def get_opencode_pair_link() -> dict[str, Any]:
    """Gera um pairing link novo e retorna a senha configurada."""
    try:
        async with httpx.AsyncClient(auth=orchestrator.auth, timeout=5.0) as client:
            resp = await client.post(f"{orchestrator.base_url}/api/pair")
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("code")
                return {
                    "code": code,
                    "pairing_link": f"{orchestrator.base_url}/auth/connect/{code}",
                    "password": orchestrator.password or "devmaster_opencode_2026",
                    "expires_in": data.get("expires_in", 300),
                }
    except Exception:
        pass
    return {
        "code": None,
        "pairing_link": None,
        "password": orchestrator.password or "devmaster_opencode_2026",
        "expires_in": 0,
    }


@router.post("/prompt")
async def send_prompt_to_opencode(req: PromptEnqueueRequest) -> dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt não pode ser vazio")
    try:
        res = await orchestrator.enqueue_or_dispatch(
            prompt=req.prompt,
            session_id=req.session_id,
            source_agent=req.source_agent,
            priority=req.priority,
            sync_tui_chat=req.sync_tui_chat,
            wait_seconds=req.wait_seconds,
        )
        return res
    except RuntimeError as exc:
        return {
            "status": "FAILED",
            "error": str(exc),
            "message": f"OpenCode Server indisponível para despacho imediato: {exc}",
        }


@router.get("/queue")
def list_opencode_queue(status: str | None = None) -> list[dict[str, Any]]:
    return orchestrator.list_queue(status=status)


@router.delete("/queue/{queue_id}")
def cancel_queue_prompt(queue_id: str) -> dict[str, Any]:
    ok = orchestrator.cancel_queue_item(queue_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item não encontrado na fila ou já processado")
    return {"status": "CANCELLED", "queue_id": queue_id}


@router.get("/history")
def list_opencode_history(
    limit: int = 50,
    q: str | None = None,
    source_agent: str | None = None,
) -> list[dict[str, Any]]:
    return orchestrator.list_history(limit=limit, query=q, source_agent=source_agent)


@router.get("/diff")
async def get_opencode_diff(session_id: str | None = None) -> list[dict[str, Any]]:
    return await orchestrator.get_session_diff(session_id=session_id)


@router.post("/start")
def start_opencode_server(port: int = 4096) -> dict[str, Any]:
    started = orchestrator.start_server_process(port=port)
    return {"started": started, "port": port}


@router.post("/stop")
def stop_opencode_server() -> dict[str, Any]:
    stopped = orchestrator.stop_server_process()
    return {"stopped": stopped}


@router.websocket("/ws")
async def opencode_websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await orchestrator.register_ui_subscriber(websocket)
    try:
        # Enviar estado inicial imediatamente
        active_sid = await orchestrator.get_or_create_session()
        busy = await orchestrator.is_opencode_busy(active_sid)
        await websocket.send_json({
            "event": "init",
            "session_id": active_sid,
            "status": "working" if busy else "idle",
            "queue": orchestrator.list_queue(status="QUEUED"),
        })
        while True:
            # Manter conexão viva recebendo eventuais comandos do cliente
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        orchestrator.unregister_ui_subscriber(websocket)
    except Exception:
        orchestrator.unregister_ui_subscriber(websocket)

