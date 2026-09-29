from __future__ import annotations

import os
from pathlib import Path

from modules.lecture.media import (
    FFMPEG_BIN,
    _concat_file_line,
    detect_video_encoder,
    encoder_args,
    media_duration,
    run_process,
)


async def build_slides_video(
    *,
    slide_pngs: list[Path],
    slide_audio_paths: list[Path],
    output_dir: Path,
) -> Path:
    if len(slide_pngs) != len(slide_audio_paths):
        raise ValueError("Slide PNG and audio counts do not match.")

    if not slide_pngs:
        raise ValueError("No slide images were provided.")

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    segment_dir = output_dir / "segments"

    segment_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoder = await detect_video_encoder()

    segment_paths: list[Path] = []
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
        duration = await media_duration(audio_path)
        expected_duration += duration

        segment_path = segment_dir / f"segment_{idx:03d}.mp4"

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

        await run_process(command)
        actual = await media_duration(segment_path)
        if abs(actual - duration) > 0.12:
            raise RuntimeError("슬라이드 영상과 음성 길이가 일치하지 않습니다.")

        segment_paths.append(segment_path)

    concat_file = segment_dir / "segments.txt"

    concat_file.write_text(
        "\n".join(_concat_file_line(path) for path in segment_paths),
        encoding="utf-8",
    )

    slides_video = output_dir / "slides.mp4"

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
        raise RuntimeError("합쳐진 슬라이드 영상 길이가 예상 길이와 일치하지 않습니다.")
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
            raise FileNotFoundError(f"Required media file not found: {path}")

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoder = await detect_video_encoder()

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

    await run_process(command)

    expected = min(
        await media_duration(slides_video), await media_duration(narration_audio)
    )
    if abs(await media_duration(output_path) - expected) > 0.12:
        raise RuntimeError("최종 영상 길이가 입력 영상·음성 길이와 일치하지 않습니다.")

    return output_path
