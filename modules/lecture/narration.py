import hashlib
import inspect
from pathlib import Path
from uuid import uuid4

from core.openai.client import get_client
from modules.lecture.composer import run_process, FFMPEG_BIN


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
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    slide_audio_paths = []

    for idx, slide in enumerate(plan["slides"], start=1):
        output_path = (
            output_dir
            / f"slide_{idx:03d}.wav"
        )
        narration_text = str(slide["narration"])
        cache_path = None
        if cache_dir is not None:
            cache_key = _tts_cache_key(model=model, voice=voice, text=narration_text)
            cache_path = cache_dir / f"{cache_key}.wav"

        if check_lease:
            await check_lease()

        if not output_path.is_file() or not output_path.stat().st_size:
            if cache_path is None or not _copy_cached_audio(cache_path, output_path):
                audio = await _speech_bytes(
                    api_key=api_key,
                    model=model,
                    voice=voice,
                    text=narration_text,
                )
                # Persist the paid result outside the per-run directory first.
                # A replacement worker can safely reuse it because the cache key
                # includes the model, voice, and exact narration text.
                if cache_path is not None:
                    _atomic_write(cache_path, audio)
                _atomic_write(output_path, audio)

        slide_audio_paths.append(output_path)

    concat_file = output_dir / "concat.txt"

    concat_file.write_text(
        "\n".join(
            f"file '{str(path.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'"
            for path in slide_audio_paths
        ),
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
