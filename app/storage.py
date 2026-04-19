from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import SyncEvent, SyncTask


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                """
            )

    def list_tasks(self) -> list[SyncTask]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: int) -> SyncTask | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def create_task(self, task: SyncTask) -> SyncTask:
        now = self._utcnow()
        payload = task.model_dump(exclude={"id", "created_at", "updated_at"})
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (name, enabled, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task.name, int(task.enabled), json.dumps(payload), now, now),
            )
            task_id = int(cursor.lastrowid)
        created = self.get_task(task_id)
        assert created is not None
        return created

    def update_task(self, task_id: int, task: SyncTask) -> SyncTask | None:
        existing = self.get_task(task_id)
        if not existing:
            return None
        payload = task.model_dump(exclude={"id", "created_at", "updated_at"})
        now = self._utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET name = ?, enabled = ?, config_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (task.name, int(task.enabled), json.dumps(payload), now, task_id),
            )
        return self.get_task(task_id)

    def set_task_enabled(self, task_id: int, enabled: bool) -> SyncTask | None:
        task = self.get_task(task_id)
        if not task:
            return None
        updated = task.model_copy(update={"enabled": enabled})
        return self.update_task(task_id, updated)

    def delete_task(self, task_id: int) -> bool:
        with self.connect() as conn:
            conn.execute("DELETE FROM events WHERE task_id = ?", (task_id,))
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def add_event(self, event: SyncEvent) -> SyncEvent:
        now = self._utcnow()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (task_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event.task_id, event.level, event.message, now),
            )
            event_id = int(cursor.lastrowid)
        return SyncEvent(id=event_id, created_at=datetime.fromisoformat(now), **event.model_dump(exclude={"id", "created_at"}))

    def list_events(self, task_id: int, limit: int = 100) -> list[SyncEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_task(self, row: sqlite3.Row) -> SyncTask:
        payload = json.loads(row["config_json"])
        payload["id"] = row["id"]
        payload["created_at"] = row["created_at"]
        payload["updated_at"] = row["updated_at"]
        return SyncTask.model_validate(payload)

    def _row_to_event(self, row: sqlite3.Row) -> SyncEvent:
        return SyncEvent.model_validate(dict(row))

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()
