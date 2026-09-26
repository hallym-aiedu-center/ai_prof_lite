import wave
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from core.database.client import get_connection
from core.jobs.errors import AmbiguousDeploymentError, retryable
from core.jobs.sqlite import SQLiteJobQueue
from modules.lecture import stages, narration, publish_scheduler
from modules.lecture.checkpoints import get_stage
from modules.lecture.composer import (
    detect_video_encoder, encoder_args, media_duration, run_process,
)
from modules.lecture.repository import (
    create_publish_schedule_config,
    get_lecture,
    get_publish_schedule,
    update_lecture,
)
from modules.lecture.service import run_lecture_job


def wav_bytes():
    import io
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\0\0' * 4800)
    return data.getvalue()


async def ready(make_lecture, **overrides):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture(**overrides)
    await queue.enqueue(lecture_id)
    return queue, await queue.claim('pipeline')


async def test_pipeline_retry_reuses_paid_stages_and_real_ffmpeg(make_lecture, monkeypatch, plan):
    monkeypatch.setenv("LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL", "false")
    plan = dict(plan)
    plan["slides"] = [
        dict(slide, narration=f"test narration {idx}")
        for idx, slide in enumerate(plan["slides"], start=1)
    ]
    queue, job = await ready(make_lecture)
    async def preflight(ctx):
        await ctx.check()
        ctx.api_key = 'test'
        ctx.directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stages.StageContext, 'preflight', preflight)
    planner = AsyncMock(return_value=plan)
    monkeypatch.setattr(stages, 'create_lecture_plan', planner)
    images = []
    async def image(**kwargs):
        path = kwargs['output_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (64, 64), 'blue').save(path)
        images.append(path)
        return path
    monkeypatch.setattr(stages, 'generate_image', image)
    speech = AsyncMock(side_effect=[wav_bytes(), TimeoutError('temporary'), *[wav_bytes() for _ in range(3)]])
    monkeypatch.setattr(narration, '_speech_bytes', speech)
    async def avatar(**kwargs):
        path = kwargs['output_path']
        encoder = await detect_video_encoder()
        command = [
            'ffmpeg', '-nostdin', '-xerror', '-y',
            '-f', 'lavfi', '-i', 'color=c=blue:s=192x192:r=25',
            '-t', '0.8', '-an',
        ]
        command += encoder_args(encoder, bitrate='2M')
        command += ['-pix_fmt', 'yuv420p', str(path)]
        await run_process(command)
        return path
    monkeypatch.setattr(stages, 'create_avatar_video', avatar)
    with pytest.raises(TimeoutError): await run_lecture_job(job, queue)
    await queue.fail(job, 'transient TTS timeout', retryable=True)
    db = await get_connection()
    try:
        await db.execute('UPDATE lecture_jobs SET available_at=0')
        await db.commit()
    finally: await db.close()
    retry = await queue.claim('replacement')
    await run_lecture_job(retry, queue)
    assert await queue.finish(retry)
    result = await get_lecture(job.lecture_id)
    assert result['status'] == 'completed' and result['progress'] == 100
    assert await media_duration(Path(result['final_video_path'])) > 0.5
    assert Path(result['pptx_path']).is_file()
    assert planner.await_count == 1 and len(images) == 4
    # slide 1 succeeded before the first attempt failed on slide 2. The retry
    # must reuse that paid TTS result instead of calling the API again.
    assert speech.await_count == 5
    assert (await get_stage(job.lecture_id, 'deploy'))['status'] == 'completed'


async def test_preflight_fails_before_paid_calls(make_lecture, monkeypatch):
    queue, job = await ready(make_lecture)
    planner = AsyncMock()
    monkeypatch.setattr(stages, 'create_lecture_plan', planner)
    with pytest.raises(FileNotFoundError): await run_lecture_job(job, queue)
    planner.assert_not_awaited()


async def test_moodle_ambiguous_create_not_repeated(make_lecture, monkeypatch):
    queue, job = await ready(make_lecture, upload_to_moodle=True, moodle_course_id=7, moodle_section_num=0)
    ctx = stages.StageContext(job, queue, await get_lecture(job.lecture_id), outputs={'compose': {'video': 'fake.mp4'}})
    monkeypatch.setattr(stages, 'get_user_moodle_client', AsyncMock(return_value=object()))
    create = AsyncMock(side_effect=TimeoutError('response lost'))
    monkeypatch.setattr(stages, 'create_activity', create)
    for _ in range(2):
        with pytest.raises(AmbiguousDeploymentError) as caught: await stages.deploy_stage(ctx)
        assert not retryable(caught.value)
    assert create.await_count == 1
    assert (await get_stage(job.lecture_id, 'moodle_create'))['status'] == 'running'


async def test_moodle_reuses_cmid_after_video_upload_failure(make_lecture, monkeypatch):
    queue, job = await ready(make_lecture, upload_to_moodle=True, moodle_course_id=7, moodle_section_num=0)
    monkeypatch.setattr(stages, 'get_user_moodle_client', AsyncMock(return_value=object()))
    create = AsyncMock(return_value={'cmid': 42, 'success': True})
    monkeypatch.setattr(stages, 'create_activity', create)
    attach = AsyncMock(side_effect=[TimeoutError('upload interrupted'), {'success': True}])
    monkeypatch.setattr(stages, 'set_video_from_file', attach)
    ctx = stages.StageContext(job, queue, await get_lecture(job.lecture_id), outputs={'compose': {'video': 'fake.mp4'}})
    with pytest.raises(TimeoutError): await stages.deploy_stage(ctx)
    restored = stages.StageContext(job, queue, await get_lecture(job.lecture_id), outputs=ctx.outputs)
    result = await stages.deploy_stage(restored)
    assert result['result']['cmid'] == 42
    assert create.await_count == 1


async def test_truncated_concatenated_video_is_rejected(monkeypatch, tmp_path):
    from modules.lecture import composer
    monkeypatch.setattr(composer, 'detect_video_encoder', AsyncMock(return_value='libx264'))
    monkeypatch.setattr(composer, 'run_process', AsyncMock(return_value=''))
    # Four valid 0.2-second segments, but concat silently produced only one.
    monkeypatch.setattr(composer, 'media_duration', AsyncMock(side_effect=[0.2] * 9))
    with pytest.raises(RuntimeError, match='합쳐진 슬라이드 영상 길이'):
        await composer.build_slides_video(slide_pngs=[tmp_path / f'{i}.png' for i in range(4)],
                                          slide_audio_paths=[tmp_path / f'{i}.wav' for i in range(4)],
                                          output_dir=tmp_path)


async def test_due_publish_waits_for_final_video_without_spending_attempt(
    make_lecture, tmp_path, monkeypatch
):
    lecture_id = await make_lecture(
        upload_to_moodle=True,
        moodle_course_id=7,
        moodle_section_num=0,
    )
    await create_publish_schedule_config(
        lecture_id=lecture_id,
        user_id=1,
        mode="exact",
        weekday=None,
        hour=None,
        minute=0,
        timezone="Asia/Seoul",
        scheduled_at="2000-01-01 00:00:00",
    )

    await publish_scheduler._run_one(lecture_id)

    schedule = await get_publish_schedule(lecture_id)
    assert schedule is not None
    assert schedule["status"] == "pending"
    assert schedule["attempts"] == 0
    assert schedule["lease_token"] is None
    lecture = await get_lecture(lecture_id)
    assert "영상 생성 완료 대기" in lecture["status_message"]

    final_video = tmp_path / "final.mp4"
    final_video.write_bytes(b"video")
    await update_lecture(lecture_id, final_video_path=str(final_video))
    deploy = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(publish_scheduler, "deploy_lecture_to_moodle", deploy)

    await publish_scheduler._run_one(lecture_id)
    schedule = await get_publish_schedule(lecture_id)
    assert schedule["status"] == "published"
    assert schedule["attempts"] == 1
    deploy.assert_awaited_once()
