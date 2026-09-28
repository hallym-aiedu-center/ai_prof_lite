import json

from core.database.client import get_connection
from core.jobs.sqlite import SQLiteJobQueue
from modules.lecture.checkpoints import save_stage
from modules.lecture.repository import get_lecture, update_lecture
from modules.lecture.review import approve_review, update_review_plan


async def test_ppt_edit_invalidates_video_stages_and_resume_requeues(make_lecture, plan):
    lecture_id = await make_lecture(review_before_video=True)
    queue = SQLiteJobQueue()
    await queue.enqueue(lecture_id)
    job = await queue.claim("review-test")
    assert job is not None

    await save_stage(lecture_id, "plan", "completed", {"plan": plan, "files": []}, run_token=job.token)
    await save_stage(lecture_id, "slides", "completed", {"pptx": "x.pptx", "pngs": [], "files": []}, run_token=job.token)
    await update_lecture(
        lecture_id,
        run_token=job.token,
        status="awaiting_review",
        review_status="awaiting_review",
        plan_json=plan,
    )
    assert await queue.pause_for_review(job)

    edited = json.loads(json.dumps(plan))
    edited["slides"][0]["title"] = "사용자가 수정한 제목"
    await update_review_plan(lecture_id, edited)

    db = await get_connection()
    try:
        stages = await (await db.execute(
            "SELECT name FROM lecture_stages WHERE lecture_id=? ORDER BY name", (lecture_id,)
        )).fetchall()
    finally:
        await db.close()
    assert [row["name"] for row in stages] == ["plan"]

    # Editing causes a slide rebuild first; after the regenerated PPT is shown,
    # approval resumes the same durable queue job for video generation.
    await update_lecture(lecture_id, status="awaiting_review", review_status="awaiting_review")
    assert await approve_review(lecture_id)
    assert await queue.resume_review(lecture_id)
    lecture = await get_lecture(lecture_id)
    assert lecture["status"] == "queued"
    assert lecture["review_status"] == "approved"
