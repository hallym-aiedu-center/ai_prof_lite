from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path


FFMPEG_BIN = os.getenv(
    "FFMPEG_BIN",
    "ffmpeg",
)

FFPROBE_BIN = os.getenv(
    "FFPROBE_BIN",
    "ffprobe",
)


async def run_process(
    args: list[str], *, cwd: Path | None = None, env: dict | None = None,
    timeout: float | None = None,
) -> str:
    limit = timeout if timeout is not None else float(os.getenv("MEDIA_PROCESS_TIMEOUT_SECONDS", "3600"))
    # Spool noisy FFmpeg/Ditto logs instead of accumulating them in RAM.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd) if cwd else None, env=env, stdout=out, stderr=err,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), limit)
        except asyncio.TimeoutError as exc:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise TimeoutError(
                f"Process timed out after {limit} seconds: {' '.join(args)}"
            ) from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise
        err.seek(0, 2)
        err.seek(max(0, err.tell() - 12000))
        stderr = err.read().decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise RuntimeError("Command failed: " + " ".join(args) + "\n" + stderr)
        out.seek(0)
        return out.read(1024 * 1024).decode("utf-8", errors="replace")


async def media_duration(
    path: Path,
) -> float:
    if not path.exists():
        raise FileNotFoundError(
            f"Media file not found: {path}"
        )

    result = await run_process(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )

    payload = json.loads(result)

    duration = (
        payload
        .get("format", {})
        .get("duration")
    )

    if duration is None:
        raise RuntimeError(
            "Could not determine media "
            f"duration: {path}"
        )

    return float(duration)


def _concat_file_line(
    path: Path,
) -> str:
    absolute = str(
        path.resolve()
    )

    absolute = absolute.replace(
        "'",
        "'\\''",
    )

    return f"file '{absolute}'"


async def _test_encoder(
    encoder: str,
) -> bool:
    """
    Do a real encode test.

    This catches encoders which are listed by ffmpeg but fail at runtime,
    such as a libopenh264 ABI/version mismatch.
    """

    with tempfile.TemporaryDirectory() as temp_dir:
        output = (
            Path(temp_dir)
            / "encoder_test.mp4"
        )

        args = [
            FFMPEG_BIN,
            "-nostdin",
            "-xerror",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=25",
            "-t",
            "0.2",
            "-an",
            "-c:v",
            encoder,
        ]

        if encoder == "libx264":
            args += [
                "-preset",
                "veryfast",
                "-crf",
                "23",
            ]

        elif encoder in {
            "h264_nvenc",
            "libopenh264",
        }:
            args += [
                "-b:v",
                "2M",
            ]

        elif encoder == "mpeg4":
            args += [
                "-q:v",
                "4",
            ]

        args += [
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]

        try:
            await run_process(args, timeout=15)
        except (RuntimeError, asyncio.TimeoutError, FileNotFoundError):
            return False
        return output.exists() and output.stat().st_size > 0


async def detect_video_encoder() -> str:
    candidates = [
        "libx264",
        "h264_nvenc",
        "libopenh264",
        "mpeg4",
    ]

    for encoder in candidates:
        if await _test_encoder(
            encoder
        ):
            print(
                "[FFmpeg] selected encoder: "
                f"{encoder}"
            )
            return encoder

        print(
            "[FFmpeg] encoder "
            f"unavailable/broken: {encoder}"
        )

    raise RuntimeError(
        "사용 가능한 FFmpeg video "
        "encoder가 없습니다."
    )


def encoder_args(
    encoder: str,
    *,
    bitrate: str,
) -> list[str]:
    if encoder == "libx264":
        return [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
        ]

    if encoder == "h264_nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-b:v",
            bitrate,
        ]

    if encoder == "libopenh264":
        return [
            "-c:v",
            "libopenh264",
            "-b:v",
            bitrate,
        ]

    if encoder == "mpeg4":
        return [
            "-c:v",
            "mpeg4",
            "-q:v",
            "3",
        ]

    raise ValueError(
        f"Unsupported encoder: {encoder}"
    )


async def build_slides_video(
    *,
    slide_pngs: list[Path],
    slide_audio_paths: list[Path],
    output_dir: Path,
) -> Path:
    if len(slide_pngs) != len(
        slide_audio_paths
    ):
        raise ValueError(
            "Slide PNG and audio counts "
            "do not match."
        )

    if not slide_pngs:
        raise ValueError(
            "No slide images were provided."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    segment_dir = (
        output_dir
        / "segments"
    )

    segment_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoder = (
        await detect_video_encoder()
    )

    segment_paths: list[
        Path
    ] = []
    expected_duration = 0.0

    for idx, (
        slide_png,
        audio_path,
    ) in enumerate(
        zip(
            slide_pngs,
            slide_audio_paths,
        ),
        start=1,
    ):
        duration = (
            await media_duration(
                audio_path
            )
        )
        expected_duration += duration

        segment_path = (
            segment_dir
            / f"segment_{idx:03d}.mp4"
        )

        command = [
            FFMPEG_BIN,
            "-nostdin",
            "-xerror",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "25",
            "-i",
            str(slide_png),
            "-t",
            f"{duration:.4f}",
            "-vf",
            (
                "scale=1920:1080:"
                "force_original_aspect_ratio=decrease,"
                "pad=1920:1080:"
                "(ow-iw)/2:(oh-ih)/2,"
                "fps=25,"
                "format=yuv420p"
            ),
            "-an",
        ]

        command += encoder_args(
            encoder,
            bitrate="4M",
        )

        command += [
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(segment_path),
        ]

        await run_process(
            command
        )
        actual = await media_duration(segment_path)
        if abs(actual - duration) > 0.12:
            raise RuntimeError('슬라이드 영상과 음성 길이가 일치하지 않습니다.')

        segment_paths.append(
            segment_path
        )

    concat_file = (
        segment_dir
        / "segments.txt"
    )

    concat_file.write_text(
        "\n".join(
            _concat_file_line(path)
            for path in segment_paths
        ),
        encoding="utf-8",
    )

    slides_video = (
        output_dir
        / "slides.mp4"
    )

    await run_process(
        [
            FFMPEG_BIN,
            "-nostdin",
            "-xerror",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(slides_video),
        ]
    )

    actual_duration = await media_duration(slides_video)
    if abs(actual_duration - expected_duration) > max(0.12, 0.08 * len(slide_pngs)):
        raise RuntimeError('합쳐진 슬라이드 영상 길이가 예상 길이와 일치하지 않습니다.')
    return slides_video


async def compose_final_video(
    *,
    slides_video: Path,
    avatar_video: Path,
    narration_audio: Path,
    output_path: Path,
    chroma_color: str,
) -> Path:
    for path in (
        slides_video,
        avatar_video,
        narration_audio,
    ):
        if not path.exists():
            raise FileNotFoundError(
                "Required media file "
                f"not found: {path}"
            )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoder = (
        await detect_video_encoder()
    )

    similarity = float(os.getenv("AVATAR_CHROMA_SIMILARITY", "0.12"))
    blend = float(os.getenv("AVATAR_CHROMA_BLEND", "0.06"))
    if not 0.00001 <= similarity <= 1.0:
        raise ValueError("AVATAR_CHROMA_SIMILARITY must be between 0.00001 and 1.0")
    if not 0.0 <= blend <= 1.0:
        raise ValueError("AVATAR_CHROMA_BLEND must be between 0.0 and 1.0")

    color = chroma_color.strip()
    if color.startswith("#"):
        color = "0x" + color[1:]

    filter_complex = (
        "[0:v]"
        "scale=1920:1080,"
        "setsar=1,"
        "format=yuv420p"
        "[bg];"

        "[1:v]"
        "scale=-2:520,"
        "setsar=1,"
        f"chromakey={color}:{similarity}:{blend},"
        "format=yuva420p"
        "[avatar];"

        "[bg][avatar]"
        "overlay="
        "W-w-34:"
        "H-h-34:"
        "eof_action=pass"
        "[v]"
    )

    command = [
        FFMPEG_BIN,
        "-nostdin",
        "-xerror",
        "-y",
        "-i",
        str(slides_video),
        "-i",
        str(avatar_video),
        "-i",
        str(narration_audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "2:a:0",
    ]

    command += encoder_args(
        encoder,
        bitrate="5M",
    )

    command += [
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    await run_process(
        command
    )

    expected = min(await media_duration(slides_video), await media_duration(narration_audio))
    if abs(await media_duration(output_path) - expected) > 0.12:
        raise RuntimeError('최종 영상 길이가 입력 영상·음성 길이와 일치하지 않습니다.')

    return output_path
