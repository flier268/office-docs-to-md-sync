from pathlib import Path

from app.converter import Converter
from app.git_ops import GitManager
from app.models import SyncTask, TaskFileRules, TaskGitConfig, TaskPaths
from app.storage import Storage
from app.sync_engine import SyncEngine


def create_task(storage: Storage, tmp_path: Path, git_enabled: bool = False, output_subdir: str = "md") -> SyncTask:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return storage.create_task(
        SyncTask(
            name="Task",
            paths=TaskPaths(source_dir=str(source), target_root=str(target), output_subdir=output_subdir, recursive=True),
            file_rules=TaskFileRules(text_extensions=[".md", ".txt"], debounce_seconds=0.1),
            git=TaskGitConfig(enabled=git_enabled, auto_commit=True),
        )
    )


def test_sync_engine_copies_markdown_file(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "123.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "123.md.md"
    assert target_file.read_text(encoding="utf-8") == "hello\n"


def test_sync_engine_commits_inside_target_root(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path, git_enabled=True)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "123.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    assert engine.statuses[task.id or 0].last_error is None
    assert (Path(task.paths.target_root) / ".git").exists()
    assert (Path(task.paths.target_root) / task.paths.output_subdir / "123.md.md").exists()


def test_reload_tasks_clears_queue_on_disable_and_removes_deleted_task(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "queued.md"
    source_file.write_text("queued\n", encoding="utf-8")

    engine.reload_tasks()
    engine.queue_path(task.id or 0, str(source_file))
    storage.set_task_enabled(task.id or 0, False)
    engine.reload_tasks()

    assert (task.id or 0) not in engine.handlers
    assert engine.statuses[task.id or 0].queued_paths == []

    storage.delete_task(task.id or 0)
    engine.reload_tasks()
    engine.remove_task(task.id or 0)

    assert (task.id or 0) not in engine.statuses
