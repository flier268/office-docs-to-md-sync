from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


DEFAULT_OFFICE_EXTENSIONS = [".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".pdf"]
DEFAULT_TEXT_EXTENSIONS = [".txt", ".md", ".markdown", ".csv", ".tsv", ".log"]


def normalize_extensions(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        ext = value.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        normalized.append(ext)
    return sorted(dict.fromkeys(normalized))


class TaskPaths(BaseModel):
    source_dir: str
    target_root: str
    output_subdir: str = "md"
    recursive: bool = True

    @field_validator("source_dir", "target_root")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return str(Path(value).expanduser())

    @field_validator("output_subdir")
    @classmethod
    def validate_output_subdir(cls, value: str) -> str:
        normalized = value.strip().strip("/\\")
        if not normalized:
            raise ValueError("output_subdir must not be empty")
        if Path(normalized).is_absolute():
            raise ValueError("output_subdir must be relative")
        if ".." in Path(normalized).parts:
            raise ValueError("output_subdir must not traverse parent directories")
        if normalized == ".git" or normalized.startswith(".git/"):
            raise ValueError("output_subdir must not use the .git directory")
        return normalized

    def source_path(self) -> Path:
        return Path(self.source_dir)

    def target_root_path(self) -> Path:
        return Path(self.target_root)

    def output_dir_path(self) -> Path:
        return self.target_root_path() / self.output_subdir


class TaskFileRules(BaseModel):
    office_extensions: list[str] = Field(default_factory=lambda: DEFAULT_OFFICE_EXTENSIONS.copy())
    text_extensions: list[str] = Field(default_factory=lambda: DEFAULT_TEXT_EXTENSIONS.copy())
    debounce_seconds: float = Field(default=1.5, ge=0.1, le=30.0)

    @field_validator("office_extensions", "text_extensions")
    @classmethod
    def validate_extensions(cls, value: list[str]) -> list[str]:
        return normalize_extensions(value)


class TaskGitConfig(BaseModel):
    enabled: bool = False
    branch: str = "main"
    remote_name: str = "origin"
    auto_commit: bool = True
    auto_push: bool = False
    push_delay_seconds: float = Field(default=10.0, ge=1.0, le=3600.0)
    commit_message_template: str = "auto: sync {task_name}"


class SyncTask(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    paths: TaskPaths
    file_rules: TaskFileRules = Field(default_factory=TaskFileRules)
    git: TaskGitConfig = Field(default_factory=TaskGitConfig)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SyncEvent(BaseModel):
    id: int | None = None
    task_id: int
    level: Literal["info", "warning", "error"]
    message: str
    created_at: datetime | None = None


class TaskStatus(BaseModel):
    task_id: int
    running: bool
    last_run_at: datetime | None = None
    last_push_at: datetime | None = None
    queued_paths: list[str] = Field(default_factory=list)
    last_error: str | None = None


class SystemStatus(BaseModel):
    running_tasks: int
    total_tasks: int
    statuses: list[TaskStatus]
