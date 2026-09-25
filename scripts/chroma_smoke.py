"""Small FFmpeg chroma-key smoke test.

Run from the project root:
    python scripts/chroma_smoke.py

It generates synthetic slide/avatar/audio media and verifies the same final
composition function used by lecture jobs. No OpenAI, Moodle, Ditto or rembg
access is required.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.lecture.composer import FFMPEG_BIN, compose_final_video, run_process


async def main() -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        slides = root / "slides.mp4"
        avatar = root / "avatar.mp4"
        audio = root / "narration.wav"
        final = root / "final.mp4"

        await run_process(
            [
                FFMPEG_BIN,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=white:s=1920x1080:r=25:d=1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(slides),
            ],
            timeout=60,
        )

        await run_process(
            [
                FFMPEG_BIN,
                "-y",
                "-f",
                "lavfi",
                "-i",
                (
                    "color=c=0x00FF00:s=640x480:r=25:d=1,"
                    "drawbox=x=160:y=80:w=320:h=360:color=red:t=fill"
                ),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(avatar),
            ],
            timeout=60,
        )

        await run_process(
            [
                FFMPEG_BIN,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ],
            timeout=60,
        )

        await compose_final_video(
            slides_video=slides,
            avatar_video=avatar,
            narration_audio=audio,
            output_path=final,
            chroma_color="#00FF00",
        )

        if not final.exists() or final.stat().st_size == 0:
            raise RuntimeError("Chroma smoke test failed")

        print(
            "OK - chroma composition generated:",
            final,
            final.stat().st_size,
            "bytes",
        )


if __name__ == "__main__":
    asyncio.run(main())
