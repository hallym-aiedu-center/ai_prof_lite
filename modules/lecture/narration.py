import inspect
from pathlib import Path

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


async def build_narration(
    *,
    api_key: str,
    plan: dict,
    output_dir: Path,
    model: str,
    voice: str,
    check_lease=None,
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    slide_audio_paths = []

    for idx, slide in enumerate(plan["slides"], start=1):
        output_path = (
            output_dir
            / f"slide_{idx:03d}.wav"
        )

        if check_lease:
            await check_lease()
        if not output_path.is_file() or not output_path.stat().st_size:
            audio = await _speech_bytes(api_key=api_key, model=model, voice=voice, text=slide["narration"])
            if not audio:
                raise ValueError("TTS returned empty audio.")
            temporary = output_path.with_suffix(".wav.tmp")
            temporary.write_bytes(audio)
            temporary.replace(output_path)
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
