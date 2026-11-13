"""
backend/plandex/worktree_generator.py
Gerador de Árvore de Diretórios e Arquivos do Projeto (Worktree Architecture estilo Plandex / Arquify).
Gera planos estruturados e determinísticos de arquivos com contratos tipados e testes de verificação.
Inclui sincronização contínua com o estado real do sistema de arquivos (disk sync).
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core import llm_router

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ROOT / "workspace" / "devmaster_history.db"


class WorktreeNode(BaseModel):
    path: str
    type: str = "file"  # 'file' | 'dir'
    purpose: str
    contract_interface: str = ""
    dependencies: List[str] = Field(default_factory=list)
    verification_test: str = ""
    status: str = "PENDING"  # 'PENDING' | 'SYNCED' | 'MODIFIED' | 'MISSING' | 'VERIFIED'
    disk_exists: bool = False
    size_bytes: int = 0
    last_modified: Optional[str] = None


class ProjectWorktree(BaseModel):
    worktree_id: str
    project_title: str
    stack: str
    root_dir: str = "."
    nodes: List[WorktreeNode] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    last_synced_at: Optional[str] = None


class PlandexWorktreeGenerator:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plandex_worktrees (
                    worktree_id TEXT PRIMARY KEY,
                    project_title TEXT NOT NULL,
                    stack TEXT NOT NULL,
                    nodes_json TEXT NOT NULL,
                    total_files INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            try:
                conn.execute("ALTER TABLE plandex_worktrees ADD COLUMN last_synced_at DATETIME;")
            except Exception:
                pass

    def generate_worktree(
        self,
        project_title: str,
        project_brief: str,
        stack: str = "fastapi_react_sqlite",
        guidelines: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> ProjectWorktree:
        """
        Gera uma especificação de árvore de arquivos estilo Plandex/Arquify.
        Respeita a filosofia Ponytail (~50% menos arquivos, código limpo e contratos explícitos).
        """
        worktree_id = f"wt_{int(time.time() * 1000)}"
        nodes = self._build_nodes_for_stack(project_title, project_brief, stack, guidelines)

        # Checar se algum arquivo já existe no disco
        for node in nodes:
            target = ROOT / node.path
            if target.exists():
                node.disk_exists = True
                node.size_bytes = target.stat().st_size
                node.status = "SYNCED"
                node.last_modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(target.stat().st_mtime))
            else:
                node.status = "MISSING"

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        worktree = ProjectWorktree(
            worktree_id=worktree_id,
            project_title=project_title,
            stack=stack,
            root_dir=".",
            nodes=nodes,
            last_synced_at=now_str,
        )

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO plandex_worktrees (worktree_id, project_title, stack, nodes_json, total_files, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (worktree_id, project_title, stack, json.dumps([n.model_dump() for n in nodes]), len(nodes), now_str))

        return worktree

    def _build_nodes_for_stack(
        self,
        title: str,
        brief: str,
        stack: str,
        guidelines: Optional[List[str]] = None,
    ) -> List[WorktreeNode]:
        """Gera nós essenciais seguindo Ponytail e contratos isolados."""
        nodes: List[WorktreeNode] = []

        # 1. Config / Schemas
        nodes.append(WorktreeNode(
            path="src/schemas.py",
            purpose="Modelos de dados estritos Pydantic v2 e DTOs de entrada/saída",
            contract_interface="BaseModel, Field, Request/Response payloads",
            dependencies=[],
            verification_test="python -c \"import src.schemas; print('Schemas OK')\"",
        ))

        # 2. Database / Storage
        nodes.append(WorktreeNode(
            path="src/database.py",
            purpose="Persistência SQLite local embutida com suporte a migrations e WAL",
            contract_interface="init_db(), get_connection(), execute_query()",
            dependencies=["src/schemas.py"],
            verification_test="python -c \"import src.database; src.database.init_db()\"",
        ))

        # 3. Core Engine / Business Logic
        nodes.append(WorktreeNode(
            path="src/core_engine.py",
            purpose=f"Lógica de negócio central do MVP: {title}",
            contract_interface="CoreService, process_task(), calculate_results()",
            dependencies=["src/schemas.py", "src/database.py"],
            verification_test="pytest tests/test_core_engine.py -q",
        ))

        # 4. API Endpoints / WebSocket Router
        nodes.append(WorktreeNode(
            path="src/api_router.py",
            purpose="Rotas FastAPI REST e streaming WebSocket em tempo real",
            contract_interface="APIRouter, GET/POST endpoints, WebSocket handler",
            dependencies=["src/schemas.py", "src/core_engine.py"],
            verification_test="pytest tests/test_api_endpoints.py -q",
        ))

        # 5. Tests
        nodes.append(WorktreeNode(
            path="tests/test_core_engine.py",
            purpose="Bateria de testes unitários com asserções determinísticas de 98%+",
            contract_interface="test_schemas(), test_database(), test_core_flow()",
            dependencies=["src/core_engine.py"],
            verification_test="python -m pytest tests/test_core_engine.py -v",
        ))

        # 6. UI / Frontend View (se stack incluir React/HTML)
        if "react" in stack or "html" in stack or "jamstack" in stack:
            nodes.append(WorktreeNode(
                path="static/app_view.html",
                purpose="Interface reativa e responsiva com Tailwind CSS e WebSocket listener",
                contract_interface="DOM bindings, state manager, ws connection",
                dependencies=["src/api_router.py"],
                verification_test="python -c \"from pathlib import Path; assert Path('static/app_view.html').exists()\"",
            ))

        return nodes

    def sync_worktree_with_disk(self, worktree_id: Optional[str] = None) -> Optional[ProjectWorktree]:
        """
        Sincroniza o estado de cada nó da Worktree com o sistema de arquivos real (ROOT).
        Atualiza status vivo: SYNCED, MISSING, MODIFIED, tamanho e timestamp.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if worktree_id:
                cursor.execute("SELECT * FROM plandex_worktrees WHERE worktree_id = ?", (worktree_id,))
            else:
                cursor.execute("SELECT * FROM plandex_worktrees ORDER BY created_at DESC LIMIT 1")

            row = cursor.fetchone()
            if not row:
                return None

            raw_nodes = json.loads(row["nodes_json"])
            nodes = [WorktreeNode(**n) for n in raw_nodes]
            has_changes = False

            for node in nodes:
                target = ROOT / node.path
                if target.exists():
                    prev_status = node.status
                    node.disk_exists = True
                    cur_size = target.stat().st_size
                    cur_mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(target.stat().st_mtime))
                    
                    if node.size_bytes != cur_size or node.last_modified != cur_mtime:
                        node.status = "MODIFIED" if prev_status == "SYNCED" else "SYNCED"
                        node.size_bytes = cur_size
                        node.last_modified = cur_mtime
                        has_changes = True
                    elif node.status == "MISSING":
                        node.status = "SYNCED"
                        has_changes = True
                else:
                    if node.disk_exists or node.status != "MISSING":
                        node.disk_exists = False
                        node.status = "MISSING"
                        node.size_bytes = 0
                        node.last_modified = None
                        has_changes = True

            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                UPDATE plandex_worktrees 
                SET nodes_json = ?, last_synced_at = ? 
                WHERE worktree_id = ?
            """, (json.dumps([n.model_dump() for n in nodes]), now_str, row["worktree_id"]))
            conn.commit()

            return ProjectWorktree(
                worktree_id=row["worktree_id"],
                project_title=row["project_title"],
                stack=row["stack"],
                nodes=nodes,
                last_synced_at=now_str,
            )

    def get_worktree(self, worktree_id: str) -> Optional[ProjectWorktree]:
        """Retorna a worktree sempre sincronizada com o disco em tempo real."""
        return self.sync_worktree_with_disk(worktree_id)

    def list_worktrees(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT worktree_id, project_title, stack, total_files, created_at, last_synced_at FROM plandex_worktrees ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]


worktree_gen = PlandexWorktreeGenerator()
