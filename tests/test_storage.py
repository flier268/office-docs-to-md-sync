import logging
from pathlib import Path

from app.models import SyncEvent, SyncTask, TaskPaths
from app.storage import Storage


def test_storage_round_trip(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    created = storage.create_task(
        SyncTask(
            name="Task A",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst"), output_subdir="md"),
        )
    )

    fetched = storage.get_task(created.id or 0)

    assert fetched is not None
    assert fetched.name == "Task A"


def test_list_tasks_skips_invalid_task_config_without_repeating_log(tmp_path: Path, caplog) -> None:
    storage = Storage(tmp_path / "app.db")
    invalid = storage.create_task(
        SyncTask(
            name="Invalid",
            paths=TaskPaths(source_dir=str(tmp_path / "bad-src"), target_root=str(tmp_path / "bad-dst")),
        )
    )
    valid = storage.create_task(
        SyncTask(
            name="Valid",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst")),
        )
    )
    with storage.connect() as connection:
        connection.execute("UPDATE tasks SET config_json = ? WHERE id = ?", ("{", invalid.id))

    with caplog.at_level(logging.ERROR):
        tasks = storage.list_tasks()
        storage.list_tasks()

    assert [task.id for task in tasks] == [valid.id]
    assert sum(record.message.startswith("Skipping invalid task configuration") for record in caplog.records) == 1


def test_add_event(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    created = storage.create_task(
        SyncTask(
            name="Task B",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst"), output_subdir="md"),
        )
    )

    event = storage.add_event(SyncEvent(task_id=created.id or 0, level="info", message="done"))

    assert event.id is not None
    assert storage.list_events(created.id or 0)[0].message == "done"


def test_set_enabled_and_delete_task(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    created = storage.create_task(
        SyncTask(
            name="Task C",
            paths=TaskPaths(source_dir=str(tmp_path / "src"), target_root=str(tmp_path / "dst"), output_subdir="md"),
        )
    )

    disabled = storage.set_task_enabled(created.id or 0, False)
    deleted = storage.delete_task(created.id or 0)

    assert disabled is not None
    assert disabled.enabled is False
    assert deleted is True
    assert storage.get_task(created.id or 0) is None
