"""Reference document compatibility facade."""

from pathlib import Path

from pptx import Presentation

from core.openai.client import get_client
from core.openai.usage import embeddings_create
from modules.lecture import reference_files as _files
from modules.lecture.reference_rag import (
    build_reference_context as _build_reference_context_impl,
)

ALLOWED_REFERENCE_TYPES = _files.ALLOWED_REFERENCE_TYPES
ALLOWED_SUFFIXES = _files.ALLOWED_SUFFIXES

save_reference_files = _files.save_reference_files
cleanup_reference_files = _files.cleanup_reference_files

_validate_pptx_archive_size = _files._validate_pptx_archive_size


def _extract_pptx(path: Path) -> str:
    _validate_pptx_archive_size(path)

    presentation = Presentation(path)
    chunks: list[str] = []

    for index, slide in enumerate(presentation.slides, start=1):
        texts = []

        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                texts.append(text.strip())

        if texts:
            chunks.append(
                f"[slide {index}]\n" + "\n".join(texts)
            )

    return "\n\n".join(chunks)


def extract_reference_text(item: dict) -> str:
    path = Path(str(item.get("path") or ""))

    if path.suffix.lower() == ".pptx":
        if not path.is_file():
            raise FileNotFoundError(
                f"참고자료 파일을 찾을 수 없습니다: {path}"
            )
        return _extract_pptx(path)

    return _files.extract_reference_text(item)


async def build_reference_context(
    files: list[dict] | None,
    *,
    title: str,
    topic: str,
    api_key: str,
    user_id: int,
    lecture_id: int | None = None,
) -> str:
    return await _build_reference_context_impl(
        files,
        title=title,
        topic=topic,
        api_key=api_key,
        user_id=user_id,
        lecture_id=lecture_id,
        get_client_fn=get_client,
        embeddings_create_fn=embeddings_create,
        extract_reference_text_fn=extract_reference_text,
    )


__all__ = [
    "ALLOWED_REFERENCE_TYPES",
    "ALLOWED_SUFFIXES",
    "save_reference_files",
    "cleanup_reference_files",
    "extract_reference_text",
    "build_reference_context",
]
