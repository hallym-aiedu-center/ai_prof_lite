import os
from pathlib import Path

from PIL import Image, ImageColor

from .config import _env_int
from .detection import _hex_color


def _auto_chroma_rgb(
    foreground: Image.Image,
) -> tuple[int, int, int]:
    """Choose green or blue based on foreground color conflict."""
    sample = foreground.copy()
    sample.thumbnail(
        (256, 256),
        Image.Resampling.BILINEAR,
    )
    pixels = [(r, g, b) for r, g, b, a in sample.convert("RGBA").getdata() if a >= 96]

    if not pixels:
        return (0, 255, 0)

    candidates = [
        (0, 255, 0),
        (0, 0, 255),
    ]

    def conflict(candidate: tuple[int, int, int]) -> tuple[int, float]:
        cr, cg, cb = candidate
        distances = [
            (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2 for r, g, b in pixels
        ]
        close = sum(1 for value in distances if value < 130**2)
        average = sum(distances) / len(distances)
        return close, -average

    return min(
        candidates,
        key=conflict,
    )


def _resolve_output_chroma_rgb(
    foreground: Image.Image,
) -> tuple[int, int, int]:
    raw = os.getenv(
        "AVATAR_CHROMA_COLOR",
        "auto",
    ).strip()

    if raw.lower() == "auto":
        return _auto_chroma_rgb(foreground)

    try:
        return ImageColor.getrgb(raw)
    except ValueError as exc:
        raise RuntimeError(f"잘못된 AVATAR_CHROMA_COLOR 값입니다: {raw}") from exc


def _foreground_bbox_from_chroma(
    image: Image.Image,
    chroma_rgb: tuple[int, int, int],
) -> tuple[int, int, int, int] | None:
    """Estimate the person/content bbox without running semantic segmentation."""
    original = image.convert("RGB")
    sample = original.copy()
    sample.thumbnail((512, 512), Image.Resampling.BILINEAR)
    sw, sh = sample.size
    cr, cg, cb = chroma_rgb
    distance_threshold = _env_int(
        "AVATAR_CHROMA_FOREGROUND_DISTANCE",
        78,
        minimum=10,
    )
    threshold_sq = distance_threshold * distance_threshold

    xs: list[int] = []
    ys: list[int] = []
    for y in range(sh):
        for x in range(sw):
            r, g, b = sample.getpixel((x, y))
            distance_sq = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if distance_sq > threshold_sq:
                xs.append(x)
                ys.append(y)

    if not xs or not ys:
        return None

    x1, x2 = min(xs), max(xs) + 1
    y1, y2 = min(ys), max(ys) + 1

    # Reject masks that are suspiciously close to the entire image; in that
    # case keeping the original frame is safer than an aggressive crop.
    if (x2 - x1) * (y2 - y1) >= sw * sh * 0.92:
        return None

    scale_x = original.width / sw
    scale_y = original.height / sh
    return (
        max(0, int(x1 * scale_x)),
        max(0, int(y1 * scale_y)),
        min(original.width, int(x2 * scale_x)),
        min(original.height, int(y2 * scale_y)),
    )


def _normalize_existing_chroma(
    *,
    source_path: Path,
    output_path: Path,
    chroma_color: str,
) -> Path:
    """Reframe an already-chroma image without semantic background removal."""
    chroma_rgb = ImageColor.getrgb(chroma_color)
    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        bbox = _foreground_bbox_from_chroma(rgb, chroma_rgb)

        if bbox:
            x1, y1, x2, y2 = bbox
            pad_x = int((x2 - x1) * 0.13)
            pad_top = int((y2 - y1) * 0.10)
            pad_bottom = int((y2 - y1) * 0.16)
            crop_box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_top),
                min(rgb.width, x2 + pad_x),
                min(rgb.height, y2 + pad_bottom),
            )
            subject_frame = rgb.crop(crop_box)
        else:
            subject_frame = rgb

        canvas_width = _env_int(
            "AVATAR_SOURCE_CANVAS_WIDTH",
            1024,
            minimum=256,
        )
        canvas_height = _env_int(
            "AVATAR_SOURCE_CANVAS_HEIGHT",
            1536,
            minimum=256,
        )
        canvas = Image.new(
            "RGB",
            (canvas_width, canvas_height),
            chroma_rgb,
        )

        max_width = int(canvas_width * 0.90)
        max_height = int(canvas_height * 0.89)
        scale = min(
            max_width / max(subject_frame.width, 1),
            max_height / max(subject_frame.height, 1),
        )
        resized = subject_frame.resize(
            (
                max(1, int(subject_frame.width * scale)),
                max(1, int(subject_frame.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )
        x = (canvas_width - resized.width) // 2
        y = canvas_height - int(canvas_height * 0.06) - resized.height
        y = max(int(canvas_height * 0.03), y)
        canvas.paste(resized, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    return output_path


def composite_on_chroma(
    *,
    transparent_path: Path,
    chroma_path: Path,
) -> tuple[Path, str]:
    """Place a transparent portrait on a flat green/blue chroma canvas."""
    with Image.open(transparent_path) as image:
        foreground = image.convert("RGBA")
        chroma_rgb = _resolve_output_chroma_rgb(foreground)
        background = Image.new(
            "RGBA",
            foreground.size,
            (*chroma_rgb, 255),
        )
        composed = Image.alpha_composite(
            background,
            foreground,
        ).convert("RGB")

    chroma_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    composed.save(
        chroma_path,
        format="PNG",
        optimize=True,
    )
    return chroma_path, _hex_color(chroma_rgb)
