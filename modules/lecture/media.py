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
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> str:
    limit = (
        timeout
        if timeout is not None
        else float(os.getenv("MEDIA_PROCESS_TIMEOUT_SECONDS", "3600"))
    )
    # Spool noisy FFmpeg/Ditto logs instead of accumulating them in RAM.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=out,
            stderr=err,
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
        raise FileNotFoundError(f"Media file not found: {path}")

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

    duration = payload.get("format", {}).get("duration")

    if duration is None:
        raise RuntimeError(f"Could not determine media duration: {path}")

    return float(duration)


def _concat_file_line(
    path: Path,
) -> str:
    absolute = str(path.resolve())

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
        output = Path(temp_dir) / "encoder_test.mp4"

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
        if await _test_encoder(encoder):
            print(f"[FFmpeg] selected encoder: {encoder}")
            return encoder

        print(f"[FFmpeg] encoder unavailable/broken: {encoder}")

    raise RuntimeError("사용 가능한 FFmpeg video encoder가 없습니다.")


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

    raise ValueError(f"Unsupported encoder: {encoder}")
