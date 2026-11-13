"""
backend/moco/failure_store.py
Sistema Evolutivo de Aprendizado com Erros e Post-Mortem (Padrão MOCO).
Catalogação estruturada de falhas e injeção dinâmica de heurísticas em agentes LangGraph/LlamaIndex.
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ROOT / "workspace" / "devmaster_history.db"


class FailureMemoryStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._seed_default_heuristics()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS moco_failure_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    target TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    fix_applied TEXT NOT NULL,
                    rule_learned TEXT NOT NULL,
                    stack_tag TEXT NOT NULL DEFAULT 'general',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    occurrence_count INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_moco_fail_target ON moco_failure_memory(target);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_moco_fail_stack ON moco_failure_memory(stack_tag);")

    def _seed_default_heuristics(self) -> None:
        """Sementes heurísticas iniciais com regras de ouro baseadas em experiência de produção."""
        initial_rules = [
            {
                "task": "fastapi_websocket_connection",
                "target": "fastapi_websocket",
                "root_cause": "Conexões WebSocket sem ping_interval gerando hanging sockets e memory leak.",
                "fix_applied": "Adicionar heartbeat com ping/pong explícito e tratamento de WebSocketDisconnect em bloco try/finally.",
                "rule_learned": "Em endpoints FastAPI com WebSockets, sempre encapsular o loop em try/finally e tratar WebSocketDisconnect limpando o subscriber da memória.",
                "stack_tag": "fastapi",
                "severity": "high",
            },
            {
                "task": "supabase_migration_rls",
                "target": "supabase_rls",
                "root_cause": "Tabela criada sem Row Level Security ou política de INSERT sem WITH CHECK (auth.uid() = user_id).",
                "fix_applied": "Adicionar ENABLE ROW LEVEL SECURITY e CREATE POLICY 'insert_own' WITH CHECK (auth.uid() = user_id).",
                "rule_learned": "No Supabase PostgreSQL, toda nova tabela exige ENABLE ROW LEVEL SECURITY e políticas explícitas com WITH CHECK para INSERT/UPDATE.",
                "stack_tag": "supabase",
                "severity": "critical",
            },
            {
                "task": "deploy_port_collision",
                "target": "docker_coolify_port",
                "root_cause": "Container tentando subir em porta 3000 ou 8000 já alocada por processo zumbi local.",
                "fix_applied": "Consultar PortBroker antes do bind e alocar porta efêmera ou próxima disponível (ex: 3008).",
                "rule_learned": "Sempre consultar o PortBroker antes de inicializar serviços Docker/Coolify ou servidores Vite/Node para evitar falha 502/BindError.",
                "stack_tag": "docker",
                "severity": "high",
            },
            {
                "task": "opencode_import_cycle",
                "target": "opencode_linter",
                "root_cause": "Import circular entre orquestrador e FastAPI router quebrando o reload do Uvicorn.",
                "fix_applied": "Mover tipos e modelos de dados para arquivos `schemas.py` puros sem dependências cruzadas.",
                "rule_learned": "Ao criar módulos de orquestração integrados com FastAPI, declare Pydantic models em arquivos de schemas isolados para eliminar ciclos de import.",
                "stack_tag": "python",
                "severity": "medium",
            },
        ]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for r in initial_rules:
                cursor.execute(
                    "SELECT id FROM moco_failure_memory WHERE target = ? AND task = ?",
                    (r["target"], r["task"]),
                )
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO moco_failure_memory 
                        (task, target, root_cause, fix_applied, rule_learned, stack_tag, severity)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (r["task"], r["target"], r["root_cause"], r["fix_applied"], r["rule_learned"], r["stack_tag"], r["severity"]))

    def record_failure(
        self,
        task: str,
        target: str,
        root_cause: str,
        fix_applied: str,
        rule_learned: str,
        stack_tag: str = "general",
        severity: str = "medium",
    ) -> Dict[str, Any]:
        """Registra uma falha estruturada e incrementa ocorrência se regra similar já existir."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, occurrence_count FROM moco_failure_memory WHERE target = ? AND task = ?",
                (target, task),
            )
            existing = cursor.fetchone()
            if existing:
                row_id = existing["id"]
                new_count = existing["occurrence_count"] + 1
                cursor.execute("""
                    UPDATE moco_failure_memory 
                    SET occurrence_count = ?, fix_applied = ?, rule_learned = ?, last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_count, fix_applied, rule_learned, row_id))
            else:
                cursor.execute("""
                    INSERT INTO moco_failure_memory 
                    (task, target, root_cause, fix_applied, rule_learned, stack_tag, severity)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (task, target, root_cause, fix_applied, rule_learned, stack_tag, severity))
                row_id = cursor.lastrowid
                new_count = 1

            return {
                "id": row_id,
                "task": task,
                "target": target,
                "root_cause": root_cause,
                "fix_applied": fix_applied,
                "rule_learned": rule_learned,
                "stack_tag": stack_tag,
                "severity": severity,
                "occurrence_count": new_count,
            }

    def get_relevant_heuristics(
        self,
        target: str = "",
        stack_tag: str = "",
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Recupera regras aprendidas mais relevantes por target, stack ou severidade."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM moco_failure_memory WHERE 1=1"
            params: list[Any] = []

            if target:
                query += " AND (target LIKE ? OR task LIKE ?)"
                params.extend([f"%{target}%", f"%{target}%"])
            if stack_tag and stack_tag != "all":
                query += " AND stack_tag = ?"
                params.append(stack_tag)

            query += " ORDER BY occurrence_count DESC, id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def format_heuristics_prompt(self, target: str = "", stack_tag: str = "") -> str:
        """Formata as heurísticas em bloco Markdown pronto para injeção no prompt do LLM."""
        heuristics = self.get_relevant_heuristics(target=target, stack_tag=stack_tag, limit=3)
        if not heuristics:
            return "- Nenhuma falha catalogada para este cenário. Siga boas práticas de código limpo."

        lines = []
        for h in heuristics:
            lines.append(
                f"- [MOCO-HEURÍSTICA #{h['id']} | {h['stack_tag'].upper()}] {h['rule_learned']} (Causa raiz anterior: {h['root_cause']})"
            )
        return "\n".join(lines)

    def list_failures(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM moco_failure_memory ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

