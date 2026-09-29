"""Small orchestrator; stages and durable checkpoints own individual steps."""

from core.jobs.base import Job, JobQueue
from modules.lecture.cleanup import cleanup_lecture_runs
from modules.lecture.repository import get_lecture
from modules.lecture.stages import STAGES, StageContext, run_stage


async def run_lecture_job(job: Job, queue: JobQueue) -> str:
    lecture = await get_lecture(job.lecture_id)
    if not lecture:
        raise ValueError("강의를 찾을 수 없습니다.")
    if lecture["status"] == "completed":
        return  # Crash after pipeline completion but before queue acknowledgement.
    context = StageContext(job=job, queue=queue, lecture=lecture)
    await cleanup_lecture_runs(job.lecture_id, preserve_tokens={job.token})
    await context.preflight()
    for name, progress, message, stage in STAGES:
        await run_stage(context, name, progress, message, stage)
        if (
            name == "slides"
            and bool(context.lecture.get("review_before_video"))
            and context.lecture.get("review_status") != "approved"
        ):
            await context.update(
                status="awaiting_review",
                progress=max(int(context.lecture.get("progress") or 0), 45),
                status_message="PPT 검토 대기 중 · 승인하면 영상 생성을 이어갑니다.",
                error_message=None,
                review_status="awaiting_review",
            )
            return "awaiting_review"
    await context.update(
        status="completed",
        progress=100,
        status_message="강의 생성이 완료되었습니다.",
        error_message=None,
    )
    await cleanup_lecture_runs(job.lecture_id, preserve_tokens={job.token})
    return "completed"
