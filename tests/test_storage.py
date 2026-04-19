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
