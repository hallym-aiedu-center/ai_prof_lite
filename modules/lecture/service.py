"""Small orchestrator; stages and durable checkpoints own individual steps."""
from core.jobs.base import Job, JobQueue
from modules.lecture.cleanup import cleanup_lecture_runs
from modules.lecture.repository import get_lecture
from modules.lecture.stages import STAGES, StageContext, run_stage


async def run_lecture_job(job: Job, queue: JobQueue) -> None:
    lecture = await get_lecture(job.lecture_id)
    if not lecture:
        raise ValueError('강의를 찾을 수 없습니다.')
    if lecture['status'] == 'completed':
        return  # Crash after pipeline completion but before queue acknowledgement.
    context = StageContext(job=job, queue=queue, lecture=lecture)
    await cleanup_lecture_runs(job.lecture_id, preserve_tokens={job.token})
    await context.preflight()
    for name, progress, message, stage in STAGES:
        await run_stage(context, name, progress, message, stage)
    await context.update(status='completed', progress=100,
                         status_message='강의 생성이 완료되었습니다.', error_message=None)
    await cleanup_lecture_runs(job.lecture_id, preserve_tokens={job.token})
