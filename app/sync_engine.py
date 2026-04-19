from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from .converter import Converter
from .git_ops import GitManager
from .models import SyncEvent, SyncTask, TaskStatus
from .storage import Storage


class TaskEventHandler(FileSystemEventHandler):
    def __init__(self, engine: "SyncEngine", task_id: int) -> None:
        self.engine = engine
        self.task_id = task_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.engine.queue_path(self.task_id, event.src_path)
        if getattr(event, "dest_path", None):
            self.engine.queue_path(self.task_id, event.dest_path)


class SyncEngine:
    def __init__(self, storage: Storage, converter: Converter, git_manager: GitManager) -> None:
        self.storage = storage
        self.converter = converter
        self.git_manager = git_manager
        self.observer = Observer()
        self.handlers: dict[int, TaskEventHandler] = {}
        self.watches: dict[int, ObservedWatch] = {}
        self.statuses: dict[int, TaskStatus] = {}
        self.queued_paths: dict[int, dict[Path, float]] = defaultdict(dict)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)

    def start(self) -> None:
        self.reload_tasks()
        self.observer.start()
        self.worker.start()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.observer.stop()
        self.observer.join(timeout=5)
        self.worker.join(timeout=5)

    def reload_tasks(self) -> None:
        tasks = self.storage.list_tasks()
        current_ids = {task.id for task in tasks if task.id is not None and task.enabled}
        for task_id in list(self.handlers):
            if task_id not in current_ids:
                self.handlers.pop(task_id, None)
                watch = self.watches.pop(task_id, None)
                if watch is not None:
                    self.observer.unschedule(watch)
                self._clear_task_queue(task_id)
        for task in tasks:
            if task.id is None:
                continue
            if task.id not in self.statuses:
                self.statuses[task.id] = TaskStatus(task_id=task.id, running=False)
            if task.enabled and task.id not in self.handlers:
                source_dir = task.paths.source_path()
                source_dir.mkdir(parents=True, exist_ok=True)
                handler = TaskEventHandler(self, task.id)
                watch = self.observer.schedule(handler, str(source_dir), recursive=task.paths.recursive)
                self.handlers[task.id] = handler
                self.watches[task.id] = watch
            elif not task.enabled:
                self.statuses[task.id].running = False
                self._clear_task_queue(task.id)

    def queue_path(self, task_id: int, path: str) -> None:
        task = self.storage.get_task(task_id)
        if not task:
            return
        self._ensure_status(task_id)
        file_path = Path(path)
        if not self._target_path_if_possible(task, file_path):
            return
        if not self.converter.is_supported(task, file_path):
            target_path = self._target_path_if_possible(task, file_path)
            if target_path and target_path.exists():
                with self.lock:
                    self.queued_paths[task_id][file_path] = time.time()
                    self.statuses[task_id].queued_paths = sorted(str(p) for p in self.queued_paths[task_id])
            return
        with self.lock:
            self.queued_paths[task_id][file_path] = time.time()
            self.statuses[task_id].queued_paths = sorted(str(p) for p in self.queued_paths[task_id])

    def rescan_task(self, task_id: int) -> None:
        task = self.storage.get_task(task_id)
        if not task:
            return
        source_root = task.paths.source_path()
        iterator = source_root.rglob("*") if task.paths.recursive else source_root.glob("*")
        for path in iterator:
            if path.is_file():
                self.queue_path(task_id, str(path))

    def get_statuses(self) -> list[TaskStatus]:
        return [self._augment_status(status) for status in self.statuses.values()]

    def remove_task(self, task_id: int) -> None:
        self.handlers.pop(task_id, None)
        watch = self.watches.pop(task_id, None)
        if watch is not None:
            self.observer.unschedule(watch)
        self._clear_task_queue(task_id)
        self.statuses.pop(task_id, None)

    def _ensure_status(self, task_id: int) -> TaskStatus:
        if task_id not in self.statuses:
            self.statuses[task_id] = TaskStatus(task_id=task_id, running=False)
        return self.statuses[task_id]

    def _clear_task_queue(self, task_id: int) -> None:
        with self.lock:
            self.queued_paths.pop(task_id, None)
        if task_id in self.statuses:
            self.statuses[task_id].queued_paths = []

    def _augment_status(self, status: TaskStatus) -> TaskStatus:
        updated = status.model_copy(deep=True)
        updated.last_push_at = self.git_manager.last_push_at(status.task_id)
        return updated

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            tasks = self.storage.list_tasks()
            for task in tasks:
                if task.id is None or not task.enabled:
                    continue
                try:
                    self._process_task_queue(task)
                    pushed = self.git_manager.maybe_push(task)
                except Exception as exc:  # pragma: no cover - defensive
                    self._record_error(task.id, f"Worker failed: {exc}")
                else:
                    if pushed:
                        self._record_event(task.id, "info", "Pushed committed changes.")
            time.sleep(0.5)

    def _process_task_queue(self, task: SyncTask) -> None:
        assert task.id is not None
        threshold = time.time() - task.file_rules.debounce_seconds
        with self.lock:
            pending = [path for path, ts in self.queued_paths[task.id].items() if ts <= threshold]
        if not pending:
            return
        status = self._ensure_status(task.id)
        status.running = True
        status.last_error = None
        status.last_run_at = datetime.now(timezone.utc)
        for source_path in pending:
            try:
                self._sync_path(task, source_path)
            except Exception as exc:  # pragma: no cover - defensive
                self._record_error(task.id, f"{source_path}: {exc}")
            finally:
                with self.lock:
                    self.queued_paths[task.id].pop(source_path, None)
                    status.queued_paths = sorted(str(p) for p in self.queued_paths[task.id])
        status.running = False
        try:
            commit = self.git_manager.commit_task_changes(task)
        except ValueError as exc:
            self._record_error(task.id, f"Git auto-commit skipped: {exc}")
            return
        if commit:
            self._record_event(task.id, "info", f"Committed changes: {commit[:7]}")

    def _sync_path(self, task: SyncTask, source_path: Path) -> None:
        target_path = self.converter.target_path_for(task, source_path)
        if not source_path.exists() or not self.converter.is_supported(task, source_path):
            if target_path.exists():
                target_path.unlink()
                self._prune_empty_dirs(target_path.parent, task.paths.output_dir_path())
                self._record_event(task.id or 0, "info", f"Removed {target_path}")
            return
        content = self.converter.convert_path(task, source_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        self._record_event(task.id or 0, "info", f"Synced {source_path} -> {target_path}")

    def _target_path_if_possible(self, task: SyncTask, source_path: Path) -> Path | None:
        try:
            return self.converter.target_path_for(task, source_path)
        except ValueError:
            return None

    def _record_event(self, task_id: int, level: str, message: str) -> None:
        self.storage.add_event(SyncEvent(task_id=task_id, level=level, message=message))

    def _record_error(self, task_id: int, message: str) -> None:
        status = self._ensure_status(task_id)
        status.last_error = message
        self._record_event(task_id, "error", message)

    @staticmethod
    def _prune_empty_dirs(path: Path, root: Path) -> None:
        current = path
        while current != root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
