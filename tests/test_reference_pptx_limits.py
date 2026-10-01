import zipfile

import pytest

from modules.lecture import references


def test_pptx_total_uncompressed_limit_includes_media(tmp_path, monkeypatch):
    path = tmp_path / "media-heavy.pptx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld/>" * 128)
        archive.writestr("ppt/media/image1.bin", b"A" * (2 * 1024 * 1024))

    # The archive itself is tiny, but its media member expands well past the cap.
    assert path.stat().st_size < 64 * 1024
    monkeypatch.setenv("MAX_PPTX_UNCOMPRESSED_BYTES", str(1024 * 1024))
    monkeypatch.setenv("MAX_PPTX_XML_BYTES", str(1024 * 1024))

    with pytest.raises(ValueError, match="PPTX 전체 해제 크기"):
        references._validate_pptx_archive_size(path)


def test_pptx_validation_runs_before_python_pptx_load(tmp_path, monkeypatch):
    path = tmp_path / "oversized-media.pptx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/media/image1.bin", b"B" * (2 * 1024 * 1024))

    monkeypatch.setenv("MAX_PPTX_UNCOMPRESSED_BYTES", str(1024 * 1024))

    def should_not_load(*args, **kwargs):
        raise AssertionError("Presentation() must not run for an oversized PPTX")

    monkeypatch.setattr(references, "Presentation", should_not_load)
    with pytest.raises(ValueError, match="PPTX 전체 해제 크기"):
        references._extract_pptx(path)
