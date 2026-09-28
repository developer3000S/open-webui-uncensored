"""Trace & feedback persistence (ТЗ §9.8 TraceRecord, §4.7 обратная связь).

SQLite side-store next to the app database (same DATA_DIR), so a container
restart keeps audit history; WAL mode lets the chat path write traces without
blocking readers. Retention follows §10.5/§13.4: rows older than
ORCH_TRACE_RETENTION_DAYS are pruned on write (cheap opportunistic sweep —
no cron dependency in this deployment).

PII posture (§11.2): trace payloads keep snippets already truncated by the
adapters; `raw_query` is stored only when ORCH_TRACE_STORE_QUERIES is on, and
feedback comments are length-capped. Secrets never enter these tables because
the safety filter masks them before synthesis produces the stored payload.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orchestrator_trace (
    trace_id TEXT PRIMARY KEY,
    request_id TEXT,
    tenant_id TEXT,
    user_id TEXT,
    started_at TEXT,
    ended_at TEXT,
    total_latency_ms INTEGER,
    total_cost_units REAL,
    status TEXT,
    recommended_action TEXT,
    intent TEXT,
    mode TEXT,
    payload TEXT NOT NULL,
    created_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trace_created ON orchestrator_trace(created_ts);
CREATE INDEX IF NOT EXISTS ix_trace_tenant ON orchestrator_trace(tenant_id, created_ts);

CREATE TABLE IF NOT EXISTS orchestrator_feedback (
    feedback_id TEXT PRIMARY KEY,
    trace_id TEXT,
    response_id TEXT,
    rating INTEGER,
    kind TEXT,
    signal TEXT,
    comment TEXT,
    created_at TEXT,
    created_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fb_trace ON orchestrator_feedback(trace_id);
"""


def _db_path() -> str:
    data_dir = os.getenv('DATA_DIR', '')
    if not data_dir:
        # backend/open_webui/retrieval/graphrag/trace_store.py -> backend/data
        data_dir = str(Path(__file__).resolve().parents[3] / 'data')
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(data_dir, 'orchestrator.db')


_conn_cache: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn_cache
    if _conn_cache is not None:
        return _conn_cache
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(_SCHEMA)
    conn.commit()
    _conn_cache = conn
    return conn


def _sweep(conn: sqlite3.Connection) -> None:
    days = int(os.getenv('ORCH_TRACE_RETENTION_DAYS', '90'))
    cutoff = time.time() - days * 86400
    conn.execute('DELETE FROM orchestrator_trace WHERE created_ts < ?', (cutoff,))
    conn.execute('DELETE FROM orchestrator_feedback WHERE created_ts < ?', (cutoff,))
    conn.commit()


def store_trace(record) -> None:
    """Persist a TraceRecord (pydantic or dict). Best-effort: observability
    must never break the answer path (§5.2)."""
    if isinstance(record, dict):
        data = record
    else:
        data = record.model_dump()
    try:
        with _lock:
            conn = _connect()
            conn.execute(
                'INSERT OR REPLACE INTO orchestrator_trace VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    data.get('trace_id'),
                    data.get('request_id'),
                    data.get('tenant_id'),
                    data.get('user_id'),
                    data.get('started_at'),
                    data.get('ended_at'),
                    int(data.get('total_latency_ms') or 0),
                    float(data.get('total_cost_units') or 0.0),
                    (data.get('final_response') or {}).get('status'),
                    (data.get('evaluation_report') or {}).get('recommended_action'),
                    (data.get('query_analysis') or {}).get('intent'),
                    (data.get('execution_plan') or {}).get('mode'),
                    json.dumps(data, ensure_ascii=False, default=str),
                    time.time(),
                ),
            )
            conn.commit()
            if int(time.time()) % 500 == 0:  # opportunistic retention sweep
                _sweep(conn)
    except Exception as e:
        log.warning('orchestrator trace store failed: %s', e)


def get_trace(trace_id: str) -> dict | None:
    try:
        with _lock:
            conn = _connect()
            row = conn.execute('SELECT payload FROM orchestrator_trace WHERE trace_id = ?', (trace_id,)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception as e:
        log.warning('orchestrator trace read failed: %s', e)
        return None


def list_traces(limit: int = 50, tenant_id: str | None = None) -> list[dict]:
    q = 'SELECT payload FROM orchestrator_trace'
    args: tuple = ()
    if tenant_id:
        q += ' WHERE tenant_id = ?'
        args = (tenant_id,)
    q += ' ORDER BY created_ts DESC LIMIT ?'
    args = args + (max(1, min(int(limit), 500)),)
    try:
        with _lock:
            conn = _connect()
            rows = conn.execute(q, args).fetchall()
        out = []
        for (payload,) in rows:
            d = json.loads(payload)
            d.pop('candidates', None)  # index view stays small; full via get_trace
            out.append(d)
        return out
    except Exception as e:
        log.warning('orchestrator trace list failed: %s', e)
        return []


def store_feedback(record) -> None:
    if isinstance(record, dict):
        data = record
    else:
        data = record.model_dump()
    try:
        with _lock:
            conn = _connect()
            conn.execute(
                'INSERT OR REPLACE INTO orchestrator_feedback VALUES (?,?,?,?,?,?,?,?,?,?)',
                (
                    data.get('feedback_id'),
                    data.get('trace_id'),
                    data.get('response_id'),
                    data.get('rating'),
                    data.get('kind', 'explicit'),
                    data.get('signal'),
                    (data.get('comment') or '')[:2000],
                    data.get('created_at') or datetime.now(timezone.utc).isoformat(),
                    time.time(),
                ),
            )
            conn.commit()
    except Exception as e:
        log.warning('orchestrator feedback store failed: %s', e)


def recent_feedback_quality(hours: int = 24) -> float | None:
    """Mean normalized rating of explicit feedback in the window — feeds the
    drift metric (§11.3) and admin status endpoint."""
    since = time.time() - hours * 3600
    try:
        with _lock:
            conn = _connect()
            row = conn.execute(
                'SELECT AVG(CAST(rating AS REAL)), COUNT(*) FROM orchestrator_feedback '
                "WHERE kind='explicit' AND rating IS NOT NULL AND created_ts > ?",
                (since,),
            ).fetchone()
        if not row or not row[1]:
            return None
        avg = float(row[0])
        # thumbs (-1/+1) or 1..5 scale both normalize to 0..1
        return round((avg + 1) / 2 if abs(avg) <= 1 else (avg - 1) / 4, 3)
    except Exception:
        return None
