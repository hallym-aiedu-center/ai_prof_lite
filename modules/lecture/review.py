from __future__ import annotations

import json
import time
from pathlib import Path

from jsonschema import validate

from core.database.client import get_connection
from modules.lecture.planner import lecture_schema_for_slide_count


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def update_review_plan(lecture_id: int, plan: dict) -> None:
    """Persist reviewer edits and invalidate only stages downstream of slides."""
    slides = list(plan.get("slides") or [])
    validate(instance=plan, schema=lecture_schema_for_slide_count(len(slides)))

    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        lecture = await (await db.execute(
            "SELECT status, review_status FROM lectures WHERE id=?", (lecture_id,)
        )).fetchone()
        if not lecture or lecture["status"] != "awaiting_review":
            raise ValueError("PPT 검토 대기 상태에서만 슬라이드를 수정할 수 있습니다.")

        row = await (await db.execute(
            "SELECT outputs_json FROM lecture_stages WHERE lecture_id=? AND name='plan'",
            (lecture_id,),
        )).fetchone()
        if not row:
            raise ValueError("수정할 강의 설계 체크포인트가 없습니다.")
        outputs = json.loads(row["outputs_json"] or "{}")
        outputs["plan"] = plan

        await db.execute(
            """
            UPDATE lecture_stages
            SET outputs_json=?, status='completed', updated_at=CURRENT_TIMESTAMP
            WHERE lecture_id=? AND name='plan'
            """,
            (json.dumps(outputs, ensure_ascii=False), lecture_id),
        )
        await db.execute(
            """
            DELETE FROM lecture_stages
            WHERE lecture_id=? AND name IN ('slides','narration','timeline','avatar','compose','deploy')
            """,
            (lecture_id,),
        )
        await db.execute(
            """
            UPDATE lectures
            SET plan_json=?, quiz_json=?, review_status='pending', pptx_path=NULL,
                narration_path=NULL, slides_video_path=NULL, avatar_path=NULL,
                final_video_path=NULL, moodle_result_json=NULL,
                status_message='수정한 PPT를 다시 생성할 준비 중입니다.',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                json.dumps(plan, ensure_ascii=False),
                json.dumps(plan.get("quiz") or [], ensure_ascii=False),
                lecture_id,
            ),
        )
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()

    for filename in outputs.get("files", []):
        path = Path(filename)
        if path.name == "lecture_plan.json":
            _write_json_atomic(path, plan)
        elif path.name == "quiz.json":
            _write_json_atomic(path, plan.get("quiz") or [])



async def approve_and_resume_review(lecture_id: int) -> bool:
    """PPT 승인과 paused job 재개를 하나의 SQLite 트랜잭션으로 처리한다.

    과거 crash로 review_status='approved'이지만 job이 paused로 남은
    상태도 동일 요청으로 복구한다.
    """
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        now = time.time()

        job_cursor = await db.execute(
            """
            UPDATE lecture_jobs
            SET status='queued',
                available_at=?,
                lease_token=NULL,
                lease_until=NULL,
                worker_id=NULL,
                gpu_id=NULL,
                last_error=NULL,
                updated_at=?
            WHERE lecture_id=?
              AND status='paused'
              AND EXISTS (
                  SELECT 1
                  FROM lectures
                  WHERE id=?
                    AND status='awaiting_review'
                    AND review_status IN ('awaiting_review', 'approved')
              )
            """,
            (now, now, lecture_id, lecture_id),
        )

        if job_cursor.rowcount != 1:
            await db.rollback()
            return False

        lecture_cursor = await db.execute(
            """
            UPDATE lectures
            SET review_status='approved',
                status='queued',
                run_token=NULL,
                error_message=NULL,
                status_message='PPT 승인 · 작업 재개 대기 중',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
              AND status='awaiting_review'
              AND review_status IN ('awaiting_review', 'approved')
            """,
            (lecture_id,),
        )

        if lecture_cursor.rowcount != 1:
            await db.rollback()
            return False

        await db.commit()
        return True

    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def approve_review(lecture_id: int) -> bool:
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            UPDATE lectures
            SET review_status='approved', status_message='PPT 승인 · 영상 생성 재개 대기 중',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='awaiting_review' AND review_status='awaiting_review'
            """,
            (lecture_id,),
        )
        await db.commit()
        return cursor.rowcount == 1
    finally:
        await db.close()
