"""Módulo 1/5 — SQLite: histórico triplo, fila de intervenções e lessons learned."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "concio.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK (role IN ('user', 'agent')),
    agent TEXT NOT NULL DEFAULT 'Diretor',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS harness_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    harness TEXT NOT NULL CHECK (harness IN ('opencode', 'claude')),
    module TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    response TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    duration_ms REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS interventions_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL DEFAULT 'Diretor',
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS lessons_learned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL,
    solution TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_history(created_at);
CREATE INDEX IF NOT EXISTS idx_harness_module ON harness_prompts(module);
CREATE INDEX IF NOT EXISTS idx_queue_status ON interventions_queue(status);
CREATE INDEX IF NOT EXISTS idx_lessons_module ON lessons_learned(module);
CREATE TABLE IF NOT EXISTS app_env (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_app_env_key ON app_env(key);
CREATE TABLE IF NOT EXISTS tts_audio_cache (
    cache_key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    clean_text TEXT NOT NULL,
    voice TEXT NOT NULL,
    provider TEXT NOT NULL,
    audio_base64 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tts_cache_key ON tts_audio_cache(cache_key);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with db(path) as conn:
        conn.executescript(SCHEMA)


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def add_chat(role: str, content: str, agent: str = "Diretor", path: Path | None = None) -> int:
    if role not in {"user", "agent"}:
        raise ValueError("role inválido")
    with db(path) as conn:
        cur = conn.execute(
            "INSERT INTO chat_history(role, agent, content) VALUES(?,?,?)", (role, agent, content)
        )
        return int(cur.lastrowid)


def list_chat(limit: int = 100, path: Path | None = None) -> list[dict[str, Any]]:
    with db(path) as conn:
        return _rows(conn.execute("SELECT * FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)))


def add_harness_prompt(
    harness: str,
    prompt: str,
    module: str = "",
    response: str = "",
    exit_code: int | None = None,
    duration_ms: float = 0,
    path: Path | None = None,
) -> int:
    if harness not in {"opencode", "claude"}:
        raise ValueError("harness inválido")
    with db(path) as conn:
        cur = conn.execute(
            """INSERT INTO harness_prompts(harness, module, prompt, response, exit_code, duration_ms)
               VALUES(?,?,?,?,?,?)""",
            (harness, module, prompt, response, exit_code, duration_ms),
        )
        return int(cur.lastrowid)


def list_harness_prompts(limit: int = 100, path: Path | None = None) -> list[dict[str, Any]]:
    with db(path) as conn:
        return _rows(conn.execute("SELECT * FROM harness_prompts ORDER BY id DESC LIMIT ?", (limit,)))


def enqueue_intervention(task: str, agent: str = "Diretor", path: Path | None = None) -> int:
    with db(path) as conn:
        cur = conn.execute("INSERT INTO interventions_queue(agent, task) VALUES(?,?)", (agent, task))
        return int(cur.lastrowid)


def next_intervention(path: Path | None = None) -> dict[str, Any] | None:
    with db(path) as conn:
        row = conn.execute(
            "SELECT * FROM interventions_queue WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE interventions_queue SET status='running' WHERE id=?", (row["id"],))
        data = dict(row)
        data["status"] = "running"
        return data


def finish_intervention(item_id: int, status: str = "done", path: Path | None = None) -> None:
    if status not in {"done", "failed"}:
        raise ValueError("status inválido")
    with db(path) as conn:
        conn.execute(
            "UPDATE interventions_queue SET status=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, item_id),
        )


def list_interventions(status: str | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    with db(path) as conn:
        if status:
            return _rows(
                conn.execute("SELECT * FROM interventions_queue WHERE status=? ORDER BY id", (status,))
            )
        return _rows(conn.execute("SELECT * FROM interventions_queue ORDER BY id"))


def add_lesson(module: str, error: str, solution: str, path: Path | None = None) -> int:
    with db(path) as conn:
        cur = conn.execute(
            "INSERT INTO lessons_learned(module, error, solution) VALUES(?,?,?)",
            (module, error, solution),
        )
        return int(cur.lastrowid)


def list_lessons(limit: int = 100, path: Path | None = None) -> list[dict[str, Any]]:
    with db(path) as conn:
        return _rows(conn.execute("SELECT * FROM lessons_learned ORDER BY id DESC LIMIT ?", (limit,)))


def top_lessons(module: str = "", limit: int = 3, path: Path | None = None) -> list[dict[str, Any]]:
    with db(path) as conn:
        if module:
            return _rows(
                conn.execute(
                    "SELECT * FROM lessons_learned WHERE module=? ORDER BY id DESC LIMIT ?", (module, limit)
                )
            )
        return _rows(conn.execute("SELECT * FROM lessons_learned ORDER BY id DESC LIMIT ?", (limit,)))


def stats(path: Path | None = None) -> dict[str, int]:
    with db(path) as conn:
        return {
            "chat": int(conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]),
            "harness": int(conn.execute("SELECT COUNT(*) FROM harness_prompts").fetchone()[0]),
            "queue": int(conn.execute("SELECT COUNT(*) FROM interventions_queue").fetchone()[0]),
            "lessons": int(conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]),
        }


def tts_stats(path: Path | None = None) -> dict[str, int]:
    with db(path) as conn:
        count = 0
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM tts_audio_cache").fetchone()[0])
        except Exception:
            pass
        return {"tts_cache": count}


def clear_all(path: Path | None = None) -> None:
    with db(path) as conn:
        for table in ("chat_history", "harness_prompts", "interventions_queue", "lessons_learned", "tts_audio_cache"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass


def get_tts_cache(cache_key: str, path: Path | None = None) -> dict[str, Any] | None:
    """Busca áudio sintetizado em cache no SQLite por hash da frase e voz."""
    if not cache_key:
        return None
    with db(path) as conn:
        row = conn.execute("SELECT * FROM tts_audio_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        return dict(row) if row else None


def save_tts_cache(
    cache_key: str,
    text: str,
    clean_text: str,
    voice: str,
    provider: str,
    audio_base64: str,
    mime_type: str = "audio/wav",
    path: Path | None = None,
) -> None:
    """Armazena áudio sintetizado em cache no SQLite para apresentações e frases recorrentes."""
    if not cache_key or not audio_base64:
        return
    with db(path) as conn:
        conn.execute(
            "INSERT INTO tts_audio_cache (cache_key, text, clean_text, voice, provider, audio_base64, mime_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(cache_key) DO UPDATE SET "
            "clean_text = excluded.clean_text, "
            "audio_base64 = excluded.audio_base64, "
            "mime_type = excluded.mime_type, "
            "created_at = CURRENT_TIMESTAMP",
            (cache_key, text, clean_text, voice, provider, audio_base64, mime_type),
        )


def list_tts_cached(limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    """Lista as apresentações e falas cacheadas no banco de dados."""
    with db(path) as conn:
        rows = conn.execute(
            "SELECT cache_key, text, clean_text, voice, provider, mime_type, created_at FROM tts_audio_cache ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_env_setting(key: str, value: str, path: Path | None = None) -> None:
    val_str = str(value).strip() if value is not None else ""
    if not val_str or re.match(r"^[\*•\s]+$", val_str):
        return
    with db(path) as conn:
        conn.execute(
            "INSERT INTO app_env (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (str(key), val_str),
        )


def save_env_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    with db(path) as conn:
        for k, v in settings.items():
            val_str = str(v).strip() if v is not None else ""
            # Proteção estrita: nunca apagar chaves cadastradas com valores vazios ou placeholders
            if not val_str or re.match(r"^[\*•\s]+$", val_str):
                continue
            conn.execute(
                "INSERT INTO app_env (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (str(k), val_str),
            )


def get_env_settings(path: Path | None = None) -> dict[str, str]:
    with db(path) as conn:
        rows = conn.execute("SELECT key, value FROM app_env").fetchall()
        return {r["key"]: r["value"] for r in rows}
