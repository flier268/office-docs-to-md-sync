from pathlib import Path

import pytest
from fastapi import HTTPException

from app.main import create_app
from app.models import SyncTask, TaskGitConfig, TaskPaths


def route_endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route {method} {path} not found")


def test_list_tasks(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    app.state.storage.create_task(
        SyncTask(
            name="Task API",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst"), output_subdir="md"),
        )
    )
    endpoint = route_endpoint(app, "/api/tasks")
    tasks = endpoint()
    assert tasks[0].name == "Task API"


def test_create_task_rejects_invalid_git_scope(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    endpoint = route_endpoint(app, "/api/tasks", "POST")
    repo_root = tmp_path / "dst"
    repo_root.mkdir()
    from git import Repo

    Repo.init(repo_root, initial_branch="main")
    task = SyncTask(
        name="Bad Git",
        paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(repo_root), output_subdir="md"),
        git=TaskGitConfig(enabled=True, auto_push=True, remote_name="origin", branch="missing"),
    )

    with pytest.raises(HTTPException) as exc_info:
        endpoint(task)

    assert exc_info.value.status_code == 400
    assert "Git remote 'origin' does not exist" in str(exc_info.value.detail)


def test_delete_and_toggle_task(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    created = app.state.storage.create_task(
        SyncTask(
            name="Task API",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst"), output_subdir="md"),
        )
    )
    disable_endpoint = route_endpoint(app, "/api/tasks/{task_id}/disable", "POST")
    enable_endpoint = route_endpoint(app, "/api/tasks/{task_id}/enable", "POST")
    delete_endpoint = route_endpoint(app, "/api/tasks/{task_id}", "DELETE")

    disabled = disable_endpoint(created.id)
    enabled = enable_endpoint(created.id)
    deleted = delete_endpoint(created.id)

    assert disabled.enabled is False
    assert enabled.enabled is True
    assert deleted["status"] == "deleted"
    assert app.state.storage.get_task(created.id) is None
