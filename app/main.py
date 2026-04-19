from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .converter import Converter
from .git_ops import GitManager
from .models import SyncTask, SystemStatus
from .storage import Storage
from .sync_engine import SyncEngine
from .validation import TaskValidationError, validate_task


STATIC_DIR = Path(__file__).parent / "static"
def create_app(data_dir: Path | None = None) -> FastAPI:
    resolved_data_dir = data_dir or Path(os.getenv("APP_DATA_DIR", ".localdata"))
    storage = Storage(resolved_data_dir / "app.db")
    converter = Converter()
    git_manager = GitManager()
    engine = SyncEngine(storage, converter, git_manager)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine.start()
        try:
            yield
        finally:
            engine.shutdown()

    app = FastAPI(title="Office Docs to MD Sync", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.storage = storage
    app.state.engine = engine
    app.state.git_manager = git_manager

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/tasks", response_model=list[SyncTask])
    def list_tasks() -> list[SyncTask]:
        return storage.list_tasks()

    @app.post("/api/tasks", response_model=SyncTask)
    def create_task(task: SyncTask) -> SyncTask:
        try:
            validate_task(task)
        except TaskValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        created = storage.create_task(task)
        engine.reload_tasks()
        engine.rescan_task(created.id or 0)
        return created

    @app.put("/api/tasks/{task_id}", response_model=SyncTask)
    def update_task(task_id: int, task: SyncTask) -> SyncTask:
        try:
            validate_task(task)
        except TaskValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = storage.update_task(task_id, task)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        engine.reload_tasks()
        engine.rescan_task(task_id)
        return updated

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int) -> dict[str, str]:
        if not storage.delete_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        engine.reload_tasks()
        engine.remove_task(task_id)
        return {"status": "deleted"}

    @app.post("/api/tasks/{task_id}/enable", response_model=SyncTask)
    def enable_task(task_id: int) -> SyncTask:
        updated = storage.set_task_enabled(task_id, True)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        engine.reload_tasks()
        engine.rescan_task(task_id)
        return updated

    @app.post("/api/tasks/{task_id}/disable", response_model=SyncTask)
    def disable_task(task_id: int) -> SyncTask:
        updated = storage.set_task_enabled(task_id, False)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        engine.reload_tasks()
        return updated

    @app.post("/api/tasks/{task_id}/rescan")
    def rescan_task(task_id: int) -> dict[str, str]:
        if not storage.get_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        engine.rescan_task(task_id)
        return {"status": "queued"}

    @app.post("/api/tasks/{task_id}/push")
    def push_task(task_id: int) -> dict[str, str]:
        task = storage.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        try:
            git_manager.ensure_repo(task).remote(task.git.remote_name).push(task.git.branch)
        except Exception as exc:  # pragma: no cover - external
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "pushed"}

    @app.get("/api/tasks/{task_id}/events")
    def list_events(task_id: int) -> list[dict]:
        if not storage.get_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return [event.model_dump(mode="json") for event in storage.list_events(task_id)]

    @app.get("/api/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        statuses = engine.get_statuses()
        running = sum(1 for status in statuses if status.running)
        return SystemStatus(running_tasks=running, total_tasks=len(storage.list_tasks()), statuses=statuses)

    return app


app = create_app()
