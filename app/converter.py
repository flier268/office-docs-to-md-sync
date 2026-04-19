from __future__ import annotations

import warnings
from pathlib import Path

from .models import SyncTask


class Converter:
    def __init__(self) -> None:
        self._engine = None

    def is_supported(self, task: SyncTask, path: Path) -> bool:
        ext = path.suffix.lower()
        return ext in task.file_rules.office_extensions or ext in task.file_rules.text_extensions

    def target_path_for(self, task: SyncTask, source_path: Path) -> Path:
        relative = source_path.relative_to(task.paths.source_path())
        return task.paths.output_dir_path() / relative.with_suffix(".md")

    def convert_path(self, task: SyncTask, source_path: Path) -> str:
        ext = source_path.suffix.lower()
        if ext in task.file_rules.text_extensions:
            text = source_path.read_text(encoding="utf-8", errors="ignore")
            return text
        if self._engine is None:
            warnings.filterwarnings(
                "ignore",
                message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
                category=RuntimeWarning,
            )
            from markitdown import MarkItDown

            self._engine = MarkItDown()
        result = self._engine.convert(str(source_path))
        return result.text_content
