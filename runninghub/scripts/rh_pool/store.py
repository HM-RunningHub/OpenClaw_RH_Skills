"""SQLite-backed store for the RunningHub async workflow task pool.

Scope: global pool, no project/batch grouping. Completion is a plain fact -
`outstanding` drops to 0. The pool does not track "was it reported": the
polling automation's own existence is that state (see rh_pool/notify.py).

Task status:
  PENDING        enqueued locally, not yet sent to RunningHub
  DISPATCHED     create succeeded, rh_task_id known (RH: QUEUED/RUNNING)
  SUCCESS        terminal
  FAILED         terminal (RH reported failure)
  SUBMIT_FAILED  terminal (create failed before a taskId was obtained)
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

# Status groups
OUTSTANDING_STATUSES = ("PENDING", "DISPATCHED")
TERMINAL_STATUSES = ("SUCCESS", "FAILED", "SUBMIT_FAILED")


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ conn
    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        """Connection that is actually closed (sqlite's `with conn` is not)."""
        conn = self._new_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id    TEXT NOT NULL,
                    instance_type  TEXT NOT NULL DEFAULT 'default',
                    node_overrides TEXT,            -- JSON list
                    request_json   TEXT,            -- JSON, api key excluded
                    rh_task_id     TEXT,            -- set once DISPATCHED
                    status         TEXT NOT NULL DEFAULT 'PENDING',
                    submitted_at   INTEGER,         -- local create-to-RH (ms)
                    started_at     INTEGER,         -- first observed running (ms)
                    updated_at     INTEGER NOT NULL,
                    finished_at    INTEGER,
                    cost_money     REAL,
                    cost_third_party_money REAL,
                    cost_coins     INTEGER,
                    cost_time_s    INTEGER,
                    error_code     TEXT,
                    error_type     TEXT,
                    error_message  TEXT,
                    results_json   TEXT,
                    inputs_json    TEXT,            -- uploaded inputs (local->rh_file_name)
                    downloads_json TEXT,            -- downloaded output files
                    session_key    TEXT             -- originating session (for wake-back)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_rh_id
                    ON tasks(rh_task_id) WHERE rh_task_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS uploads (
                    local_path   TEXT PRIMARY KEY,
                    size         INTEGER NOT NULL,
                    mtime        INTEGER NOT NULL,
                    rh_file_name TEXT NOT NULL,
                    created_at   INTEGER NOT NULL
                );
                """
            )
            self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns introduced after a DB was first created (idempotent)."""
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        wanted = {
            "cost_coins": "ALTER TABLE tasks ADD COLUMN cost_coins INTEGER",
            "cost_third_party_money":
                "ALTER TABLE tasks ADD COLUMN cost_third_party_money REAL",
            "inputs_json": "ALTER TABLE tasks ADD COLUMN inputs_json TEXT",
            "downloads_json": "ALTER TABLE tasks ADD COLUMN downloads_json TEXT",
            "session_key": "ALTER TABLE tasks ADD COLUMN session_key TEXT",
        }
        for column, ddl in wanted.items():
            if column not in existing:
                conn.execute(ddl)

    # ------------------------------------------------------------------ meta
    @staticmethod
    def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db() as conn:
            self._set_meta(conn, key, value)

    # --------------------------------------------------------------- enqueue
    def enqueue(self, jobs: Iterable[dict],
                session_key: str | None = None) -> list[int]:
        """Insert jobs as PENDING. Each job:
        workflow_id, instance_type?, node_overrides?(list), request_json?(dict),
        inputs?(list of uploaded-input records).

        session_key records the originating session so the drain can be
        reported back to it.
        """
        ts = now_ms()
        ids: list[int] = []
        with self._db() as conn:
            for job in jobs:
                cur = conn.execute(
                    """
                    INSERT INTO tasks (workflow_id, instance_type, node_overrides,
                                       request_json, inputs_json, session_key,
                                       status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        str(job["workflow_id"]),
                        str(job.get("instance_type") or "default"),
                        json.dumps(job.get("node_overrides") or [], ensure_ascii=False),
                        json.dumps(job.get("request_json") or {}, ensure_ascii=False),
                        json.dumps(job.get("inputs") or [], ensure_ascii=False),
                        session_key,
                        ts,
                    ),
                )
                ids.append(int(cur.lastrowid))
        return ids

    # ------------------------------------------------------------- retrieval
    def get_pending(self, limit: int) -> list[sqlite3.Row]:
        with self._db() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM tasks WHERE status='PENDING' "
                    "ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            )

    def get_active(self) -> list[sqlite3.Row]:
        """Dispatched, not terminal (need RH polling)."""
        with self._db() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM tasks WHERE status='DISPATCHED' ORDER BY id ASC"
                ).fetchall()
            )

    def count_status(self) -> dict[str, int]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM tasks GROUP BY status"
            ).fetchall()
        counts = {r["status"]: r["c"] for r in rows}
        counts["outstanding"] = sum(counts.get(s, 0) for s in OUTSTANDING_STATUSES)
        return counts

    def get_task(self, *, pool_id: int | None = None,
                 rh_task_id: str | None = None) -> sqlite3.Row | None:
        with self._db() as conn:
            if pool_id is not None:
                return conn.execute("SELECT * FROM tasks WHERE id=?", (pool_id,)).fetchone()
            if rh_task_id is not None:
                return conn.execute(
                    "SELECT * FROM tasks WHERE rh_task_id=?", (rh_task_id,)
                ).fetchone()
        return None

    def list_tasks(self, status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        with self._db() as conn:
            if status:
                return list(conn.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall())
            return list(conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall())

    # ----------------------------------------------------------- transitions
    def mark_dispatched(self, pool_id: int, rh_task_id: str) -> None:
        ts = now_ms()
        with self._db() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status='DISPATCHED', rh_task_id=?, submitted_at=COALESCE(submitted_at, ?),
                       updated_at=?
                   WHERE id=? AND status='PENDING'""",
                (str(rh_task_id), ts, ts, pool_id),
            )

    def mark_submit_failed(self, pool_id: int, error_type: str,
                           error_code: str = "", error_message: str = "") -> None:
        ts = now_ms()
        with self._db() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status='SUBMIT_FAILED', error_type=?, error_code=?,
                       error_message=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='PENDING'""",
                (error_type, error_code, error_message, ts, ts, pool_id),
            )

    def apply_query_result(self, pool_id: int, status: str, *,
                           rh_status: str | None = None,
                           results: list[dict] | None = None,
                           cost_money: float | None = None,
                           cost_third_party_money: float | None = None,
                           cost_coins: int | None = None,
                           cost_time_s: int | None = None,
                           error_code: str = "",
                           error_type: str = "",
                           error_message: str = "") -> None:
        """Apply a normalized RH query snapshot to a DISPATCHED task."""
        ts = now_ms()
        with self._db() as conn:
            if status == "SUCCESS":
                conn.execute(
                    """UPDATE tasks SET status='SUCCESS', results_json=?,
                           cost_money=COALESCE(?, cost_money),
                           cost_third_party_money=COALESCE(?, cost_third_party_money),
                           cost_coins=COALESCE(?, cost_coins),
                           cost_time_s=COALESCE(?, cost_time_s),
                           finished_at=COALESCE(finished_at, ?), updated_at=?
                       WHERE id=?""",
                    (json.dumps(results or [], ensure_ascii=False), cost_money,
                     cost_third_party_money, cost_coins, cost_time_s, ts, ts, pool_id),
                )
            elif status == "FAILED":
                conn.execute(
                    """UPDATE tasks SET status='FAILED', error_code=?, error_type=?,
                           error_message=?, cost_money=COALESCE(?, cost_money),
                           finished_at=COALESCE(finished_at, ?), updated_at=?
                       WHERE id=?""",
                    (error_code, error_type, error_message, cost_money, ts, ts, pool_id),
                )
            else:
                # Still pending on RH; record first observed RUNNING as started.
                if rh_status == "RUNNING":
                    conn.execute(
                        """UPDATE tasks SET started_at=COALESCE(started_at, ?),
                               updated_at=? WHERE id=?""",
                        (ts, ts, pool_id),
                    )
                else:
                    conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, pool_id))

    # ------------------------------------------------------- uploads / ledger
    def find_upload(self, local_path: str, size: int, mtime: int) -> str | None:
        """Return cached rh_file_name when path+size+mtime match, else None."""
        with self._db() as conn:
            row = conn.execute(
                "SELECT rh_file_name FROM uploads "
                "WHERE local_path=? AND size=? AND mtime=?",
                (str(local_path), int(size), int(mtime)),
            ).fetchone()
        return row["rh_file_name"] if row else None

    def record_upload(self, local_path: str, size: int, mtime: int,
                      rh_file_name: str) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT INTO uploads(local_path, size, mtime, rh_file_name, created_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(local_path) DO UPDATE SET "
                "size=excluded.size, mtime=excluded.mtime, "
                "rh_file_name=excluded.rh_file_name, created_at=excluded.created_at",
                (str(local_path), int(size), int(mtime), str(rh_file_name), now_ms()),
            )

    def set_inputs(self, pool_id: int, inputs: list[dict]) -> None:
        """Record uploaded inputs: [{param, fieldName, localPath, rhFileName}]."""
        with self._db() as conn:
            conn.execute("UPDATE tasks SET inputs_json=?, updated_at=? WHERE id=?",
                         (json.dumps(inputs, ensure_ascii=False), now_ms(), pool_id))

    def set_downloads(self, pool_id: int, downloads: list[dict]) -> None:
        """Record downloaded outputs: [{nodeId, url, path, size, outputType}]."""
        with self._db() as conn:
            conn.execute(
                "UPDATE tasks SET downloads_json=?, updated_at=? WHERE id=?",
                (json.dumps(downloads, ensure_ascii=False), now_ms(), pool_id))

    def distinct_session_keys(self) -> list[str]:
        """Distinct originating sessions with finished work pending wake-back."""
        with self._db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_key FROM tasks "
                "WHERE session_key IS NOT NULL AND session_key != ''"
            ).fetchall()
        return [r["session_key"] for r in rows]

    def clear_session_keys(self) -> None:
        """Drop wake-back targets after a batch drain has been reported."""
        with self._db() as conn:
            conn.execute("UPDATE tasks SET session_key=NULL "
                         "WHERE session_key IS NOT NULL")



def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("node_overrides", "request_json", "results_json",
                "inputs_json", "downloads_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
