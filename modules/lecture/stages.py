import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.config import data_dir
from core.jobs.base import Job, JobQueue, LeaseLost
from modules.credentials.required import require_user_openai_api_key
from modules.image.service import generate_image
from modules.lecture.avatar import create_avatar_video, get_ditto_paths
from modules.lecture.background import prepare_avatar_source
from modules.lecture.checkpoints import get_stage, save_stage
from modules.lecture.composer import (
    build_slides_video,
    compose_final_video,
    media_duration,
)
from modules.lecture.narration import build_narration
from modules.lecture.moodle_deployment import (
    MoodleCreateState,
    MoodleDeploymentSpec,
    deploy_moodle_video,
)
from modules.lecture.planner import create_lecture_plan, expand_lecture_narrations
from modules.lecture.references import build_reference_context
from modules.lecture.repository import get_publish_schedule, update_lecture
from modules.lecture.slides import build_slide_assets, use_image_model_slide_rendering
from modules.moodle.service import get_user_moodle_client
from modules.moodle.videotracker.service import create_activity, set_video_from_file


@dataclass
class StageContext:
    job: Job
    queue: JobQueue
    lecture: dict
    outputs: dict = field(default_factory=dict)
    api_key: str = field(default='', repr=False)

    @property
    def directory(self):
        # A paused, expired process must never overwrite another attempt's media.
        return data_dir() / 'lectures' / str(self.job.lecture_id) / 'runs' / self.job.token

    @property
    def cache_directory(self):
        # Content-addressed paid-call artifacts may be shared across attempts.
        # Final media remains isolated by run_token in ``directory`` above.
        return data_dir() / 'lectures' / str(self.job.lecture_id) / 'cache'

    async def check(self):
        if not await self.queue.owns(self.job):
            raise LeaseLost('작업 소유권이 변경되었습니다.')

    async def update(self, **values):
        await self.check()
        await update_lecture(self.job.lecture_id, run_token=self.job.token, **values)
        self.lecture.update(values)

    async def checkpoint(self, name, status, outputs):
        await self.check()
        await save_stage(self.job.lecture_id, name, status, outputs, run_token=self.job.token)

    async def preflight(self):
        await self.check()
        done = set()
        for name, *_ in STAGES:
            saved = await get_stage(self.job.lecture_id, name)
            if saved and saved['status'] == 'completed':
                done.add(name)
        # Validate prerequisites of unfinished stages before making paid calls.
        if not {'narration', 'timeline', 'compose'} <= done:
            for command in (os.getenv('FFMPEG_BIN', 'ffmpeg'), os.getenv('FFPROBE_BIN', 'ffprobe')):
                if not shutil.which(command):
                    raise FileNotFoundError(f'필수 실행 파일이 없습니다: {command}')
        if 'avatar' not in done:
            ditto, data, config = get_ditto_paths()
            for path in (ditto / 'inference.py', data, config, Path(self.lecture.get('portrait_path') or 'missing')):
                if not path.exists():
                    raise FileNotFoundError(f'필수 파일이 없습니다: {path}')
        if not {'plan', 'images', 'narration'} <= done:
            self.api_key = await require_user_openai_api_key(self.lecture['user_id'])
        if self.lecture['upload_to_moodle']:
            client = await get_user_moodle_client(self.lecture['user_id'])
            await client.validate_target()
        self.directory.mkdir(parents=True, exist_ok=True)


def verify_files(outputs):
    for filename in outputs.get('files', []):
        path = Path(filename)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f'저장된 단계의 산출물이 없습니다: {path}. 원본 파일을 복원하세요.')


async def run_stage(ctx, name, progress, message, stage):
    await ctx.check()
    checkpoint = await get_stage(ctx.job.lecture_id, name)
    if checkpoint and checkpoint['status'] == 'completed':
        verify_files(checkpoint['outputs'])
        ctx.outputs[name] = checkpoint['outputs']
        return
    await ctx.update(progress=progress, status_message=message)
    await ctx.checkpoint(name, 'running', {})
    outputs = await stage(ctx)
    verify_files(outputs)
    await ctx.checkpoint(name, 'completed', outputs)
    ctx.outputs[name] = outputs


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def plan_stage(ctx):
    source_files = ctx.lecture.get("source_files_json") or []
    reference_mode = str(ctx.lecture.get("reference_mode") or "rag").lower()
    reference_context = ""
    if source_files and reference_mode == "rag":
        reference_context = await build_reference_context(
            source_files,
            title=ctx.lecture["title"],
            topic=ctx.lecture["topic"],
            api_key=ctx.api_key,
            user_id=int(ctx.lecture["user_id"]),
            lecture_id=int(ctx.job.lecture_id),
        )

    plan = await create_lecture_plan(
        api_key=ctx.api_key,
        title=ctx.lecture['title'],
        topic=ctx.lecture['topic'],
        model=ctx.lecture['text_model'],
        target_duration_minutes=int(ctx.lecture.get('target_duration_minutes') or 40),
        target_slide_count=int(ctx.lecture.get('target_slide_count') or 10),
        reference_context=reference_context,
        reference_files=source_files if reference_mode == "full" else None,
        reference_mode=reference_mode,
        user_id=int(ctx.lecture["user_id"]),
        lecture_id=int(ctx.job.lecture_id),
    )
    plan_path, quiz_path = ctx.directory / 'lecture_plan.json', ctx.directory / 'quiz.json'
    await ctx.check()
    write_json(plan_path, plan)
    write_json(quiz_path, plan['quiz'])
    await ctx.update(plan_json=plan, quiz_json=plan['quiz'])
    return {'plan': plan, 'files': [str(plan_path), str(quiz_path)]}


_IMAGE_SIZE = "1536x1024"
_IMAGE_QUALITY = "medium"


def _image_cache_key(*, slide_index: int, model: str, prompt: str) -> str:
    # Stable across retries, but distinct per slide even when prompts match.
    payload = (
        f"v2\0{slide_index}\0{model}\0{_IMAGE_SIZE}\0{_IMAGE_QUALITY}\0{prompt}"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _copy_image_atomic(source: Path, destination: Path) -> bool:
    if not source.is_file() or source.stat().st_size <= 0:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


async def image_stage(ctx):
    if use_image_model_slide_rendering() and bool(ctx.lecture['generate_images']):
        slides = ctx.outputs['plan']['plan']['slides']
        return {'images': [None for _ in slides], 'files': []}

    paths = []
    cache_dir = ctx.cache_directory / 'images'
    for index, slide in enumerate(ctx.outputs['plan']['plan']['slides'], 1):
        await ctx.check()
        image_prompt = str(slide.get('image_prompt') or '').strip()
        if ctx.lecture['generate_images'] and image_prompt:
            path = ctx.directory / 'images' / f'slide_{index:03d}.png'
            prompt = image_prompt + '\\nEducational visual. No text or logos.'
            cache_path = cache_dir / (
                _image_cache_key(
                    slide_index=index,
                    model=ctx.lecture['image_model'],
                    prompt=prompt,
                ) + '.png'
            )

            # Run outputs remain isolated by run_token, but paid image results are
            # content-addressed and shared across attempts for this lecture.
            if not path.is_file() or path.stat().st_size <= 0:
                if not _copy_image_atomic(cache_path, path):
                    await generate_image(
                        api_key=ctx.api_key,
                        model=ctx.lecture['image_model'],
                        prompt=prompt,
                        output_path=path,
                        size=_IMAGE_SIZE,
                        quality=_IMAGE_QUALITY,
                        user_id=int(ctx.lecture["user_id"]),
                        lecture_id=int(ctx.job.lecture_id),
                    )
                    _copy_image_atomic(path, cache_path)
            elif not cache_path.is_file() or cache_path.stat().st_size <= 0:
                # Backfill the shared cache if an older/current attempt already has
                # a complete run-local image but no cache entry yet.
                _copy_image_atomic(path, cache_path)
            paths.append(str(path))
        else:
            paths.append(None)
    return {'images': paths, 'files': [p for p in paths if p]}


async def slides_stage(ctx):
    pptx, pngs = await build_slide_assets(
        api_key=ctx.api_key,
        title=ctx.lecture['title'],
        plan=ctx.outputs['plan']['plan'],
        output_dir=ctx.directory / 'slides',
        image_model=ctx.lecture['image_model'],
        generate_images=bool(ctx.lecture['generate_images']),
        image_paths=[Path(p) if p else None for p in ctx.outputs['images']['images']],
        avatar_source_path=Path(ctx.lecture['portrait_path']) if ctx.lecture.get('portrait_path') else None,
        cache_dir=ctx.cache_directory / 'slides',
        user_id=int(ctx.lecture["user_id"]),
        lecture_id=int(ctx.job.lecture_id),
    )

    await ctx.update(pptx_path=str(pptx))
    return {'pptx': str(pptx), 'pngs': list(map(str, pngs)), 'files': [str(pptx), *map(str, pngs)]}


def _duration_max_retries() -> int:
    try:
        value = int(os.getenv("LECTURE_DURATION_MAX_RETRIES", "3"))
    except ValueError:
        value = 3
    return max(0, min(5, value))


def _minimum_duration_seconds(ctx) -> float:
    minutes = max(1, int(ctx.lecture.get("target_duration_minutes") or 40))
    return float(minutes * 60)


async def narration_stage(ctx):
    minimum_seconds = _minimum_duration_seconds(ctx)
    max_retries = _duration_max_retries()
    plan = ctx.outputs['plan']['plan']
    duration = 0.0
    narration = None
    audios = []

    for attempt in range(max_retries + 1):
        narration, audios = await build_narration(
            api_key=ctx.api_key,
            plan=plan,
            output_dir=ctx.directory / 'audio',
            model=ctx.lecture['tts_model'],
            voice=ctx.lecture['tts_voice'],
            check_lease=ctx.check,
            cache_dir=ctx.cache_directory / 'tts',
            user_id=int(ctx.lecture["user_id"]),
            lecture_id=int(ctx.job.lecture_id),
        )
        duration = await media_duration(narration)
        if duration >= minimum_seconds:
            break

        if attempt >= max_retries:
            raise RuntimeError(
                '목표 강의시간을 충족하지 못했습니다. '
                f'목표={minimum_seconds / 60:.1f}분, 실제={duration / 60:.1f}분, '
                f'보강 시도={max_retries}회'
            )

        await ctx.check()
        await ctx.update(
            status_message=(
                '강의 시간이 부족해 설명을 보강하는 중 '
                f'({duration / 60:.1f}/{minimum_seconds / 60:.1f}분, '
                f'{attempt + 1}/{max_retries}회)'
            )
        )
        plan = await expand_lecture_narrations(
            api_key=ctx.api_key,
            plan=plan,
            model=ctx.lecture['text_model'],
            actual_duration_seconds=duration,
            minimum_duration_seconds=minimum_seconds,
            attempt=attempt + 1,
            user_id=int(ctx.lecture["user_id"]),
            lecture_id=int(ctx.job.lecture_id),
        )

        # Keep the corrected narration durable across worker retries.  Slides and
        # quiz content are untouched, so already-rendered slide assets remain valid.
        ctx.outputs['plan']['plan'] = plan
        plan_path = ctx.directory / 'lecture_plan.json'
        write_json(plan_path, plan)
        await ctx.update(plan_json=plan)
        await ctx.checkpoint('plan', 'completed', ctx.outputs['plan'])

    assert narration is not None
    await ctx.update(narration_path=str(narration))
    return {
        'narration': str(narration),
        'audios': list(map(str, audios)),
        'duration': duration,
        'target_duration': minimum_seconds,
        'duration_corrections': attempt,
        'files': [str(narration), *map(str, audios)],
    }


async def timeline_stage(ctx):
    path = await build_slides_video(slide_pngs=list(map(Path, ctx.outputs['slides']['pngs'])),
                                    slide_audio_paths=list(map(Path, ctx.outputs['narration']['audios'])),
                                    output_dir=ctx.directory)
    await ctx.update(slides_video_path=str(path))
    return {'video': str(path), 'files': [str(path)]}


async def avatar_stage(ctx):
    prepared = await asyncio.to_thread(
        prepare_avatar_source,
        source_path=Path(ctx.lecture['portrait_path']),
        output_dir=ctx.directory / 'avatar_source',
    )
    await ctx.check()
    path = await create_avatar_video(portrait_path=prepared.ditto_source,
                                     narration_audio=Path(ctx.outputs['narration']['narration']),
                                     output_path=ctx.directory / 'avatar.mp4')
    await ctx.update(avatar_path=str(path))
    files = [str(path), str(prepared.ditto_source)]
    if prepared.transparent_foreground is not None:
        files.append(str(prepared.transparent_foreground))
    return {
        'video': str(path),
        'chroma_color': prepared.chroma_color,
        'input_mode': prepared.input_mode,
        'files': files,
    }


async def compose_stage(ctx):
    path = await compose_final_video(slides_video=Path(ctx.outputs['timeline']['video']),
                                     avatar_video=Path(ctx.outputs['avatar']['video']),
                                     narration_audio=Path(ctx.outputs['narration']['narration']),
                                     output_path=ctx.directory / 'final_lecture.mp4',
                                     chroma_color=ctx.outputs['avatar']['chroma_color'])
    duration = await media_duration(path)
    minimum_seconds = _minimum_duration_seconds(ctx)
    if duration < minimum_seconds:
        raise RuntimeError(
            '최종 강의 영상이 목표 강의시간보다 짧습니다. '
            f'목표={minimum_seconds / 60:.1f}분, 실제={duration / 60:.1f}분'
        )
    await ctx.update(final_video_path=str(path))
    return {
        'video': str(path),
        'duration': duration,
        'target_duration': minimum_seconds,
        'files': [str(path)],
    }


class _StageMoodleCreateMarker:
    def __init__(self, ctx: StageContext):
        self.ctx = ctx

    async def load(self) -> MoodleCreateState:
        previous = await get_stage(self.ctx.job.lecture_id, "moodle_create")
        if not previous:
            return MoodleCreateState()
        if previous["status"] == "completed":
            activity = (previous.get("outputs") or {}).get("activity")
            return MoodleCreateState(status="completed", activity=activity)
        return MoodleCreateState(status="running")

    async def mark_running(self) -> None:
        await self.ctx.checkpoint("moodle_create", "running", {})

    async def mark_completed(self, activity: dict) -> None:
        await self.ctx.checkpoint("moodle_create", "completed", {"activity": activity})


async def deploy_stage(ctx):
    lecture = ctx.lecture
    if not lecture["upload_to_moodle"]:
        return {"result": None}

    # AI Instructor can generate a lecture ahead of its class time. Once a
    # publish row exists, publish_scheduler exclusively owns Moodle deployment.
    schedule = await get_publish_schedule(ctx.job.lecture_id)
    if schedule:
        return {
            "result": None,
            "scheduled_publish": True,
            "scheduled_at": schedule.get("scheduled_at"),
            "publish_status": schedule.get("status"),
        }

    await ctx.check()
    video_path = ctx.outputs["compose"]["video"]
    duration = ctx.outputs["compose"].get("duration")
    if duration is None:
        # Backward compatibility for checkpoints created before duration was
        # recorded in compose-stage outputs.
        video_file = Path(video_path)
        if video_file.is_file():
            duration = await media_duration(video_file)

    spec = MoodleDeploymentSpec.from_lecture(
        lecture,
        video_path=video_path,
        duration=duration,
    )
    result = await deploy_moodle_video(
        spec,
        marker=_StageMoodleCreateMarker(ctx),
        get_client=get_user_moodle_client,
        create_activity=create_activity,
        set_video_from_file=set_video_from_file,
    )

    if result.cmid != lecture.get("moodle_videotracker_cmid"):
        await ctx.update(moodle_videotracker_cmid=result.cmid)
    payload = result.as_dict()
    await ctx.update(moodle_result_json=payload)
    return {"result": payload}


STAGES = (
    ('plan', 10, '강의 구성과 퀴즈 생성 중', plan_stage),
    ('images', 22, '슬라이드 시각자료 생성 중', image_stage),
    ('slides', 42, 'PPT와 슬라이드 생성 중', slides_stage),
    ('narration', 50, '설명 음성 생성 중', narration_stage),
    ('timeline', 65, '슬라이드 영상 생성 중', timeline_stage),
    ('avatar', 73, 'Ditto TalkingHead 생성 중', avatar_stage),
    ('compose', 86, '최종 강의 영상 합성 중', compose_stage),
    ('deploy', 96, 'Moodle 배포 중', deploy_stage),
)
