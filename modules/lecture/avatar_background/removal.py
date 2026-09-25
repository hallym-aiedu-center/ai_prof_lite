import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image

@lru_cache(maxsize=1)
def _rembg_session():
    try:
        from rembg import new_session
    except ImportError as exc:
        raise RuntimeError(
            "배경 제거 기능을 사용하려면 rembg가 필요합니다. "
            "`pip install rembg onnxruntime` 후 다시 실행하세요."
        ) from exc

    model = os.getenv(
        "REMBG_MODEL",
        "u2net_human_seg",
    ).strip() or "u2net_human_seg"

    return new_session(model)


def remove_portrait_background(
    *,
    source_path: Path,
    transparent_path: Path,
) -> Path:
    """Remove a non-chroma portrait background and save an RGBA PNG."""
    if not source_path.exists():
        raise FileNotFoundError(
            f"Portrait image not found: {source_path}"
        )

    try:
        from rembg import remove
    except ImportError as exc:
        raise RuntimeError(
            "배경 제거 기능을 사용하려면 rembg가 필요합니다. "
            "`pip install rembg onnxruntime` 후 다시 실행하세요."
        ) from exc

    with Image.open(source_path) as image:
        image = image.convert("RGBA")
        result = remove(
            image,
            session=_rembg_session(),
        )

    if isinstance(result, bytes):
        with Image.open(io.BytesIO(result)) as parsed:
            foreground = parsed.convert("RGBA")
    elif isinstance(result, Image.Image):
        foreground = result.convert("RGBA")
    else:
        raise RuntimeError(
            "rembg가 예상하지 못한 결과 형식을 반환했습니다."
        )

    transparent_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    foreground.save(
        transparent_path,
        format="PNG",
    )
    return transparent_path
