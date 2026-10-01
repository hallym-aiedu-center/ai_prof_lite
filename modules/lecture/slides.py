from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from core.openai.client import get_client
from core.openai.usage import images_generate
from modules.lecture.slide_rendering import (
    PPT_IMAGE_HEIGHT,
    PPT_IMAGE_WIDTH,
    _contain_size,
    _estimate_avatar_safe_zone,
    _fit_image as _render_fit_image,
    build_pptx_from_images,
    render_local_slide,
)

# Backward-compatible exports kept for callers/tests that import these symbols
# from modules.lecture.slides.
WIDTH = PPT_IMAGE_WIDTH
HEIGHT = PPT_IMAGE_HEIGHT
_fit_image = _render_fit_image

RAW_IMAGE_SIZE = "1536x1024"
WIDE_IMAGE_SIZE = "1536x864"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_QUALITY = os.getenv("OPENAI_SLIDE_IMAGE_QUALITY", "high")


def _bool_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def use_image_model_slide_rendering() -> bool:
    return _bool_env("LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL", True)


def _atomic_write(path: Path, content: bytes):
    if not content:
        raise ValueError("Image API returned an empty image.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


async def _save_openai_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    output_path: Path,
    quality: str = DEFAULT_QUALITY,
    size: str = RAW_IMAGE_SIZE,
    user_id: int | None = None,
    lecture_id: int | None = None,
    usage_context: dict | None = None,
) -> Path:
    if user_id is None:
        raise ValueError("Tracked OpenAI image calls require user_id.")
    client = get_client(api_key=api_key)
    async with client:
        result = await images_generate(
            client,
            user_id=user_id,
            lecture_id=lecture_id,
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            usage_context=usage_context,
        )

    item = result.data[0]
    if getattr(item, "b64_json", None):
        _atomic_write(output_path, base64.b64decode(item.b64_json))
        return output_path

    url = getattr(item, "url", None)
    if not url:
        raise RuntimeError("Image API returned neither b64_json nor url.")

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as http:
        response = await http.get(url)
        response.raise_for_status()
        _atomic_write(output_path, response.content)
    return output_path


def _build_slide_prompt(
    *,
    lecture_title: str,
    slide_index: int,
    total_slides: int,
    slide: dict,
    avatar_safe_zone: dict,
) -> str:
    title = str(slide.get("title") or "").strip()
    bullets = [
        str(item).strip() for item in slide.get("bullets", []) if str(item).strip()
    ]
    image_prompt = str(slide.get("image_prompt") or "").strip()
    bullet_block = (
        "\n".join(f"- {item}" for item in bullets) or "- 핵심 내용을 간결하게 정리"
    )
    visual_block = image_prompt or "관련 개념을 보조하는 교육용 시각 요소"
    return f"""
Create a single finished 16:9 presentation slide image in Korean.
It must be one flat polished lecture slide, including all text directly in the image.
Lecture title: {lecture_title}
Slide: {slide_index}/{total_slides}
Main title: {title}
Body bullet points that must appear in Korean:
{bullet_block}
Visual concept:
{visual_block}
Keep a talking-presenter safe zone in the lower-right: x={avatar_safe_zone["left"]}..{avatar_safe_zone["right"]}, y={avatar_safe_zone["top"]}..{avatar_safe_zone["bottom"]} on a 1920x1080 canvas. Put no important text, labels, faces, charts or critical illustrations there. Do not draw a placeholder box for it.
Professional modern educational PPT style. Strong hierarchy, generous spacing, readable Korean typography, no logos, no watermark, no content cropping. Return one complete slide image only.
""".strip()


def _image_request_size(model: str) -> str:
    # GPT Image 2 supports arbitrary valid dimensions, so request the final 16:9
    # composition directly. Older selectable models keep their legacy landscape
    # size and are contained without distortion below.
    return (
        WIDE_IMAGE_SIZE
        if str(model or "").startswith("gpt-image-2")
        else RAW_IMAGE_SIZE
    )


def _slide_cache_key(*, model: str, quality: str, size: str, prompt: str) -> str:
    payload = f"v2\0{model}\0{quality}\0{size}\0{prompt}".encode()
    return hashlib.sha256(payload).hexdigest()


def _copy_cached_image(cache_path: Path, output_path: Path) -> bool:
    if not cache_path.is_file() or cache_path.stat().st_size <= 0:
        return False
    _atomic_write(output_path, cache_path.read_bytes())
    return True


def _fit_to_ppt_canvas(*, source_path: Path, output_path: Path):
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = _contain_size(
            image.width, image.height, PPT_IMAGE_WIDTH, PPT_IMAGE_HEIGHT
        )
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (PPT_IMAGE_WIDTH, PPT_IMAGE_HEIGHT), (255, 255, 255))
        canvas.paste(
            image,
            ((PPT_IMAGE_WIDTH - width) // 2, (PPT_IMAGE_HEIGHT - height) // 2),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")


async def generate_slide_image(
    *,
    api_key: str,
    model: str,
    lecture_title: str,
    slide_index: int,
    total_slides: int,
    slide: dict,
    output_path: Path,
    avatar_source_path: Path | None = None,
    cache_dir: Path | None = None,
    user_id: int | None = None,
    lecture_id: int | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    actual_model = model or DEFAULT_MODEL
    request_size = _image_request_size(actual_model)
    prompt = _build_slide_prompt(
        lecture_title=lecture_title,
        slide_index=slide_index,
        total_slides=total_slides,
        slide=slide,
        avatar_safe_zone=_estimate_avatar_safe_zone(avatar_source_path),
    )

    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / (
            _slide_cache_key(
                model=actual_model,
                quality=DEFAULT_QUALITY,
                size=request_size,
                prompt=prompt,
            )
            + ".png"
        )
        if _copy_cached_image(cache_path, output_path):
            return output_path

    raw_path = output_path.with_name(output_path.stem + "_raw" + output_path.suffix)
    try:
        await _save_openai_image(
            api_key=api_key,
            model=actual_model,
            prompt=prompt,
            output_path=raw_path,
            size=request_size,
            user_id=user_id,
            lecture_id=lecture_id,
            usage_context={
                "operation": "lecture_slide_image",
                "stage": "slides.render",
                "item_key": f"slide_{slide_index:03d}",
                "item_index": slide_index,
                "metadata": {"total_slides": total_slides},
            },
        )
        _fit_to_ppt_canvas(source_path=raw_path, output_path=output_path)
        if cache_path is not None:
            _atomic_write(cache_path, output_path.read_bytes())
    finally:
        raw_path.unlink(missing_ok=True)
    return output_path


async def build_slide_assets(
    *,
    api_key: str,
    title: str,
    plan: dict,
    output_dir: Path,
    image_model: str,
    generate_images: bool = True,
    image_paths: Sequence[Path | None] | None = None,
    avatar_source_path: Path | None = None,
    cache_dir: Path | None = None,
    user_id: int | None = None,
    lecture_id: int | None = None,
) -> tuple[Path, list[Path]]:
    """Create slide PNGs and PPTX.

    Full-slide Image API rendering is used only when both generate_images=True and
    LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL is enabled. When image generation is
    disabled, no Image API call is made; deterministic local slides are rendered.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slides = plan.get("slides", [])
    total_slides = len(slides)
    visuals = list(image_paths or [])
    render_with_image_model = bool(
        generate_images and use_image_model_slide_rendering()
    )

    slide_png_paths: list[Path] = []
    for idx, slide in enumerate(slides, start=1):
        png_path = output_dir / f"slide_{idx:03d}.png"
        if not png_path.is_file() or not png_path.stat().st_size:
            if render_with_image_model:
                await generate_slide_image(
                    api_key=api_key,
                    model=image_model or DEFAULT_MODEL,
                    lecture_title=title,
                    slide_index=idx,
                    total_slides=total_slides,
                    slide=slide,
                    output_path=png_path,
                    avatar_source_path=avatar_source_path,
                    cache_dir=cache_dir,
                    user_id=user_id,
                    lecture_id=lecture_id,
                )
            else:
                visual = visuals[idx - 1] if idx - 1 < len(visuals) else None
                render_local_slide(
                    lecture_title=title,
                    slide_index=idx,
                    total_slides=total_slides,
                    slide=slide,
                    output_path=png_path,
                    visual_path=Path(visual) if visual else None,
                    avatar_source_path=avatar_source_path,
                )
        slide_png_paths.append(png_path)

    pptx_path = output_dir.parent / "lecture.pptx"
    build_pptx_from_images(output_path=pptx_path, slide_image_paths=slide_png_paths)
    return pptx_path, slide_png_paths
