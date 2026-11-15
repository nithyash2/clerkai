"""SQLite run log: every document processed is recorded for monitoring."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .schemas import RunResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    source        TEXT NOT NULL,
    llm           TEXT NOT NULL,
    status        TEXT NOT NULL,
    doc_type      TEXT,
    confidence    REAL,
    team          TEXT NOT NULL,
    action        TEXT NOT NULL,
    priority      TEXT NOT NULL,
    needs_review  INTEGER NOT NULL,
    pii_masked    INTEGER NOT NULL,
    latency_ms    REAL NOT NULL,
    attempts      INTEGER NOT NULL,
    error         TEXT,
    result_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
"""


class RunStore:
    def __init__(self, path: str | Path = "clerkai.db") -> None:
        # The API serves requests on several threads, so one shared connection is
        # allowed across threads and every database call is guarded by a lock.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.conn.executescript(SCHEMA)

    def log(self, r: RunResult) -> int:
        with self._lock:
            return self._log(r)

    def _log(self, r: RunResult) -> int:
        cur = self.conn.execute(
            """INSERT INTO runs (created_at, source, llm, status, doc_type, confidence, team,
               action, priority, needs_review, pii_masked, latency_ms, attempts, error, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                r.source,
                r.llm,
                r.status,
                r.extraction.doc_type.value if r.extraction else None,
                r.extraction.confidence if r.extraction else None,
                r.decision.team,
                r.decision.action,
                r.decision.priority.value,
                int(r.decision.needs_review),
                sum(r.pii_masked.values()),
                r.latency_ms,
                r.attempts,
                r.error,
                r.model_dump_json(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def stats(self) -> dict[str, float]:
        with self._lock:
            return self._stats()

    def _stats(self) -> dict[str, float]:
        row = self.conn.execute(
            """SELECT COUNT(*) AS runs,
                      AVG(status = 'failed') AS failure_rate,
                      AVG(needs_review) AS review_rate,
                      AVG(latency_ms) AS avg_latency_ms,
                      SUM(pii_masked) AS pii_masked
               FROM runs"""
        ).fetchone()
        return {k: (row[k] or 0) for k in row.keys()}

    def review_queue(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, source, team, priority, result_json FROM runs "
                "WHERE needs_review = 1 ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "team": r["team"],
                "priority": r["priority"],
                "reasons": json.loads(r["result_json"])["decision"]["reasons"],
            }
            for r in rows
        ]
