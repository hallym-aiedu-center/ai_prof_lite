from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.lecture import stages


class FakeContext:
    def __init__(self, tmp_path, plan):
        self.api_key = 'key'
        self.directory = tmp_path / 'run'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache_directory = tmp_path / 'cache'
        self.lecture = {
            'target_duration_minutes': 40,
            'tts_model': 'tts',
            'tts_voice': 'alloy',
            'text_model': 'text',
        }
        plan_file = self.directory / 'lecture_plan.json'
        plan_file.write_text('{}', encoding='utf-8')
        self.outputs = {
            'plan': {
                'plan': plan,
                'files': [str(plan_file)],
            }
        }
        self.check = AsyncMock()
        self.update = AsyncMock()
        self.checkpoint = AsyncMock()


@pytest.mark.asyncio
async def test_narration_stage_expands_until_actual_audio_meets_minimum(tmp_path, monkeypatch, plan):
    ctx = FakeContext(tmp_path, plan)
    audio_dir = ctx.directory / 'audio'
    audio_dir.mkdir(parents=True, exist_ok=True)
    narration_path = ctx.directory / 'narration.wav'
    narration_path.write_bytes(b'audio')
    slide_paths = []
    for index in range(4):
        path = audio_dir / f'slide_{index + 1:03d}.wav'
        path.write_bytes(b'audio')
        slide_paths.append(path)

    build = AsyncMock(return_value=(narration_path, slide_paths))
    expanded = dict(plan)
    expanded['slides'] = [
        dict(slide, narration=slide['narration'] + ' 확장 설명')
        for slide in plan['slides']
    ]
    expand = AsyncMock(return_value=expanded)
    duration = AsyncMock(side_effect=[1800.0, 2520.0])
    monkeypatch.setattr(stages, 'build_narration', build)
    monkeypatch.setattr(stages, 'expand_lecture_narrations', expand)
    monkeypatch.setattr(stages, 'media_duration', duration)

    result = await stages.narration_stage(ctx)

    assert build.await_count == 2
    assert expand.await_count == 1
    assert result['duration'] == 2520.0
    assert result['target_duration'] == 2400.0
    assert result['duration_corrections'] == 1
    assert ctx.outputs['plan']['plan'] == expanded
    ctx.checkpoint.assert_any_await('plan', 'completed', ctx.outputs['plan'])
    assert '확장 설명' in (ctx.directory / 'lecture_plan.json').read_text(encoding='utf-8')


@pytest.mark.asyncio
async def test_narration_stage_fails_after_bounded_corrections(tmp_path, monkeypatch, plan):
    ctx = FakeContext(tmp_path, plan)
    narration_path = ctx.directory / 'narration.wav'
    narration_path.write_bytes(b'audio')
    slide_path = ctx.directory / 'audio' / 'slide_001.wav'
    slide_path.parent.mkdir(parents=True, exist_ok=True)
    slide_path.write_bytes(b'audio')

    monkeypatch.setenv('LECTURE_DURATION_MAX_RETRIES', '1')
    monkeypatch.setattr(
        stages,
        'build_narration',
        AsyncMock(return_value=(narration_path, [slide_path])),
    )
    monkeypatch.setattr(stages, 'media_duration', AsyncMock(side_effect=[1200.0, 1500.0]))
    monkeypatch.setattr(stages, 'expand_lecture_narrations', AsyncMock(return_value=plan))

    with pytest.raises(RuntimeError, match='목표 강의시간을 충족하지 못했습니다'):
        await stages.narration_stage(ctx)


@pytest.mark.asyncio
async def test_compose_stage_rejects_video_below_hard_minimum(tmp_path, monkeypatch):
    final = tmp_path / 'final.mp4'
    final.write_bytes(b'video')
    monkeypatch.setattr(stages, 'compose_final_video', AsyncMock(return_value=final))
    monkeypatch.setattr(stages, 'media_duration', AsyncMock(return_value=2399.0))

    ctx = SimpleNamespace(
        lecture={'target_duration_minutes': 40},
        directory=tmp_path,
        outputs={
            'timeline': {'video': str(tmp_path / 'slides.mp4')},
            'avatar': {'video': str(tmp_path / 'avatar.mp4'), 'chroma_color': '#00ff00'},
            'narration': {'narration': str(tmp_path / 'narration.wav')},
        },
        update=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match='최종 강의 영상이 목표 강의시간보다 짧습니다'):
        await stages.compose_stage(ctx)
    ctx.update.assert_not_awaited()
