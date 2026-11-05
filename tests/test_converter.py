import base64
import hashlib
import re
import zipfile
from pathlib import Path

import pytest

import app.converter as converter_module
from app.converter import IMAGE_DIR_NAME, Converter
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

    assert target == Path(task.paths.target_root) / "md" / "nested" / "report.docx.md"


def test_target_path_for_keeps_source_extension_to_avoid_collisions(tmp_path: Path) -> None:
    task = sample_task(tmp_path)
    converter = Converter()
    docx_path = Path(task.paths.source_dir) / "nested" / "A.docx"
    xlsx_path = Path(task.paths.source_dir) / "nested" / "A.xlsx"
    docx_path.parent.mkdir()
    docx_path.write_text("placeholder", encoding="utf-8")
    xlsx_path.write_text("placeholder", encoding="utf-8")

    docx_target = converter.target_path_for(task, docx_path)
    xlsx_target = converter.target_path_for(task, xlsx_path)

    assert docx_target.name == "A.docx.md"
    assert xlsx_target.name == "A.xlsx.md"
    assert docx_target != xlsx_target


def test_convert_text_file_to_markdown(tmp_path: Path) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "notes.txt"
    source_path.write_text("hello\nworld\n", encoding="utf-8")
    converter = Converter()

    result = converter.convert_path(task, source_path)

    assert result.markdown == "hello\nworld\n"
    assert result.image_relpaths == ()


def test_convert_office_file_requires_markitdown_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "report.docx"
    source_path.write_text("placeholder", encoding="utf-8")
    converter = Converter()
    monkeypatch.setattr(converter_module, "MarkItDown", None)

    with pytest.raises(RuntimeError, match="MarkItDown dependency is unavailable in this build"):
        converter.convert_path(task, source_path)


def test_office_conversion_requires_target_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyMarkItDown:
        def convert(self, path: str, keep_data_uris: bool = False):
            raise AssertionError("conversion must not start without target_path")

    monkeypatch.setattr(converter_module, "MarkItDown", DummyMarkItDown)
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "report.docx"
    source_path.write_text("placeholder", encoding="utf-8")
    converter = Converter()

    with pytest.raises(ValueError, match="target_path"):
        converter.convert_path(task, source_path)


def test_extract_data_uri_images_writes_sha256_files_and_relative_links(tmp_path: Path) -> None:
    converter = Converter()
    source_path = tmp_path / "notes.txt"
    target_path = tmp_path / "md" / "report.docx.md"
    payload = b"\x89PNG\r\n\x1a\n" + b"fake-png"
    encoded = base64.b64encode(payload).decode("ascii")
    markdown = f"Intro\n\n![chart](data:image/png;base64,{encoded})\n"
    digest = hashlib.sha256(payload).hexdigest()
    relpath = f"{IMAGE_DIR_NAME}/{digest}.png"

    result = converter.materialize_images(source_path, markdown, target_path)

    assert result.image_relpaths == (relpath,)
    image_path = target_path.parent / relpath
    assert image_path.read_bytes() == payload
    assert result.markdown == f"Intro\n\n![chart]({relpath})\n"

    again = converter.materialize_images(source_path, markdown, target_path)
    assert again.image_relpaths == result.image_relpaths
    assert image_path.read_bytes() == payload
    assert again.markdown == result.markdown


def test_office_zip_media_is_appended_when_markdown_has_no_embedded_images(tmp_path: Path) -> None:
    task = sample_task(tmp_path)
    source_path = Path(task.paths.source_dir) / "report.docx"
    png = b"\x89PNG\r\n\x1a\nimage"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("word/document.xml", "<w:document />")
        archive.writestr("word/media/image1.png", png)
    target_path = tmp_path / "md" / "report.docx.md"
    converter = Converter()

    result = converter.materialize_images(source_path, "body\n", target_path)

    match = re.search(rf"!\[\]\(({IMAGE_DIR_NAME}/[0-9a-f]{{64}}\.png)\)", result.markdown)
    assert match is not None
    image_path = target_path.parent / match.group(1)
    assert image_path.read_bytes() == png
    assert result.markdown.startswith("body\n")
    assert result.image_relpaths == (match.group(1),)


def test_invalid_data_uri_is_left_in_place_and_does_not_abort_other_images(tmp_path: Path) -> None:
    converter = Converter()
    source_path = tmp_path / "notes.txt"
    target_path = tmp_path / "md" / "report.docx.md"
    good = b"good-png"
    encoded = base64.b64encode(good).decode("ascii")
    markdown = f"![bad](data:image/png;base64,@@@not-base64@@@)\n![good](data:image/png;base64,{encoded})\n"

    result = converter.materialize_images(source_path, markdown, target_path)

    digest = hashlib.sha256(good).hexdigest()
    relpath = f"{IMAGE_DIR_NAME}/{digest}.png"
    assert result.image_relpaths == (relpath,)
    assert "@@@not-base64@@@" in result.markdown
    assert f"![good]({relpath})" in result.markdown
    assert (target_path.parent / relpath).read_bytes() == good


def test_zip_media_is_appended_for_hashes_not_already_linked(tmp_path: Path) -> None:
    converter = Converter()
    source_path = tmp_path / "report.docx"
    linked = b"already-linked"
    extra = b"zip-only"
    encoded = base64.b64encode(linked).decode("ascii")
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("word/document.xml", "<w:document />")
        archive.writestr("word/media/same.png", linked)
        archive.writestr("word/media/extra.png", extra)
    target_path = tmp_path / "md" / "report.docx.md"
    markdown = f"![chart](data:image/png;base64,{encoded})\n"

    result = converter.materialize_images(source_path, markdown, target_path)

    linked_rel = f"{IMAGE_DIR_NAME}/{hashlib.sha256(linked).hexdigest()}.png"
    extra_rel = f"{IMAGE_DIR_NAME}/{hashlib.sha256(extra).hexdigest()}.png"
    assert result.image_relpaths == (linked_rel, extra_rel)
    assert f"![chart]({linked_rel})" in result.markdown
    assert result.markdown.count(linked_rel) == 1
    assert f"![]({extra_rel})" in result.markdown
    assert (target_path.parent / extra_rel).read_bytes() == extra


def test_keep_data_uris_is_passed_only_when_convert_accepts_it() -> None:
    from app.converter import _accepts_keep_data_uris

    def legacy(path: str):
        return path

    def modern(path: str, keep_data_uris: bool = False):
        return path

    def kwargs_only(path: str, **options):
        return path

    assert _accepts_keep_data_uris(legacy) is False
    assert _accepts_keep_data_uris(modern) is True
    assert _accepts_keep_data_uris(kwargs_only) is True
