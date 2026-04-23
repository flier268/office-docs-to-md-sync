from pathlib import Path

from git import Repo

from app.git_ops import GitManager, git_pat_env_var_name
from app.models import SyncTask, TaskGitConfig, TaskPaths


def make_task(tmp_path: Path, name: str = "Task API") -> SyncTask:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return SyncTask(
        name=name,
        paths=TaskPaths(source_dir=str(source), target_root=str(target), output_subdir="md"),
        git=TaskGitConfig(enabled=True, auto_push=True),
    )


def test_git_pat_env_var_name_uses_task_name() -> None:
    assert git_pat_env_var_name("Task API") == "Task_API_key"
    assert git_pat_env_var_name(" docs/sync ") == "docs_sync_key"


def test_git_pat_for_task_reads_task_key_env(tmp_path: Path, monkeypatch) -> None:
    task = make_task(tmp_path, name="Task API")
    monkeypatch.setenv("Task_API_key", "pat-token")

    assert GitManager()._pat_for_task(task) == "pat-token"


def test_git_pat_for_task_accepts_uppercase_env(tmp_path: Path, monkeypatch) -> None:
    task = make_task(tmp_path, name="Task API")
    monkeypatch.setenv("TASK_API_KEY", "pat-token")

    assert GitManager()._pat_for_task(task) == "pat-token"


def test_push_environment_sets_askpass_for_pat(tmp_path: Path, monkeypatch) -> None:
    task = make_task(tmp_path)
    repo = Repo.init(Path(task.paths.target_root), initial_branch=task.git.branch)
    monkeypatch.setenv("Task_API_key", "pat-token")

    manager = GitManager()
    with manager._push_environment(task, repo):
        env = repo.git._environment
        askpass = Path(env["GIT_ASKPASS"])
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert askpass.exists()
        assert "pat-token" in askpass.read_text(encoding="utf-8")

    assert repo.git._environment == {}
    assert not askpass.exists()
