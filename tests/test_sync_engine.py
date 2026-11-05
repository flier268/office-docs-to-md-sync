import hashlib
import json
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.converter import ConversionResult, Converter
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


def test_record_error_survives_readonly_event_database(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())

    def fail_to_add_event(*_args, **_kwargs):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(storage, "add_event", fail_to_add_event)

    engine._record_error(task.id or 0, "conversion failed")

    assert engine.statuses[task.id or 0].last_error == "conversion failed"


def test_sync_engine_uses_apscheduler_for_processing_and_scans(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    engine = SyncEngine(storage, Converter(), GitManager())

    engine.reload_tasks()

    process_job = engine.scheduler.get_job("process-task-queues")
    scan_job = engine.scheduler.get_job(f"scan-task-{task.id}")

    assert isinstance(engine.scheduler, BackgroundScheduler)
    assert isinstance(process_job.trigger, IntervalTrigger)
    assert process_job.trigger.interval == timedelta(seconds=0.5)
    assert process_job.max_instances == 1
    assert process_job.coalesce is True
    assert process_job.misfire_grace_time is None
    assert isinstance(scan_job.trigger, IntervalTrigger)
    assert scan_job.trigger.interval == timedelta(seconds=5)
    assert scan_job.max_instances == 1
    assert scan_job.coalesce is True
    assert scan_job.misfire_grace_time is None


def test_shutdown_does_not_wait_for_running_scheduler_job(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    engine = SyncEngine(storage, Converter(), GitManager())
    started = threading.Event()
    release = threading.Event()

    def blocking_job() -> None:
        started.set()
        release.wait(timeout=5)

    engine.scheduler.remove_all_jobs()
    engine.scheduler.add_job(blocking_job, "date", run_date=datetime.now(timezone.utc))
    engine.start()
    shutdown_thread = threading.Thread(target=engine.shutdown)
    try:
        assert started.wait(timeout=2)
        shutdown_thread.start()
        shutdown_thread.join(timeout=0.5)
        assert not shutdown_thread.is_alive()
    finally:
        release.set()
        if shutdown_thread.ident is not None:
            shutdown_thread.join(timeout=2)
        if engine.scheduler.running:
            engine.shutdown()


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


def test_file_event_does_not_reconvert_unchanged_source(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    converter = Converter()
    engine = SyncEngine(storage, converter, GitManager())
    source_file = Path(task.paths.source_dir) / "tracked.md"
    source_file.write_text("hello\n", encoding="utf-8")

    engine._scan_task(task)
    engine._process_task_queue(task)
    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "tracked.md.md"
    original_mtime = target_file.stat().st_mtime_ns

    def fail_conversion(*_args, **_kwargs):
        raise AssertionError("unchanged source must not be converted again")

    monkeypatch.setattr(converter, "convert_path", fail_conversion)
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    assert target_file.read_text(encoding="utf-8") == "hello\n"
    assert target_file.stat().st_mtime_ns == original_mtime
    assert engine.statuses[task.id or 0].last_error is None


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


def _write_sha256_image(target_path: Path, payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    image_dir = target_path.parent / "references"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / f"{digest}.png"
    image_path.write_bytes(payload)
    return image_path


def test_sync_engine_extracts_images_and_removes_them_with_source(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    converter = Converter()
    engine = SyncEngine(storage, converter, GitManager())
    source_file = Path(task.paths.source_dir) / "report.txt"
    source_file.write_text("office-like\n", encoding="utf-8")
    payload = b"png-bytes"

    def fake_convert(task_arg, source_path, target_path=None):
        assert target_path is not None
        image_path = _write_sha256_image(target_path, payload)
        rel = f"references/{image_path.name}"
        return ConversionResult(f"![photo]({rel})\n", (rel,))

    monkeypatch.setattr(converter, "convert_path", fake_convert)
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "report.txt.md"
    image_file = _write_sha256_image(target_file, payload)
    digest = image_file.stem
    manifest_path = Path(task.paths.target_root) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["tasks"][str(task.id)]["files"]["report.txt"]

    assert target_file.read_text(encoding="utf-8") == f"![photo](references/{digest}.png)\n"
    assert image_file.exists()
    assert entry["image_relpaths"] == [f"{task.paths.output_subdir}/references/{digest}.png"]

    source_file.unlink()
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    assert not target_file.exists()
    assert not image_file.exists()


def test_sync_engine_adds_overwrites_and_removes_images_when_source_updates(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    converter = Converter()
    engine = SyncEngine(storage, converter, GitManager())
    source_file = Path(task.paths.source_dir) / "report.txt"
    source_file.write_text("v1\n", encoding="utf-8")
    kept = b"kept-image"
    removed = b"removed-image"
    added = b"added-image"
    overwritten = b"overwritten-image"

    def fake_convert(task_arg, source_path, target_path=None):
        assert target_path is not None
        version = source_path.read_text(encoding="utf-8")
        payloads = [kept, removed] if version == "v1\n" else [kept, added, overwritten]
        links = []
        rels = []
        for payload in payloads:
            image_path = _write_sha256_image(target_path, payload)
            rel = f"references/{image_path.name}"
            links.append(f"![]({rel})")
            rels.append(rel)
        return ConversionResult("\n".join(links) + "\n", tuple(rels))

    monkeypatch.setattr(converter, "convert_path", fake_convert)
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    target_file = Path(task.paths.target_root) / task.paths.output_subdir / "report.txt.md"
    kept_path = _write_sha256_image(target_file, kept)
    removed_path = target_file.parent / "references" / f"{hashlib.sha256(removed).hexdigest()}.png"
    added_path = target_file.parent / "references" / f"{hashlib.sha256(added).hexdigest()}.png"
    overwritten_path = target_file.parent / "references" / f"{hashlib.sha256(overwritten).hexdigest()}.png"
    original_kept_mtime = kept_path.stat().st_mtime_ns

    assert kept_path.exists()
    assert removed_path.exists()
    assert not added_path.exists()

    source_file.write_text("v2\n", encoding="utf-8")
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    assert kept_path.exists()
    assert kept_path.read_bytes() == kept
    assert kept_path.stat().st_mtime_ns >= original_kept_mtime
    assert not removed_path.exists()
    assert added_path.exists()
    assert added_path.read_bytes() == added
    assert overwritten_path.exists()
    assert overwritten_path.read_bytes() == overwritten
    markdown = target_file.read_text(encoding="utf-8")
    assert kept_path.name in markdown
    assert added_path.name in markdown
    assert overwritten_path.name in markdown
    assert removed_path.name not in markdown


def test_shared_image_is_kept_until_last_document_stops_using_it(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    converter = Converter()
    engine = SyncEngine(storage, converter, GitManager())
    first = Path(task.paths.source_dir) / "first.txt"
    second = Path(task.paths.source_dir) / "second.txt"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    payload = b"shared-image"

    def fake_convert(task_arg, source_path, target_path=None):
        assert target_path is not None
        image_path = _write_sha256_image(target_path, payload)
        rel = f"references/{image_path.name}"
        return ConversionResult(f"![]({rel})\n", (rel,))

    monkeypatch.setattr(converter, "convert_path", fake_convert)
    for source_file in (first, second):
        engine.queue_path(task.id or 0, str(source_file))
        engine.queued_paths[task.id or 0][source_file] = 0
        engine._process_task_queue(task)

    target_root = Path(task.paths.target_root) / task.paths.output_subdir
    image_file = target_root / "references" / f"{hashlib.sha256(payload).hexdigest()}.png"
    assert image_file.exists()
    assert (target_root / "first.txt.md").exists()
    assert (target_root / "second.txt.md").exists()

    first.unlink()
    engine.queue_path(task.id or 0, str(first))
    engine.queued_paths[task.id or 0][first] = 0
    engine._process_task_queue(task)

    assert not (target_root / "first.txt.md").exists()
    assert (target_root / "second.txt.md").exists()
    assert image_file.exists()
    assert image_file.read_bytes() == payload

    second.unlink()
    engine.queue_path(task.id or 0, str(second))
    engine.queued_paths[task.id or 0][second] = 0
    engine._process_task_queue(task)

    assert not (target_root / "second.txt.md").exists()
    assert not image_file.exists()


def test_manifest_tracks_only_converter_owned_images(tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "app.db")
    task = create_task(storage, tmp_path)
    converter = Converter()
    engine = SyncEngine(storage, converter, GitManager())
    source_file = Path(task.paths.source_dir) / "report.txt"
    source_file.write_text("v1\n", encoding="utf-8")
    payload = b"owned-image"

    def fake_convert(task_arg, source_path, target_path=None):
        assert target_path is not None
        image_path = _write_sha256_image(target_path, payload)
        rel = f"references/{image_path.name}"
        return ConversionResult(f"see references/not-managed.png\n![]({rel})\n", (rel,))

    monkeypatch.setattr(converter, "convert_path", fake_convert)
    engine.queue_path(task.id or 0, str(source_file))
    engine.queued_paths[task.id or 0][source_file] = 0
    engine._process_task_queue(task)

    manifest = json.loads((Path(task.paths.target_root) / MANIFEST_NAME).read_text(encoding="utf-8"))
    entry = manifest["tasks"][str(task.id)]["files"]["report.txt"]
    digest = hashlib.sha256(payload).hexdigest()
    assert entry["image_relpaths"] == [f"{task.paths.output_subdir}/references/{digest}.png"]


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
