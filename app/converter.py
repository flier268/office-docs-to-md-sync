from __future__ import annotations

import warnings
from pathlib import Path

from .models import SyncTask

try:
    from markitdown_no_magika import MarkItDown
except ModuleNotFoundError:  # pragma: no cover - depends on installed extras/build output
    MarkItDown = None


class Converter:
    def __init__(self) -> None:
        self._engine = None

    def is_supported(self, task: SyncTask, path: Path) -> bool:
        ext = path.suffix.lower()
        return ext in task.file_rules.office_extensions or ext in task.file_rules.text_extensions

    def target_path_for(self, task: SyncTask, source_path: Path) -> Path:
        relative = source_path.relative_to(task.paths.source_path())
        return task.paths.output_dir_path() / relative.parent / f"{relative.name}.md"

    def convert_path(self, task: SyncTask, source_path: Path) -> str:
        ext = source_path.suffix.lower()
        if ext in task.file_rules.text_extensions:
            text = source_path.read_text(encoding="utf-8", errors="ignore")
            return text
        if MarkItDown is None:
            raise RuntimeError("MarkItDown dependency is unavailable in this build")
        if self._engine is None:
            warnings.filterwarnings(
                "ignore",
                message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
                category=RuntimeWarning,
            )
            self._engine = MarkItDown()
        result = self._engine.convert(str(source_path))
        return result.text_content
