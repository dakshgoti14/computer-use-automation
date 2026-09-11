"""Lightweight SQLite-backed run registry for GET /runs/{run_id}.

This is the one place the assignment's "SQLite for lightweight persistence
where useful" guidance applies concretely: a small, queryable record of
past discovery/replay runs, without pulling in an ORM or a queue for what
is otherwise a single-process demo API.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.api.schemas import RunRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    capability_id TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    evidence_ref TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);
"""


class RunStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def save(self, record: RunRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id, kind, status, capability_id, message, created_at, evidence_ref, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id, record.kind, record.status, record.capability_id,
                record.message, record.created_at, record.evidence_ref,
                json.dumps(record.extra),
            ),
        )
        self._conn.commit()

    def get(self, run_id: str) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT run_id, kind, status, capability_id, message, created_at, evidence_ref, extra "
            "FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row[0], kind=row[1], status=row[2], capability_id=row[3],
            message=row[4], created_at=row[5], evidence_ref=row[6], extra=json.loads(row[7]),
        )

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        rows = self._conn.execute(
            "SELECT run_id, kind, status, capability_id, message, created_at, evidence_ref, extra "
            "FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            RunRecord(
                run_id=r[0], kind=r[1], status=r[2], capability_id=r[3],
                message=r[4], created_at=r[5], evidence_ref=r[6], extra=json.loads(r[7]),
            )
            for r in rows
        ]
