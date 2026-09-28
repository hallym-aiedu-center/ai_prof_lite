
import pytest
from PIL import Image

from modules.lecture.avatar_background import chroma


def test_auto_chroma_and_resolve_color(monkeypatch):
    transparent = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    assert chroma._auto_chroma_rgb(transparent) == (0, 255, 0)

    green_subject = Image.new("RGBA", (8, 8), (0, 230, 0, 255))
    blue_subject = Image.new("RGBA", (8, 8), (0, 0, 230, 255))
    assert chroma._auto_chroma_rgb(green_subject) == (0, 0, 255)
    assert chroma._auto_chroma_rgb(blue_subject) == (0, 255, 0)

    monkeypatch.setenv("AVATAR_CHROMA_COLOR", "#123456")
    assert chroma._resolve_output_chroma_rgb(green_subject) == (18, 52, 86)
    monkeypatch.setenv("AVATAR_CHROMA_COLOR", "not-a-color")
    with pytest.raises(RuntimeError, match="AVATAR_CHROMA_COLOR"):
        chroma._resolve_output_chroma_rgb(green_subject)


def test_foreground_bbox_detects_subject_and_rejects_bad_masks(monkeypatch):
    monkeypatch.setenv("AVATAR_CHROMA_FOREGROUND_DISTANCE", "40")
    green = (0, 255, 0)

    all_green = Image.new("RGB", (100, 80), green)
    assert chroma._foreground_bbox_from_chroma(all_green, green) is None

    full_red = Image.new("RGB", (100, 80), (255, 0, 0))
    assert chroma._foreground_bbox_from_chroma(full_red, green) is None

    framed = Image.new("RGB", (100, 80), green)
    for y in range(20, 70):
        for x in range(30, 70):
            framed.putpixel((x, y), (220, 20, 20))
    bbox = chroma._foreground_bbox_from_chroma(framed, green)
    assert bbox is not None
    x1, y1, x2, y2 = bbox
    assert x1 <= 30 <= x2 and y1 <= 20 <= y2
    assert x2 >= 70 and y2 >= 70


def test_normalize_existing_chroma_reframes_subject(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_SOURCE_CANVAS_WIDTH", "256")
    monkeypatch.setenv("AVATAR_SOURCE_CANVAS_HEIGHT", "320")
    source = tmp_path / "source.png"
    output = tmp_path / "out" / "normalized.png"
    image = Image.new("RGB", (120, 100), (0, 255, 0))
    for y in range(20, 95):
        for x in range(40, 80):
            image.putpixel((x, y), (200, 30, 30))
    image.save(source)

    result = chroma._normalize_existing_chroma(
        source_path=source,
        output_path=output,
        chroma_color="#00FF00",
    )
    assert result == output and output.is_file()
    with Image.open(output) as normalized:
        assert normalized.size == (256, 320)
        assert normalized.getpixel((0, 0)) == (0, 255, 0)
        assert any(pixel != (0, 255, 0) for pixel in normalized.getdata())


def test_composite_on_chroma_writes_flat_background(tmp_path, monkeypatch):
    source = tmp_path / "transparent.png"
    output = tmp_path / "nested" / "chroma.png"
    foreground = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    for y in range(5, 15):
        for x in range(5, 15):
            foreground.putpixel((x, y), (255, 0, 0, 255))
    foreground.save(source)

    monkeypatch.setenv("AVATAR_CHROMA_COLOR", "#123456")
    result, color = chroma.composite_on_chroma(
        transparent_path=source,
        chroma_path=output,
    )
    assert result == output and color == "#123456"
    with Image.open(output) as composed:
        assert composed.mode == "RGB"
        assert composed.getpixel((0, 0)) == (18, 52, 86)
        assert composed.getpixel((10, 10)) == (255, 0, 0)
