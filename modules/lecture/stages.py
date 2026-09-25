import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.config import data_dir
from core.jobs.base import Job, JobQueue, LeaseLost
from core.jobs.errors import AmbiguousDeploymentError
from modules.credentials.required import require_user_openai_api_key
from modules.image.service import generate_image
from modules.lecture.avatar import create_avatar_video, get_ditto_paths
from modules.lecture.background import prepare_avatar_source
from modules.lecture.composer import build_slides_video, compose_final_video
from modules.lecture.narration import build_narration
from modules.lecture.planner import create_lecture_plan
from modules.lecture.checkpoints import get_stage, save_stage
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
    plan = await create_lecture_plan(
        api_key=ctx.api_key,
        title=ctx.lecture['title'],
        topic=ctx.lecture['topic'],
        model=ctx.lecture['text_model'],
        target_duration_minutes=int(ctx.lecture.get('target_duration_minutes') or 40),
        target_slide_count=int(ctx.lecture.get('target_slide_count') or 10),
    )
    plan_path, quiz_path = ctx.directory / 'lecture_plan.json', ctx.directory / 'quiz.json'
    await ctx.check()
    write_json(plan_path, plan)
    write_json(quiz_path, plan['quiz'])
    await ctx.update(plan_json=plan, quiz_json=plan['quiz'])
    return {'plan': plan, 'files': [str(plan_path), str(quiz_path)]}


async def image_stage(ctx):
    if use_image_model_slide_rendering() and bool(ctx.lecture['generate_images']):
        slides = ctx.outputs['plan']['plan']['slides']
        return {'images': [None for _ in slides], 'files': []}

    paths = []
    for index, slide in enumerate(ctx.outputs['plan']['plan']['slides'], 1):
        await ctx.check()
        if ctx.lecture['generate_images'] and slide['image_prompt'].strip():
            path = ctx.directory / 'images' / f'slide_{index:03d}.png'
            # generate_image commits atomically; existing files are complete.
            if not path.is_file() or not path.stat().st_size:
                await generate_image(api_key=ctx.api_key, model=ctx.lecture['image_model'],
                                     prompt=slide['image_prompt'] + '\\nEducational visual. No text or logos.', output_path=path)
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
    )

    await ctx.update(pptx_path=str(pptx))
    return {'pptx': str(pptx), 'pngs': list(map(str, pngs)), 'files': [str(pptx), *map(str, pngs)]}


async def narration_stage(ctx):
    narration, audios = await build_narration(
        api_key=ctx.api_key, plan=ctx.outputs['plan']['plan'], output_dir=ctx.directory / 'audio',
        model=ctx.lecture['tts_model'], voice=ctx.lecture['tts_voice'], check_lease=ctx.check,
    )
    await ctx.update(narration_path=str(narration))
    return {'narration': str(narration), 'audios': list(map(str, audios)),
            'files': [str(narration), *map(str, audios)]}


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
    await ctx.update(final_video_path=str(path))
    return {'video': str(path), 'files': [str(path)]}


async def deploy_stage(ctx):
    lecture = ctx.lecture
    if not lecture['upload_to_moodle']:
        return {'result': None}

    # AI Instructor can generate a lecture ahead of its class time.  In that
    # case the worker must finish media generation now but leave Moodle
    # deployment to publish_scheduler at scheduled_at.
    schedule = await get_publish_schedule(ctx.job.lecture_id)
    if schedule:
        # Once a delayed-publish row exists, publish_scheduler exclusively owns
        # Moodle deployment.  This also prevents a race where the scheduler
        # publishes just before this stage and the worker uploads a second time.
        return {
            'result': None,
            'scheduled_publish': True,
            'scheduled_at': schedule.get('scheduled_at'),
            'publish_status': schedule.get('status'),
        }

    client = await get_user_moodle_client(lecture['user_id'])
    cmid = lecture.get('moodle_videotracker_cmid')
    activity = None
    if lecture['moodle_deploy_mode'] == 'create' and not cmid:
        previous = await get_stage(ctx.job.lecture_id, 'moodle_create')
        if previous and previous['status'] == 'completed':
            activity = previous['outputs']['activity']
            cmid = int(activity['cmid'])
        elif previous:
            raise AmbiguousDeploymentError(
                'Moodle 활동 생성 결과가 불확실합니다. Moodle에서 활동을 확인한 뒤 '
                'scripts/resolve_deployment.py로 CMID를 등록하세요. 자동 중복 생성은 중단했습니다.')
        else:
            # Marker BEFORE the non-idempotent request prevents blind recreation.
            await ctx.checkpoint('moodle_create', 'running', {})
            try:
                activity = await create_activity(client=client, course_id=int(lecture['moodle_course_id']),
                                                 section_num=int(lecture['moodle_section_num']), name=lecture['title'],
                                                 intro='AI Professor Lite에서 자동 생성한 강의 영상입니다.')
            except Exception as exc:
                raise AmbiguousDeploymentError(
                    'Moodle 활동 생성 응답을 확인하지 못했습니다. Moodle에서 생성 여부를 확인하세요.') from exc
            cmid = int(activity['cmid'])
            await ctx.checkpoint('moodle_create', 'completed', {'activity': activity})
        await ctx.update(moodle_videotracker_cmid=cmid)
    if not cmid:
        raise ValueError('Moodle VideoTracker CMID가 없습니다.')
    await ctx.check()
    video = await set_video_from_file(client=client, cmid=int(cmid), path=ctx.outputs['compose']['video'])
    if isinstance(video, dict) and video.get('success') is False:
        raise RuntimeError('Moodle 영상 연결에 실패했습니다.')
    result = {'mode': lecture['moodle_deploy_mode'], 'cmid': cmid, 'activity': activity, 'video': video}
    await ctx.update(moodle_result_json=result)
    return {'result': result}


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
