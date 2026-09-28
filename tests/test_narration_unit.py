from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.lecture import narration


def test_tts_chunk_size_and_split_boundaries(monkeypatch):
    monkeypatch.setenv("LECTURE_TTS_CHUNK_CHARS", "100")
    assert narration._tts_chunk_chars() == 500
    monkeypatch.setenv("LECTURE_TTS_CHUNK_CHARS", "5000")
    assert narration._tts_chunk_chars() == narration.TTS_API_MAX_CHARS

    assert narration._split_tts_text(" short text ", max_chars=20) == ["short text"]
    chunks = narration._split_tts_text("A" * 12 + ". " + "B" * 12, max_chars=16)
    assert "".join(chunks).replace(" ", "") == ("A" * 12 + "." + "B" * 12)
    assert all(len(chunk) <= 16 for chunk in chunks)
    assert narration._split_tts_text("x" * 21, max_chars=10) == ["x" * 10, "x" * 10, "x"]

    with pytest.raises(ValueError, match="empty"):
        narration._split_tts_text("   ")
    with pytest.raises(ValueError, match="chunk size"):
        narration._split_tts_text("hello", max_chars=5000)


def test_atomic_write_cache_copy_and_concat_line(tmp_path):
    target = tmp_path / "nested" / "audio.wav"
    narration._atomic_write(target, b"wav")
    assert target.read_bytes() == b"wav"
    with pytest.raises(ValueError, match="empty audio"):
        narration._atomic_write(target, b"")

    output = tmp_path / "copied.wav"
    assert narration._copy_cached_audio(target, output) is True
    assert output.read_bytes() == b"wav"
    assert narration._copy_cached_audio(tmp_path / "missing.wav", output) is False

    quoted = narration._ffmpeg_concat_line(tmp_path / "it's.wav")
    assert quoted.startswith("file '") and "it" in quoted and "wav'" in quoted


@pytest.mark.asyncio
async def test_concat_wav_files_single_and_multiple(tmp_path, monkeypatch):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"A")
    second.write_bytes(b"B")

    single = tmp_path / "single.wav"
    await narration._concat_wav_files(paths=[first], output_path=single, work_dir=tmp_path)
    assert single.read_bytes() == b"A"

    async def fake_run(command, cwd):
        Path(command[-1]).write_bytes(b"joined")
        assert cwd == tmp_path

    monkeypatch.setattr(narration, "run_process", fake_run)
    output = tmp_path / "joined.wav"
    await narration._concat_wav_files(paths=[first, second], output_path=output, work_dir=tmp_path)
    assert output.read_bytes() == b"joined"
    assert not list(tmp_path.glob(".tts_concat_*.txt"))

    with pytest.raises(ValueError, match="No WAV chunks"):
        await narration._concat_wav_files(paths=[], output_path=output, work_dir=tmp_path)


class _FakeClient:
    def __init__(self, response):
        self.audio = SimpleNamespace(
            speech=SimpleNamespace(create=AsyncMock(return_value=response))
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_speech_bytes_supports_openai_response_shapes(monkeypatch):
    class AsyncAread:
        async def aread(self):
            return b"aread"

    monkeypatch.setattr(narration, "get_client", lambda **_: _FakeClient(AsyncAread()))
    assert await narration._speech_bytes(api_key="k", model="m", voice="v", text="t") == b"aread"

    monkeypatch.setattr(narration, "get_client", lambda **_: _FakeClient(SimpleNamespace(content=b"content")))
    assert await narration._speech_bytes(api_key="k", model="m", voice="v", text="t") == b"content"

    class SyncRead:
        def read(self):
            return b"read"

    monkeypatch.setattr(narration, "get_client", lambda **_: _FakeClient(SyncRead()))
    assert await narration._speech_bytes(api_key="k", model="m", voice="v", text="t") == b"read"

    monkeypatch.setattr(narration, "get_client", lambda **_: _FakeClient(object()))
    with pytest.raises(RuntimeError, match="Unable to read"):
        await narration._speech_bytes(api_key="k", model="m", voice="v", text="t")


@pytest.mark.asyncio
async def test_build_narration_uses_chunk_cache_and_full_cache(tmp_path, monkeypatch):
    output_dir = tmp_path / "audio" / "slides"
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("LECTURE_TTS_CHUNK_CHARS", "500")
    speech = AsyncMock(return_value=b"chunk-audio")
    monkeypatch.setattr(narration, "_speech_bytes", speech)

    async def fake_concat(*, paths, output_path, work_dir):
        output_path.write_bytes(b"|".join(path.read_bytes() for path in paths))

    async def fake_run(command, cwd):
        Path(command[-1]).write_bytes(b"final-narration")

    monkeypatch.setattr(narration, "_concat_wav_files", fake_concat)
    monkeypatch.setattr(narration, "run_process", fake_run)
    lease = AsyncMock()
    plan = {
        "slides": [
            {"narration": "A" * 650},
            {"narration": "short narration"},
        ]
    }

    narration_path, slide_paths = await narration.build_narration(
        api_key="key",
        plan=plan,
        output_dir=output_dir,
        model="tts",
        voice="alloy",
        check_lease=lease,
        cache_dir=cache_dir,
    )
    assert narration_path.read_bytes() == b"final-narration"
    assert len(slide_paths) == 2 and all(path.is_file() for path in slide_paths)
    assert speech.await_count == 3
    assert lease.await_count >= 5

    # Delete slide outputs only: second run should restore from full-result cache
    # without paying for TTS again.
    for path in slide_paths:
        path.unlink()
    speech.reset_mock()
    _, rebuilt = await narration.build_narration(
        api_key="key",
        plan=plan,
        output_dir=output_dir,
        model="tts",
        voice="alloy",
        cache_dir=cache_dir,
    )
    assert all(path.is_file() for path in rebuilt)
    speech.assert_not_awaited()

    # Change only one slide's narration. The content key must invalidate only
    # that run-local WAV while the unchanged slide is reused without a paid call.
    changed_plan = {
        "slides": [
            {"narration": "A" * 650},
            {"narration": "changed narration"},
        ]
    }
    speech.reset_mock()
    await narration.build_narration(
        api_key="key",
        plan=changed_plan,
        output_dir=output_dir,
        model="tts",
        voice="alloy",
        cache_dir=cache_dir,
    )
    assert speech.await_count == 1
