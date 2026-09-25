from pathlib import Path

from PIL import Image

from .config import _env_float, _env_int

def _trim_alpha(
    foreground: Image.Image,
) -> Image.Image:
    rgba = foreground.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return rgba
    return rgba.crop(bbox)


def _feather_bottom_alpha(
    foreground: Image.Image,
) -> Image.Image:
    """Soften a hard lower crop without changing the head/hair silhouette."""
    rgba = foreground.convert("RGBA")
    feather_px = _env_int(
        "AVATAR_BOTTOM_FEATHER_PX",
        28,
        minimum=0,
    )
    if feather_px <= 0:
        return rgba

    alpha = rgba.getchannel("A")
    width, height = rgba.size
    feather_px = min(feather_px, max(1, height // 5))
    gradient = Image.new("L", (1, height), 255)
    gradient_pixels = gradient.load()
    start = height - feather_px

    for y in range(start, height):
        # Keep the first row fully opaque and ease towards zero at the bottom.
        ratio = (height - 1 - y) / max(feather_px - 1, 1)
        gradient_pixels[0, y] = max(0, min(255, int(255 * ratio)))

    gradient = gradient.resize((width, height))
    softened = Image.composite(
        alpha,
        Image.new("L", alpha.size, 0),
        gradient,
    )
    rgba.putalpha(softened)
    return rgba


def _presenter_canvas(
    foreground: Image.Image,
) -> Image.Image:
    """Normalize a transparent person into a stable Ditto portrait canvas."""
    foreground = _trim_alpha(foreground)
    foreground = _feather_bottom_alpha(foreground)

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
    side_ratio = _env_float(
        "AVATAR_SOURCE_SIDE_PAD_RATIO",
        0.10,
        minimum=0.0,
        maximum=0.45,
    )
    top_ratio = _env_float(
        "AVATAR_SOURCE_TOP_PAD_RATIO",
        0.06,
        minimum=0.0,
        maximum=0.45,
    )
    bottom_ratio = _env_float(
        "AVATAR_SOURCE_BOTTOM_PAD_RATIO",
        0.11,
        minimum=0.0,
        maximum=0.45,
    )

    max_width = max(1, int(canvas_width * (1.0 - side_ratio * 2.0)))
    max_height = max(1, int(canvas_height * (1.0 - top_ratio - bottom_ratio)))
    scale = min(
        max_width / max(foreground.width, 1),
        max_height / max(foreground.height, 1),
    )
    new_width = max(1, int(foreground.width * scale))
    new_height = max(1, int(foreground.height * scale))
    foreground = foreground.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    canvas = Image.new(
        "RGBA",
        (canvas_width, canvas_height),
        (0, 0, 0, 0),
    )
    x = (canvas_width - new_width) // 2
    y = canvas_height - int(canvas_height * bottom_ratio) - new_height
    y = max(int(canvas_height * top_ratio), y)
    canvas.alpha_composite(foreground, (x, y))
    return canvas



def _save_normalized_transparent(
    *,
    source_path: Path,
    transparent_path: Path,
) -> Path:
    with Image.open(source_path) as image:
        prepared = _presenter_canvas(image.convert("RGBA"))
    transparent_path.parent.mkdir(parents=True, exist_ok=True)
    prepared.save(transparent_path, format="PNG", optimize=True)
    return transparent_path

