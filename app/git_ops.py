from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from .models import SyncTask
from .sync_state import MANIFEST_NAME


def git_pat_env_var_name(task_name: str) -> str:
    normalized = re.sub(r"\W+", "_", task_name.strip()).strip("_")
    return f"{normalized or 'TASK'}_key"


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
        manifest_path = working_tree / MANIFEST_NAME
        manifest_scope = manifest_path.relative_to(working_tree).as_posix()
        scoped_status = repo.git.status("--porcelain", "--", scope, manifest_scope)
        if not scoped_status.strip():
            return None
        repo.git.add("--all", "--", scope, manifest_scope)
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
        self.push(task)
        self._next_push_at.pop(task_id, None)
        self._last_push_at[task_id] = datetime.now(timezone.utc)
        return True

    def push(self, task: SyncTask) -> None:
        repo = self.ensure_repo(task)
        try:
            remote = repo.remote(task.git.remote_name)
            with self._push_environment(task, repo):
                remote.push(task.git.branch)
        except (ValueError, GitCommandError):
            raise

    def last_push_at(self, task_id: int) -> datetime | None:
        return self._last_push_at.get(task_id)

    @contextmanager
    def _push_environment(self, task: SyncTask, repo: Repo) -> Iterator[None]:
        token = self._pat_for_task(task)
        if not token:
            yield
            return

        askpass_path = self._write_askpass_script(token)
        try:
            with repo.git.custom_environment(GIT_ASKPASS=str(askpass_path), GIT_TERMINAL_PROMPT="0"):
                yield
        finally:
            askpass_path.unlink(missing_ok=True)

    def _pat_for_task(self, task: SyncTask) -> str | None:
        for env_var in self._pat_env_var_candidates(task):
            token = os.getenv(env_var)
            if token:
                return token
        return None

    def _pat_env_var_candidates(self, task: SyncTask) -> list[str]:
        primary = git_pat_env_var_name(task.name)
        candidates = [primary, primary.upper()]
        raw = f"{task.name}_key"
        if raw not in candidates:
            candidates.append(raw)
        return candidates

    def _write_askpass_script(self, token: str) -> Path:
        fd, name = tempfile.mkstemp(prefix="office-docs-git-askpass-", suffix=".sh")
        path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
            handle.write('case "$1" in\n')
            handle.write('  *Username*) printf "%s\\n" "x-access-token" ;;\n')
            handle.write(f'  *) printf "%s\\n" "{self._shell_double_quote(token)}" ;;\n')
            handle.write("esac\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    @staticmethod
    def _shell_double_quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
