from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Sequence

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pptx import Presentation
from pptx.util import Inches

from core.openai.client import get_client


RAW_IMAGE_SIZE = "1536x1024"
PPT_IMAGE_WIDTH = 1920
PPT_IMAGE_HEIGHT = 1080
WIDTH = PPT_IMAGE_WIDTH
HEIGHT = PPT_IMAGE_HEIGHT

PPT_WIDTH_INCHES = 13.333333
PPT_HEIGHT_INCHES = 7.5

DEFAULT_MODEL = "gpt-image-2"
DEFAULT_QUALITY = os.getenv("OPENAI_SLIDE_IMAGE_QUALITY", "high")

AVATAR_OVERLAY_HEIGHT = 520
AVATAR_OVERLAY_MARGIN = 34
AVATAR_SAFE_PADDING = 70
AVATAR_SAFE_MIN_WIDTH = 520
AVATAR_SAFE_MAX_WIDTH = 900


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
) -> Path:
    client = get_client(api_key=api_key)
    async with client:
        result = await client.images.generate(
            model=model,
            prompt=prompt,
            size=RAW_IMAGE_SIZE,
            quality=quality,
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


def _estimate_avatar_safe_zone(avatar_source_path: Path | None) -> dict:
    avatar_width = AVATAR_SAFE_MIN_WIDTH
    if avatar_source_path and avatar_source_path.is_file():
        try:
            with Image.open(avatar_source_path) as image:
                width, height = image.size
            if width > 0 and height > 0:
                avatar_width = round(AVATAR_OVERLAY_HEIGHT * (width / height))
        except Exception:
            avatar_width = AVATAR_SAFE_MIN_WIDTH

    avatar_width = max(360, min(avatar_width, AVATAR_SAFE_MAX_WIDTH))
    safe_width = min(PPT_IMAGE_WIDTH - 80, max(AVATAR_SAFE_MIN_WIDTH, avatar_width + AVATAR_SAFE_PADDING * 2))
    safe_height = min(PPT_IMAGE_HEIGHT - 80, AVATAR_OVERLAY_HEIGHT + AVATAR_SAFE_PADDING * 2)
    right = PPT_IMAGE_WIDTH - AVATAR_OVERLAY_MARGIN
    bottom = PPT_IMAGE_HEIGHT - AVATAR_OVERLAY_MARGIN
    left = max(0, right - safe_width)
    top = max(0, bottom - safe_height)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
        "width_pct": round((right - left) / PPT_IMAGE_WIDTH * 100),
        "height_pct": round((bottom - top) / PPT_IMAGE_HEIGHT * 100),
    }


def _build_slide_prompt(
    *, lecture_title: str, slide_index: int, total_slides: int, slide: dict,
    avatar_safe_zone: dict,
) -> str:
    title = str(slide.get("title") or "").strip()
    bullets = [str(item).strip() for item in slide.get("bullets", []) if str(item).strip()]
    image_prompt = str(slide.get("image_prompt") or "").strip()
    bullet_block = "\n".join(f"- {item}" for item in bullets) or "- 핵심 내용을 간결하게 정리"
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
Keep a talking-presenter safe zone in the lower-right: x={avatar_safe_zone['left']}..{avatar_safe_zone['right']}, y={avatar_safe_zone['top']}..{avatar_safe_zone['bottom']} on a 1920x1080 canvas. Put no important text, labels, faces, charts or critical illustrations there. Do not draw a placeholder box for it.
Professional modern educational PPT style. Strong hierarchy, generous spacing, readable Korean typography, no logos, no watermark, no content cropping. Return one complete slide image only.
""".strip()


def _resize_exact_to_ppt_canvas(*, source_path: Path, output_path: Path):
    with Image.open(source_path) as source:
        image = source.convert("RGB").resize((PPT_IMAGE_WIDTH, PPT_IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")


async def generate_slide_image(
    *, api_key: str, model: str, lecture_title: str, slide_index: int,
    total_slides: int, slide: dict, output_path: Path,
    avatar_source_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_path.with_name(output_path.stem + "_raw" + output_path.suffix)
    prompt = _build_slide_prompt(
        lecture_title=lecture_title,
        slide_index=slide_index,
        total_slides=total_slides,
        slide=slide,
        avatar_safe_zone=_estimate_avatar_safe_zone(avatar_source_path),
    )
    await _save_openai_image(
        api_key=api_key,
        model=model or DEFAULT_MODEL,
        prompt=prompt,
        output_path=raw_path,
    )
    _resize_exact_to_ppt_canvas(source_path=raw_path, output_path=output_path)
    raw_path.unlink(missing_ok=True)
    return output_path


def _contain_size(source_width: int, source_height: int, max_width: int, max_height: int) -> tuple[int, int]:
    if min(source_width, source_height, max_width, max_height) <= 0:
        raise ValueError("Image dimensions must be positive.")
    scale = min(max_width / source_width, max_height / source_height)
    return max(1, round(source_width * scale)), max(1, round(source_height * scale))


def _fit_image(source_path: Path, box: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = box
    max_width, max_height = right - left, bottom - top
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = _contain_size(image.width, image.height, max_width, max_height)
        return image.resize((width, height), Image.Resampling.LANCZOS)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return []
    # Korean does not always contain spaces, so progressively split oversized words by character.
    units = text.split(" ")
    lines: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current} {unit}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        fragment = ""
        for char in unit:
            candidate = fragment + char
            if fragment and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(fragment)
                fragment = char
            else:
                fragment = candidate
        current = fragment
    if current:
        lines.append(current)
    return lines


def render_local_slide(
    *, lecture_title: str, slide_index: int, total_slides: int, slide: dict,
    output_path: Path, visual_path: Path | None = None,
    avatar_source_path: Path | None = None,
) -> Path:
    canvas = Image.new("RGB", (PPT_IMAGE_WIDTH, PPT_IMAGE_HEIGHT), (248, 250, 252))
    draw = ImageDraw.Draw(canvas)
    safe = _estimate_avatar_safe_zone(avatar_source_path)

    draw.rectangle((0, 0, PPT_IMAGE_WIDTH, 18), fill=(79, 70, 229))
    draw.text((90, 55), lecture_title[:100], font=_font(30, bold=True), fill=(100, 116, 139))
    draw.text((1690, 58), f"{slide_index:02d} / {total_slides:02d}", font=_font(26), fill=(100, 116, 139))

    title_font = _font(58, bold=True)
    body_font = _font(34)
    title = str(slide.get("title") or "핵심 내용").strip()
    y = 135
    for line in _wrap_text(draw, title, title_font, 1120)[:2]:
        draw.text((90, y), line, font=title_font, fill=(15, 23, 42))
        y += 76
    y += 35

    visual_exists = visual_path is not None and visual_path.is_file()
    content_right = 1110 if visual_exists else min(1320, safe["left"] - 40)
    text_width = max(650, content_right - 155)
    bullets = [str(item).strip() for item in slide.get("bullets", []) if str(item).strip()]
    for bullet in bullets[:6]:
        lines = _wrap_text(draw, bullet, body_font, text_width)
        if not lines:
            continue
        draw.ellipse((92, y + 14, 108, y + 30), fill=(79, 70, 229))
        for line_no, line in enumerate(lines[:3]):
            draw.text((132, y), line, font=body_font, fill=(51, 65, 85))
            y += 49
        y += 20
        if y > 900:
            break

    if visual_exists:
        box = (1160, 200, min(1810, safe["left"] - 35), 650)
        if box[2] - box[0] >= 260:
            visual = _fit_image(visual_path, box)
            x = box[0] + (box[2] - box[0] - visual.width) // 2
            vy = box[1] + (box[3] - box[1] - visual.height) // 2
            draw.rounded_rectangle((box[0] - 12, box[1] - 12, box[2] + 12, box[3] + 12), radius=28, fill=(255, 255, 255), outline=(226, 232, 240), width=3)
            canvas.paste(visual, (x, vy))

    # Keep the presenter region visually quiet without drawing a visible placeholder.
    draw.rounded_rectangle((safe["left"], safe["top"], safe["right"], safe["bottom"]), radius=40, fill=(241, 245, 249))
    draw.text((90, 1000), "AI Professor Lite", font=_font(24, bold=True), fill=(148, 163, 184))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path


def build_pptx_from_images(*, output_path: Path, slide_image_paths: Sequence[Path]) -> Path:
    prs = Presentation()
    prs.slide_width = Inches(PPT_WIDTH_INCHES)
    prs.slide_height = Inches(PPT_HEIGHT_INCHES)
    for image_path in slide_image_paths:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(str(image_path), 0, 0, width=prs.slide_width, height=prs.slide_height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)
    return output_path


async def build_slide_assets(
    *, api_key: str, title: str, plan: dict, output_dir: Path, image_model: str,
    generate_images: bool = True, image_paths: Sequence[Path | None] | None = None,
    avatar_source_path: Path | None = None,
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
    render_with_image_model = bool(generate_images and use_image_model_slide_rendering())

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
