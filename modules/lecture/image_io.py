from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PIL import Image


def atomic_write_bytes(path: Path, content: bytes) -> None:
    if not content:
        raise ValueError("Cannot persist an empty image artifact.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_image_atomic(image: Image.Image, path: Path, image_format: str = "PNG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        image.save(temporary, format=image_format)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def is_valid_image(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False
