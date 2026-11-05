from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import re
import warnings
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import markitdown_tweaks as _markitdown_tweaks  # registers magika stub before markitdown import
from .models import SyncTask

try:
    from markitdown import MarkItDown
except ModuleNotFoundError:  # pragma: no cover - depends on installed extras/build output
    MarkItDown = None

IMAGE_DIR_NAME = "references"

_MIME_TO_EXT = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "gif": ".gif",
    "webp": ".webp",
    "bmp": ".bmp",
    "svg+xml": ".svg",
    "svg": ".svg",
    "x-icon": ".ico",
    "tiff": ".tiff",
    "tif": ".tiff",
}

_DATA_URI_RE = re.compile(
    r"(?P<prefix>!\[[^\]]*\]\()data:image/(?P<mime>[^;,\s)]+)(?:;base64)?,(?P<data>[A-Za-z0-9+/=\s]+)(?P<suffix>\))"
    r"|(?P<html_prefix><img\b[^>]*?\bsrc=[\"'])data:image/(?P<html_mime>[^;,\s\"']+)(?:;base64)?,(?P<html_data>[A-Za-z0-9+/=\s]+)(?P<html_suffix>[\"'][^>]*>)",
    re.IGNORECASE,
)

_OFFICE_MEDIA_PREFIXES = ("word/media/", "ppt/media/", "xl/media/")
_OFFICE_ZIP_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".xlsm"}


@dataclass(frozen=True)
class ConversionResult:
    markdown: str
    image_relpaths: tuple[str, ...] = ()


class Converter:
    def __init__(self) -> None:
        self._engine = None

    def is_supported(self, task: SyncTask, path: Path) -> bool:
        ext = path.suffix.lower()
        return ext in task.file_rules.office_extensions or ext in task.file_rules.text_extensions

    def target_path_for(self, task: SyncTask, source_path: Path) -> Path:
        relative = source_path.relative_to(task.paths.source_path())
        return task.paths.output_dir_path() / relative.parent / f"{relative.name}.md"

    def convert_path(self, task: SyncTask, source_path: Path, target_path: Path | None = None) -> ConversionResult:
        ext = source_path.suffix.lower()
        if ext in task.file_rules.text_extensions:
            return ConversionResult(source_path.read_text(encoding="utf-8", errors="ignore"))
        if MarkItDown is None:
            raise RuntimeError("MarkItDown dependency is unavailable in this build")
        if self._engine is None:
            warnings.filterwarnings(
                "ignore",
                message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
                category=RuntimeWarning,
            )
            self._engine = MarkItDown()
        if target_path is None:
            raise ValueError("Office conversion requires target_path to store images")
        markdown = self._convert_office(source_path)
        return self.materialize_images(source_path, markdown, target_path)

    def _convert_office(self, source_path: Path) -> str:
        convert = self._engine.convert
        kwargs = {"keep_data_uris": True} if _accepts_keep_data_uris(convert) else {}
        result = convert(str(source_path), **kwargs)
        return result.text_content

    def materialize_images(self, source_path: Path, markdown: str, target_path: Path) -> ConversionResult:
        markdown, extracted = self._extract_data_uri_images(markdown, target_path)
        markdown, extras = self._append_office_media_images(source_path, markdown, target_path, extracted)
        return ConversionResult(markdown, tuple(extracted + extras))

    def _extract_data_uri_images(self, markdown: str, target_path: Path) -> tuple[str, list[str]]:
        written: list[str] = []

        def replace(match: re.Match[str]) -> str:
            if match.group("prefix") is not None:
                mime = match.group("mime")
                data = match.group("data")
                prefix = match.group("prefix")
                suffix = match.group("suffix")
            else:
                mime = match.group("html_mime")
                data = match.group("html_data")
                prefix = match.group("html_prefix")
                suffix = match.group("html_suffix")
            try:
                payload = base64.b64decode(re.sub(r"\s+", "", data), validate=True)
            except (binascii.Error, ValueError):
                return match.group(0)
            relpath = self._write_image_bytes(target_path, mime, payload)
            written.append(relpath)
            return f"{prefix}{relpath}{suffix}"

        rewritten = _DATA_URI_RE.sub(replace, markdown)
        return rewritten, written

    def _append_office_media_images(
        self,
        source_path: Path,
        markdown: str,
        target_path: Path,
        already_linked: Sequence[str] = (),
    ) -> tuple[str, list[str]]:
        linked = set(already_linked)
        if source_path.suffix.lower() not in _OFFICE_ZIP_EXTENSIONS:
            return markdown, []
        if not zipfile.is_zipfile(source_path):
            return markdown, []
        extras: list[str] = []
        with zipfile.ZipFile(source_path) as archive:
            for name in archive.namelist():
                lowered = name.lower()
                if not any(lowered.startswith(prefix) for prefix in _OFFICE_MEDIA_PREFIXES):
                    continue
                payload = archive.read(name)
                if not payload:
                    continue
                ext = Path(name).suffix.lower() or ".bin"
                relpath = self._write_image_file(target_path, ext, payload)
                if relpath in linked:
                    continue
                linked.add(relpath)
                extras.append(relpath)
        if not extras:
            return markdown, []
        links = "\n".join(f"![]({relpath})" for relpath in extras)
        separator = "" if markdown.endswith("\n") or not markdown else "\n"
        return markdown + separator + links + "\n", extras

    def _write_image_bytes(self, target_path: Path, mime: str, payload: bytes) -> str:
        ext = _MIME_TO_EXT.get(mime.lower(), f".{mime.lower().split('+')[0]}")
        return self._write_image_file(target_path, ext, payload)

    def _write_image_file(self, target_path: Path, ext: str, payload: bytes) -> str:
        if not ext.startswith("."):
            ext = f".{ext}"
        filename = f"{hashlib.sha256(payload).hexdigest()}{ext.lower()}"
        image_dir = target_path.parent / IMAGE_DIR_NAME
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / filename).write_bytes(payload)
        return f"{IMAGE_DIR_NAME}/{filename}"


def _accepts_keep_data_uris(convert: object) -> bool:
    try:
        signature = inspect.signature(convert)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters
    if "keep_data_uris" in parameters:
        return True
    return any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
