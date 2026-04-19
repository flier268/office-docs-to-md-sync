from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from .models import SyncTask


class GitManager:
    def __init__(self) -> None:
        self._next_push_at: dict[int, datetime] = {}
        self._last_push_at: dict[int, datetime] = {}

    def ensure_repo(self, task: SyncTask) -> Repo:
        repo_dir = task.paths.target_root_path()
        repo_dir.mkdir(parents=True, exist_ok=True)
        try:
            return Repo(repo_dir)
        except (InvalidGitRepositoryError, NoSuchPathError):
            repo = Repo.init(repo_dir, initial_branch=task.git.branch)
            return repo

    def commit_task_changes(self, task: SyncTask) -> str | None:
        if not task.git.enabled or not task.git.auto_commit:
            return None
        repo = self.ensure_repo(task)
        target_dir = task.paths.output_dir_path().resolve()
        working_tree = Path(repo.working_tree_dir or "").resolve()
        if working_tree not in {target_dir, *target_dir.parents}:
            raise ValueError("output directory must be inside the Git working tree")
        relative_target = target_dir.relative_to(working_tree)
        scope = "." if str(relative_target) == "." else str(relative_target)
        scoped_status = repo.git.status("--porcelain", "--", scope)
        if not scoped_status.strip():
            return None
        repo.git.add("--all", "--", scope)
        message = task.git.commit_message_template.format(task_name=task.name)
        commit = repo.index.commit(message)
        if task.git.auto_push:
            self._next_push_at[task.id or 0] = datetime.now(timezone.utc) + timedelta(seconds=task.git.push_delay_seconds)
        return commit.hexsha

    def maybe_push(self, task: SyncTask) -> bool:
        task_id = task.id or 0
        if not task.git.enabled or not task.git.auto_push:
            return False
        next_push = self._next_push_at.get(task_id)
        if not next_push or datetime.now(timezone.utc) < next_push:
            return False
        repo = self.ensure_repo(task)
        try:
            remote = repo.remote(task.git.remote_name)
            remote.push(task.git.branch)
        except (ValueError, GitCommandError):
            raise
        self._next_push_at.pop(task_id, None)
        self._last_push_at[task_id] = datetime.now(timezone.utc)
        return True

    def last_push_at(self, task_id: int) -> datetime | None:
        return self._last_push_at.get(task_id)
