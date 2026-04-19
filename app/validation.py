from __future__ import annotations

from pathlib import Path

from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from .models import SyncTask


class TaskValidationError(ValueError):
    """Raised when a task configuration is invalid."""


def validate_task(task: SyncTask) -> None:
    if not task.git.enabled:
        return

    repo_root = task.paths.target_root_path().expanduser().resolve()

    try:
        repo = Repo(repo_root)
    except (InvalidGitRepositoryError, NoSuchPathError):
        repo = None

    if task.git.auto_push and repo is not None:
        if task.git.remote_name not in [remote.name for remote in repo.remotes]:
            raise TaskValidationError(f"Git remote '{task.git.remote_name}' does not exist in target root.")
        branch_names = [head.name for head in repo.heads]
        if task.git.branch not in branch_names:
            raise TaskValidationError(f"Git branch '{task.git.branch}' does not exist in target root.")
