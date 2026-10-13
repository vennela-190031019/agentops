"""SQLite trace storage: one row per run, one row per span.

The DB path is resolved from `AGENTOPS_DB_PATH` on every call (not cached at
import time) so tests can point it at a temp file regardless of import
order. Schema creation is idempotent and runs on every connection, so there
is no separate "init" step callers must remember to invoke first.
"""
import os
import sqlite3
import time

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "agentops.db")


def _db_path() -> str:
    return os.environ.get("AGENTOPS_DB_PATH", DEFAULT_DB_PATH)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            question TEXT,
            role TEXT,
            status TEXT,
            answer TEXT,
            created_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            name TEXT,
            latency_ms REAL,
            tokens INTEGER,
            error TEXT
        )
    """)
    return conn


def init_db() -> None:
    _conn().close()


def save_run(run_id: str, question: str, role: str, status: str, answer: str, spans: list[dict]) -> None:
    """Upsert the run's status/answer and append its spans.

    Spans are appended (never deleted) so a pending run's guard/retrieve/plan
    spans and its later approve/reject resume's tool/answer spans both show
    up in the same run's trace.
    """
    conn = _conn()
    conn.execute(
        "INSERT INTO runs (run_id, question, role, status, answer, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, answer=excluded.answer",
        (run_id, question, role, status, answer, time.time()),
    )
    for s in spans:
        conn.execute(
            "INSERT INTO spans (run_id, name, latency_ms, tokens, error) VALUES (?, ?, ?, ?, ?)",
            (run_id, s["name"], s["latency_ms"], s.get("tokens", 0), s.get("error")),
        )
    conn.commit()
    conn.close()


def recent_runs(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        spans = [dict(s) for s in conn.execute(
            "SELECT name, latency_ms, tokens, error FROM spans WHERE run_id = ? ORDER BY id", (r["run_id"],)
        ).fetchall()]
        out.append({
            "run_id": r["run_id"], "question": r["question"], "role": r["role"],
            "status": r["status"], "answer": r["answer"], "created_at": r["created_at"],
            "latency_ms": round(sum(s["latency_ms"] for s in spans), 3),
            "tokens": sum(s["tokens"] or 0 for s in spans),
            "errors": sum(1 for s in spans if s["error"]),
            "spans": spans,
        })
    conn.close()
    return out
