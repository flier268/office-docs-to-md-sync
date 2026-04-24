import json
import tempfile
from pathlib import Path

from app.converter import Converter
from app.git_ops import GitManager
from app.models import SyncTask, TaskFileRules, TaskGitConfig, TaskPaths
from app.storage import Storage
from app.sync_engine import MANIFEST_NAME, SyncEngine


def create_task(storage: Storage, tmp_path: Path, git_enabled: bool = False, output_subdir: str = "md") -> SyncTask:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return storage.create_task(
        SyncTask(
            name="Task",
            paths=TaskPaths(source_dir=str(source), target_root=str(target), output_subdir=output_subdir, recursive=True),
            file_rules=TaskFileRules(text_extensions=[".md", ".txt"], debounce_seconds=0.1, scan_interval_seconds=5.0),
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
    assert (Path(task.paths.target_root) / MANIFEST_NAME).exists()


def test_sync_engine_git_commit_includes_manifest(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path, git_enabled=True)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "123.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    repo = engine.git_manager.ensure_repo(task)
    committed_files = repo.git.show("--name-only", "--pretty=format:", "HEAD").splitlines()

    assert task.paths.output_subdir + "/123.md.md" in committed_files
    assert MANIFEST_NAME in committed_files


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


def test_periodic_scan_detects_new_file_and_updates_manifest(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "new.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "new.md.md"
    manifest_path = Path(task.paths.target_root) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert target_file.read_text(encoding="utf-8") == "hello\n"
    assert manifest["tasks"][str(task.id)]["files"]["new.md"]["target_relpath"] == "md/new.md.md"


def test_manifest_temp_file_is_created_outside_target_root(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())

    engine._write_manifest(task, {"tasks": {}})

    temp_entries = list(Path(task.paths.target_root).glob("tmp*"))
    manifest_path = Path(task.paths.target_root) / MANIFEST_NAME

    assert manifest_path.exists()
    assert temp_entries == []
    assert manifest_path.parent != Path(tempfile.gettempdir())


def test_periodic_scan_uses_hash_to_detect_changes(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "tracked.md"
    source_file.write_text("v1\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)
    source_file.write_text("v2\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "tracked.md.md"
    assert target_file.read_text(encoding="utf-8") == "v2\n"


def test_periodic_scan_removes_deleted_output_and_manifest_entry(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "gone.md"
    source_file.write_text("bye\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)
    source_file.unlink()

    engine._scan_task(task)
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "gone.md.md"
    manifest_path = Path(task.paths.target_root) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not target_file.exists()
    assert "gone.md" not in manifest["tasks"].get(str(task.id), {}).get("files", {})


def test_remove_task_clears_manifest_section(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())
    source_file = Path(task.paths.source_dir) / "tracked.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)
    engine.task_configs[task.id or 0] = task
    engine.remove_task(task.id or 0)

    manifest_path = Path(task.paths.target_root) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert str(task.id) not in manifest["tasks"]
