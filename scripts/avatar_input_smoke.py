from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from modules.lecture.background import (
    detect_avatar_input,
    prepare_avatar_source,
)


def _green_screen(path: Path) -> None:
    image = Image.new("RGB", (800, 1000), (0, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 100, 550, 400), fill=(220, 180, 150))
    draw.rectangle((180, 360, 620, 900), fill=(30, 30, 30))
    image.save(path)


def _ordinary(path: Path) -> None:
    image = Image.new("RGB", (800, 1000), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 100, 550, 400), fill=(220, 180, 150))
    draw.rectangle((180, 360, 620, 900), fill=(30, 30, 30))
    image.save(path)


def _transparent(path: Path) -> None:
    image = Image.new("RGBA", (800, 1000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 100, 550, 400), fill=(220, 180, 150, 255))
    draw.rectangle((180, 360, 620, 900), fill=(30, 30, 30, 255))
    image.save(path)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        green = root / "green.png"
        ordinary = root / "ordinary.png"
        transparent = root / "transparent.png"
        _green_screen(green)
        _ordinary(ordinary)
        _transparent(transparent)

        assert detect_avatar_input(green)["mode"] == "chroma"
        assert detect_avatar_input(ordinary)["mode"] == "portrait"
        assert detect_avatar_input(transparent)["mode"] == "transparent"

        prepared = prepare_avatar_source(
            source_path=green,
            output_dir=root / "prepared",
        )
        assert prepared.input_mode == "chroma"
        assert prepared.ditto_source.exists()
        assert prepared.chroma_color.upper() == "#00FF00"

    print("avatar input smoke: OK")


if __name__ == "__main__":
    main()
