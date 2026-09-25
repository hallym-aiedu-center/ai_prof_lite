from core.moodle.client import MoodleClient


async def get_quizzes_by_courses(
    client: MoodleClient,
    course_ids: list[int],
):
    params = {
        f"courseids[{idx}]": int(course_id)
        for idx, course_id in enumerate(course_ids)
    }

    return await client.call(
        "mod_quiz_get_quizzes_by_courses",
        **params,
    )


async def get_attempt_review(
    client: MoodleClient,
    *,
    attempt_id: int,
):
    return await client.call(
        "mod_quiz_get_attempt_review",
        attemptid=int(attempt_id),
    )
