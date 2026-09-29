from __future__ import annotations

import asyncio
import math
import os
import re
from pathlib import Path

from core.config import positive_int
from core.openai.client import get_client
from core.openai.usage import embeddings_create
from modules.lecture.reference_files import extract_reference_text


def _chunks(text: str, *, size: int = 2600, overlap: int = 260) -> list[str]:
    """Split references on document boundaries before falling back to a sliding window.

    Embeddings work better when a chunk starts at a paragraph/slide boundary instead
    of an arbitrary Unicode character.  Oversized paragraphs still use overlap so
    context is not lost around a hard size boundary.
    """
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    result: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current:
            result.append(current)
            current = ""

    for paragraph in paragraphs:
        if len(paragraph) <= size:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= size:
                current = candidate
            else:
                flush_current()
                current = paragraph
            continue

        flush_current()
        step = max(1, size - overlap)
        for start in range(0, len(paragraph), step):
            piece = paragraph[start : start + size].strip()
            if piece:
                result.append(piece)
            if start + size >= len(paragraph):
                break

    flush_current()
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


async def build_reference_context(
    files: list[dict] | None,
    *,
    title: str,
    topic: str,
    api_key: str,
    user_id: int,
    lecture_id: int | None = None,
    get_client_fn=None,
    embeddings_create_fn=None,
    extract_reference_text_fn=None,
) -> str:
    """Semantic RAG: chunk local files, embed query/chunks with OpenAI, rank by cosine similarity."""
    client_factory = get_client_fn or get_client
    create_embeddings = embeddings_create_fn or embeddings_create
    extract_text = extract_reference_text_fn or extract_reference_text
    if not files:
        return ""

    documents: list[tuple[str, str]] = []
    for item in files:
        text = await asyncio.to_thread(extract_text, item)
        text = text.strip()
        if text:
            documents.append((str(item.get("name") or Path(item["path"]).name), text))
    if not documents:
        return ""

    chunk_size = positive_int("REFERENCE_RAG_CHUNK_CHARS", 2600)
    try:
        overlap_value = int(os.getenv("REFERENCE_RAG_CHUNK_OVERLAP_CHARS", "260"))
    except ValueError as exc:
        raise ValueError(
            "REFERENCE_RAG_CHUNK_OVERLAP_CHARS must be an integer"
        ) from exc
    overlap = min(max(0, overlap_value), max(0, chunk_size - 1))
    top_k = positive_int("REFERENCE_RAG_TOP_K", 16)
    try:
        max_chunks = int(os.getenv("REFERENCE_RAG_MAX_CHUNKS", "0"))
    except ValueError as exc:
        raise ValueError("REFERENCE_RAG_MAX_CHUNKS must be an integer") from exc
    if max_chunks < 0:
        raise ValueError(
            "REFERENCE_RAG_MAX_CHUNKS must be 0 (unlimited) or a positive integer"
        )
    limit = positive_int("MAX_REFERENCE_CONTEXT_CHARS", 60_000)
    model = (
        os.getenv("REFERENCE_EMBEDDING_MODEL", "text-embedding-3-small").strip()
        or "text-embedding-3-small"
    )

    chunks: list[tuple[str, str]] = []
    for name, text in documents:
        for chunk in _chunks(text, size=chunk_size, overlap=overlap):
            chunks.append((name, chunk))
            if max_chunks and len(chunks) >= max_chunks:
                break
        if max_chunks and len(chunks) >= max_chunks:
            break
    if not chunks:
        return ""

    query = f"강의 제목: {title}\n강의 주제: {topic}"
    client = client_factory(api_key=api_key)
    vectors: list[list[float]] = []
    async with client:
        query_response = await create_embeddings(
            client,
            user_id=user_id,
            lecture_id=lecture_id,
            model=model,
            input=[query],
            encoding_format="float",
            usage_context={
                "operation": "reference_rag_embedding",
                "stage": "references.query",
                "item_key": "query",
            },
        )
        query_vector = list(query_response.data[0].embedding)
        batch_size = positive_int("REFERENCE_EMBEDDING_BATCH_SIZE", 64)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            response = await create_embeddings(
                client,
                user_id=user_id,
                lecture_id=lecture_id,
                model=model,
                input=[chunk for _, chunk in batch],
                encoding_format="float",
                usage_context={
                    "operation": "reference_rag_embedding",
                    "stage": "references.chunk_batch",
                    "item_key": f"batch_{start // batch_size + 1}",
                    "item_index": start // batch_size + 1,
                    "metadata": {"batch_size": len(batch)},
                },
            )
            vectors.extend(list(item.embedding) for item in response.data)

    ranked = sorted(
        (
            (_cosine(query_vector, vector), index, chunks[index][0], chunks[index][1])
            for index, vector in enumerate(vectors)
        ),
        key=lambda item: (-item[0], item[1]),
    )

    selected: list[str] = []
    used = 0
    for score, _, name, chunk in ranked[:top_k]:
        block = f"### {name} (semantic RAG, similarity={score:.4f})\n{chunk}"
        if used + len(block) > limit:
            remaining = limit - used
            if remaining > 200:
                selected.append(block[:remaining])
            break
        selected.append(block)
        used += len(block)
    return "\n\n".join(selected)
