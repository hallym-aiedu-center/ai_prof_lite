import os
from pathlib import Path
from statistics import median

from PIL import Image, ImageColor

from .config import _env_float


def _thumbnail_rgba(
    image: Image.Image,
    maximum: int = 512,
) -> Image.Image:
    sample = image.convert("RGBA").copy()
    sample.thumbnail(
        (maximum, maximum),
        Image.Resampling.BILINEAR,
    )
    return sample


def _border_pixels(
    image: Image.Image,
) -> list[tuple[int, int, int, int]]:
    sample = _thumbnail_rgba(image)
    width, height = sample.size
    thickness = max(3, int(min(width, height) * 0.06))
    pixels = sample.load()
    result: list[tuple[int, int, int, int]] = []

    for y in range(height):
        for x in range(width):
            if (
                x < thickness
                or x >= width - thickness
                or y < thickness
                or y >= height - thickness
            ):
                result.append(pixels[x, y])

    return result


def _green_like(r: int, g: int, b: int) -> bool:
    return (
        g >= 105
        and g >= r + 35
        and g >= b + 25
        and g >= int(r * 1.25)
    )


def _blue_like(r: int, g: int, b: int) -> bool:
    return (
        b >= 105
        and b >= r + 35
        and b >= g + 20
        and b >= int(r * 1.25)
    )


def _representative_color(
    pixels: list[tuple[int, int, int, int]],
) -> tuple[int, int, int]:
    if not pixels:
        return (0, 255, 0)
    return (
        int(median([item[0] for item in pixels])),
        int(median([item[1] for item in pixels])),
        int(median([item[2] for item in pixels])),
    )


def _hex_color(
    rgb: tuple[int, int, int],
) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def detect_avatar_input(
    source_path: Path,
) -> dict:
    """Detect transparent, green/blue chroma, or ordinary portrait input.

    The decision intentionally focuses on the *border* of the source image.
    A chroma screen normally dominates image edges while a shirt or object of
    the same color usually does not. This makes the detector less likely to
    misclassify a green/blue garment as the background.
    """
    if not source_path.exists():
        raise FileNotFoundError(
            f"Portrait image not found: {source_path}"
        )

    with Image.open(source_path) as image:
        rgba = image.convert("RGBA")
        sample = _thumbnail_rgba(rgba)

        alpha_values = sample.getchannel("A").tobytes()
        transparent_ratio = (
            sum(1 for value in alpha_values if value <= 32)
            / max(len(alpha_values), 1)
        )
        partial_alpha_ratio = (
            sum(1 for value in alpha_values if value < 245)
            / max(len(alpha_values), 1)
        )

        # A meaningful transparent region means the image has already been
        # background-removed. A tiny alpha fringe is not enough on its own.
        if (
            transparent_ratio >= _env_float(
                "AVATAR_TRANSPARENT_RATIO_THRESHOLD",
                0.005,
                minimum=0.0,
                maximum=1.0,
            )
            or partial_alpha_ratio >= 0.08
        ):
            return {
                "mode": "transparent",
                "chroma_color": None,
                "score": max(transparent_ratio, partial_alpha_ratio),
            }

        border = [
            pixel
            for pixel in _border_pixels(rgba)
            if pixel[3] >= 220
        ]

    if not border:
        return {
            "mode": "portrait",
            "chroma_color": None,
            "score": 0.0,
        }

    green_pixels = [
        item
        for item in border
        if _green_like(item[0], item[1], item[2])
    ]
    blue_pixels = [
        item
        for item in border
        if _blue_like(item[0], item[1], item[2])
    ]

    green_score = len(green_pixels) / len(border)
    blue_score = len(blue_pixels) / len(border)
    threshold = _env_float(
        "AVATAR_CHROMA_BORDER_THRESHOLD",
        0.64,
        minimum=0.1,
        maximum=1.0,
    )

    if max(green_score, blue_score) < threshold:
        return {
            "mode": "portrait",
            "chroma_color": None,
            "score": max(green_score, blue_score),
        }

    if green_score >= blue_score:
        color = _representative_color(green_pixels)
        score = green_score
    else:
        color = _representative_color(blue_pixels)
        score = blue_score

    return {
        "mode": "chroma",
        "chroma_color": _hex_color(color),
        "score": score,
    }


def _parse_forced_chroma_color(
    value: str,
) -> tuple[int, int, int] | None:
    normalized = value.strip().lower()
    if not normalized or normalized == "auto":
        return None
    if normalized == "green":
        return (0, 255, 0)
    if normalized == "blue":
        return (0, 0, 255)
    try:
        return ImageColor.getrgb(value)
    except ValueError as exc:
        raise RuntimeError(
            f"잘못된 AVATAR_INPUT_CHROMA_COLOR 값입니다: {value}"
        ) from exc


def _resolve_input_decision(
    source_path: Path,
) -> dict:
    forced_mode = os.getenv(
        "AVATAR_INPUT_MODE",
        "auto",
    ).strip().lower()

    if forced_mode not in {
        "auto",
        "portrait",
        "chroma",
        "transparent",
    }:
        raise RuntimeError(
            "AVATAR_INPUT_MODE must be one of: "
            "auto, portrait, chroma, transparent"
        )

    detected = detect_avatar_input(source_path)

    if forced_mode == "auto":
        return detected

    if forced_mode == "chroma":
        forced_color = _parse_forced_chroma_color(
            os.getenv(
                "AVATAR_INPUT_CHROMA_COLOR",
                "auto",
            )
        )
        if forced_color is not None:
            chroma_color = _hex_color(forced_color)
        elif detected["mode"] == "chroma":
            chroma_color = detected["chroma_color"]
        else:
            # Green is a deterministic fallback when the operator explicitly
            # declares that the source is a chroma image but auto-color cannot
            # confidently infer its screen color.
            chroma_color = "#00FF00"
        return {
            "mode": "chroma",
            "chroma_color": chroma_color,
            "score": detected.get("score", 0.0),
        }

    return {
        "mode": forced_mode,
        "chroma_color": None,
        "score": detected.get("score", 0.0),
    }
