import hashlib
import inspect
import os
from pathlib import Path
from uuid import uuid4

from core.openai.client import get_client
from modules.lecture.composer import run_process, FFMPEG_BIN


TTS_API_MAX_CHARS = 4096
DEFAULT_TTS_CHUNK_CHARS = 3900


def _tts_chunk_chars() -> int:
    configured = int(os.getenv("LECTURE_TTS_CHUNK_CHARS", str(DEFAULT_TTS_CHUNK_CHARS)))
    return min(TTS_API_MAX_CHARS, max(500, configured))


def _split_tts_text(text: str, *, max_chars: int | None = None) -> list[str]:
    text = str(text or "").strip()
    if not text:
        raise ValueError("Narration text is empty.")
    limit = int(max_chars or _tts_chunk_chars())
    if limit <= 0 or limit > TTS_API_MAX_CHARS:
        raise ValueError(f"TTS chunk size must be between 1 and {TTS_API_MAX_CHARS} characters.")
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    boundaries = ("\n\n", "\n", ". ", "? ", "! ", "。", "！", "？", ".", "?", "!")
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = -1
        minimum_boundary = max(1, limit // 2)
        for marker in boundaries:
            pos = window.rfind(marker)
            if pos >= minimum_boundary:
                candidate = pos + len(marker)
                if candidate > cut:
                    cut = candidate
        if cut < 0:
            space = window.rfind(" ")
            cut = space + 1 if space >= minimum_boundary else limit
        chunk = remaining[:cut].strip()
        if not chunk:
            chunk = remaining[:limit]
            cut = limit
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _ffmpeg_concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))
    return f"file '{escaped}'"


async def _concat_wav_files(*, paths: list[Path], output_path: Path, work_dir: Path) -> None:
    if not paths:
        raise ValueError("No WAV chunks to concatenate.")
    if len(paths) == 1:
        _atomic_write(output_path, paths[0].read_bytes())
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    concat_file = work_dir / f".tts_concat_{token}.txt"
    temporary = output_path.with_name(f".{output_path.stem}.{token}.wav")
    concat_file.write_text("\n".join(_ffmpeg_concat_line(path) for path in paths), encoding="utf-8")
    try:
        await run_process(
            [
                FFMPEG_BIN,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            cwd=work_dir,
        )
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("TTS chunk concatenation produced no audio.")
        temporary.replace(output_path)
    finally:
        concat_file.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


async def _speech_bytes(
    *,
    api_key: str,
    model: str,
    voice: str,
    text: str,
) -> bytes:
    client = get_client(api_key=api_key)

    async with client:
        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="wav",
        )

        if hasattr(response, "aread"):
            result = response.aread()
            if inspect.isawaitable(result):
                return await result
            return result

        content = getattr(response, "content", None)

        if content is not None:
            return content

        if hasattr(response, "read"):
            result = response.read()
            if inspect.isawaitable(result):
                return await result
            return result

        raise RuntimeError(
            "Unable to read audio response bytes."
        )


def _tts_cache_key(*, model: str, voice: str, text: str) -> str:
    payload = f"{model}\0{voice}\0{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    if not content:
        raise ValueError("TTS returned empty audio.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _copy_cached_audio(cache_path: Path, output_path: Path) -> bool:
    if not cache_path.is_file() or cache_path.stat().st_size <= 0:
        return False
    _atomic_write(output_path, cache_path.read_bytes())
    return True


async def build_narration(
    *,
    api_key: str,
    plan: dict,
    output_dir: Path,
    model: str,
    voice: str,
    check_lease=None,
    cache_dir: Path | None = None,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    slide_audio_paths: list[Path] = []
    chunk_work_dir = output_dir / ".tts_chunks"

    for idx, slide in enumerate(plan["slides"], start=1):
        output_path = output_dir / f"slide_{idx:03d}.wav"
        narration_text = str(slide["narration"])
        full_cache_path = None
        if cache_dir is not None:
            full_cache_key = _tts_cache_key(model=model, voice=voice, text=narration_text)
            full_cache_path = cache_dir / f"{full_cache_key}.wav"

        if check_lease:
            await check_lease()

        if not output_path.is_file() or not output_path.stat().st_size:
            if full_cache_path is not None and _copy_cached_audio(full_cache_path, output_path):
                slide_audio_paths.append(output_path)
                continue

            chunks = _split_tts_text(narration_text)
            chunk_paths: list[Path] = []
            for chunk_index, chunk_text in enumerate(chunks, start=1):
                if check_lease:
                    await check_lease()

                chunk_key = _tts_cache_key(model=model, voice=voice, text=chunk_text)
                if cache_dir is not None:
                    chunk_path = cache_dir / f"{chunk_key}.wav"
                else:
                    chunk_path = chunk_work_dir / f"slide_{idx:03d}_{chunk_index:03d}_{chunk_key[:12]}.wav"

                if not chunk_path.is_file() or chunk_path.stat().st_size <= 0:
                    audio = await _speech_bytes(
                        api_key=api_key,
                        model=model,
                        voice=voice,
                        text=chunk_text,
                    )
                    _atomic_write(chunk_path, audio)
                chunk_paths.append(chunk_path)

            if check_lease:
                await check_lease()
            await _concat_wav_files(paths=chunk_paths, output_path=output_path, work_dir=output_dir)
            if full_cache_path is not None:
                _atomic_write(full_cache_path, output_path.read_bytes())

        slide_audio_paths.append(output_path)

    concat_file = output_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(_ffmpeg_concat_line(path) for path in slide_audio_paths),
        encoding="utf-8",
    )

    narration_path = output_dir.parent / "narration.wav"
    await run_process(
        [
            FFMPEG_BIN,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:a",
            "pcm_s16le",
            str(narration_path),
        ],
        cwd=output_dir,
    )

    return narration_path, slide_audio_paths

