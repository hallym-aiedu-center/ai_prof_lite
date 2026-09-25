"""Attach a verified existing Moodle activity after an ambiguous create response."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from core.database.client import get_connection
from core.database.migrations import init_database
from core.jobs.factory import get_queue
from modules.lecture.repository import get_lecture, get_publish_schedule
from modules.moodle.courses.service import get_videotrackers
from modules.moodle.service import get_user_moodle_client


async def _verify_cmid(lecture: dict, cmid: int) -> None:
    if not lecture.get("moodle_course_id"):
        raise ValueError("Moodle 강좌가 설정된 강의만 복구할 수 있습니다.")
    client = await get_user_moodle_client(int(lecture["user_id"]))
    trackers = await get_videotrackers(client, int(lecture["moodle_course_id"]))
    if not any(int(item["cmid"]) == cmid for item in trackers):
        raise ValueError("CMID가 이 강의의 Moodle 강좌에 속하지 않습니다.")


async def resolve(lecture_id: int, cmid: int) -> None:
    await init_database()
    lecture = await get_lecture(lecture_id)
    if not lecture:
        raise ValueError("강의를 찾을 수 없습니다.")

    schedule = await get_publish_schedule(lecture_id)
    scheduled_ambiguity = bool(
        schedule
        and schedule.get("status") == "failed"
        and schedule.get("create_state") == "running"
    )
    worker_ambiguity = lecture.get("status") == "failed"
    if not scheduled_ambiguity and not worker_ambiguity:
        raise ValueError("Moodle 생성 결과가 불확실한 실패 작업만 복구할 수 있습니다.")

    await _verify_cmid(lecture, cmid)

    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            """
            UPDATE lectures
            SET moodle_videotracker_cmid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (cmid, lecture_id),
        )

        if scheduled_ambiguity:
            result = json.dumps(
                {"cmid": cmid, "resolved_manually": True},
                ensure_ascii=False,
            )
            cursor = await db.execute(
                """
                UPDATE lecture_publish_schedules
                SET create_state = 'completed',
                    create_result_json = ?,
                    status = 'pending',
                    scheduled_at = CURRENT_TIMESTAMP,
                    lease_token = NULL,
                    lease_until = NULL,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE lecture_id = ?
                  AND status = 'failed'
                  AND create_state = 'running'
                """,
                (result, lecture_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("예약 게시 상태가 변경되었습니다. 다시 확인하세요.")

        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()

    if scheduled_ambiguity:
        print(f"Lecture {lecture_id}: CMID {cmid} 확인 완료, 예약 업로드 재시도 대기 중")
        return

    if not await get_queue().retry(lecture_id):
        raise RuntimeError("재시도 대기열로 이동하지 못했습니다. 작업 상태를 확인하세요.")
    print(f"Lecture {lecture_id}: CMID {cmid} 확인 완료, 강의 작업 재시도 대기 중")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lecture-id", type=int, required=True)
    parser.add_argument("--cmid", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(resolve(args.lecture_id, args.cmid))
