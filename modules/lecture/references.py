from __future__ import annotations

import asyncio
import re
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import HTTPException, UploadFile
from pptx import Presentation

from core.config import data_dir, positive_int

ALLOWED_REFERENCE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}
ALLOWED_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx"}


def _safe_name(name: str | None, fallback_suffix: str) -> str:
    raw = Path(name or f"reference{fallback_suffix}").name
    stem = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", raw).strip(" .")
    return (stem or f"reference{fallback_suffix}")[:160]


async def save_reference_files(uploads: list[UploadFile] | None) -> list[dict]:
    uploads = [upload for upload in (uploads or []) if upload and upload.filename]
    if not uploads:
        return []

    maximum_files = positive_int("MAX_REFERENCE_FILES", 5)
    if len(uploads) > maximum_files:
        raise HTTPException(422, f"참고자료는 최대 {maximum_files}개까지 첨부할 수 있습니다.")

    maximum_total = positive_int("MAX_REFERENCE_UPLOAD_BYTES", 25 * 1024 * 1024)
    maximum_each = positive_int("MAX_REFERENCE_FILE_BYTES", 10 * 1024 * 1024)
    directory = data_dir() / "uploads" / "references" / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    saved: list[dict] = []
    total = 0

    try:
        for upload in uploads:
            content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
            suffix = Path(upload.filename or "").suffix.lower()
            expected_suffix = ALLOWED_REFERENCE_TYPES.get(content_type)
            if suffix not in ALLOWED_SUFFIXES or (expected_suffix and suffix != expected_suffix):
                raise HTTPException(422, "참고자료는 PDF, TXT, Markdown, DOCX, PPTX만 업로드할 수 있습니다.")

            content = bytearray()
            try:
                while chunk := await upload.read(64 * 1024):
                    content.extend(chunk)
                    if len(content) > maximum_each:
                        raise HTTPException(413, f"참고자료 1개는 최대 {maximum_each // (1024 * 1024)}MB입니다.")
                    if total + len(content) > maximum_total:
                        raise HTTPException(413, f"참고자료 전체 용량은 최대 {maximum_total // (1024 * 1024)}MB입니다.")
            finally:
                await upload.close()

            if not content:
                raise HTTPException(422, f"빈 참고자료는 사용할 수 없습니다: {upload.filename}")

            filename = _safe_name(upload.filename, suffix)
            path = directory / f"{uuid4().hex[:10]}_{filename}"
            temporary = path.with_suffix(path.suffix + ".tmp")
            try:
                await asyncio.to_thread(temporary.write_bytes, bytes(content))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

            total += len(content)
            saved.append({
                "name": filename,
                "path": str(path),
                "content_type": content_type or "application/octet-stream",
                "size": len(content),
            })
        return saved
    except BaseException:
        for item in saved:
            Path(item["path"]).unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


def cleanup_reference_files(files: list[dict] | None) -> None:
    parents: set[Path] = set()
    for item in files or []:
        path = Path(str(item.get("path") or ""))
        if path.is_file():
            path.unlink(missing_ok=True)
        if path.parent.name:
            parents.add(path.parent)
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("PDF 참고자료 처리를 위해 pypdf가 필요합니다.") from exc
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages if (page.extract_text() or "").strip())


def _extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml")
    root = ElementTree.fromstring(raw)
    texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    return "\n".join(texts)


def _extract_pptx(path: Path) -> str:
    presentation = Presentation(path)
    chunks: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        texts = []
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                texts.append(text.strip())
        if texts:
            chunks.append(f"[slide {index}]\n" + "\n".join(texts))
    return "\n\n".join(chunks)


def extract_reference_text(item: dict) -> str:
    path = Path(str(item.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"참고자료 파일을 찾을 수 없습니다: {path}")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pptx":
        return _extract_pptx(path)
    raise ValueError(f"지원하지 않는 참고자료 형식입니다: {suffix}")


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text or "")
        if len(token) >= 2
    }


def _chunks(text: str, *, size: int = 2600, overlap: int = 260) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    return [text[start:start + size] for start in range(0, len(text), step)]


def build_reference_context(files: list[dict] | None, *, title: str, topic: str) -> str:
    """Build RAG-style context by chunking every reference and retrieving relevant chunks."""
    if not files:
        return ""

    documents: list[tuple[str, str]] = []
    for item in files:
        text = extract_reference_text(item).strip()
        if text:
            documents.append((str(item.get("name") or Path(item["path"]).name), text))
    if not documents:
        return ""

    chunk_size = positive_int("REFERENCE_RAG_CHUNK_CHARS", 2600)
    overlap = min(
        max(0, positive_int("REFERENCE_RAG_CHUNK_OVERLAP_CHARS", 260)),
        max(0, chunk_size - 1),
    )
    top_k = positive_int("REFERENCE_RAG_TOP_K", 16)
    limit = positive_int("MAX_REFERENCE_CONTEXT_CHARS", 60_000)
    query_terms = _terms(f"{title}\n{topic}")

    ranked: list[tuple[int, int, str, str]] = []
    serial = 0
    for name, text in documents:
        for chunk in _chunks(text, size=chunk_size, overlap=overlap):
            serial += 1
            chunk_terms = _terms(chunk)
            score = len(query_terms & chunk_terms)
            ranked.append((score, -serial, name, chunk))

    # Stable fallback: if lexical overlap is sparse, earlier chunks still rank first.
    ranked.sort(reverse=True)

    selected: list[str] = []
    used = 0
    for _, _, name, chunk in ranked[:top_k]:
        block = f"### {name} (RAG 발췌)\n{chunk}"
        if used + len(block) > limit:
            remaining = limit - used
            if remaining > 200:
                selected.append(block[:remaining])
            break
        selected.append(block)
        used += len(block)
    return "\n\n".join(selected)
