from pathlib import Path

import pytest

import app.converter as converter_module
from app.converter import Converter
from app.models import SyncTask, TaskFileRules, TaskGitConfig, TaskPaths


def sample_task(tmp_path: Path) -> SyncTask:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return SyncTask(
        name="Sample",
        paths=TaskPaths(source_dir=str(source), target_root=str(target), output_subdir="md", recursive=True),
        file_rules=TaskFileRules(
            office_extensions=[".docx"],
            text_extensions=[".txt", ".md"],
            debounce_seconds=0.1,
        ),
        git=TaskGitConfig(),
    )


def test_target_path_for(tmp_path: Path) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "nested" / "report.docx"
    source_path.parent.mkdir()
    source_path.write_text("placeholder", encoding="utf-8")
    converter = Converter()

    target = converter.target_path_for(task, source_path)

    assert target == Path(task.paths.target_root) / "md" / "nested" / "report.md"


def test_convert_text_file_to_markdown(tmp_path: Path) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "notes.txt"
    source_path.write_text("hello\nworld\n", encoding="utf-8")
    converter = Converter()

    result = converter.convert_path(task, source_path)

    assert result == "hello\nworld\n"


def test_convert_office_file_requires_markitdown_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "report.docx"
    source_path.write_text("placeholder", encoding="utf-8")
    converter = Converter()
    monkeypatch.setattr(converter_module, "MarkItDown", None)

    with pytest.raises(RuntimeError, match="MarkItDown dependency is unavailable in this build"):
        converter.convert_path(task, source_path)
