from __future__ import annotations

from typing import Any

from core.moodle.client import MoodleClient


async def get_assignments(client: MoodleClient, course_ids: list[int] | None = None, capabilities: list[str] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if course_ids:
        params["courseids"] = course_ids
    if capabilities:
        params["capabilities"] = capabilities
    return await client.call("mod_assign_get_assignments", **params)


async def get_submissions(client: MoodleClient, assignment_ids: list[int] | None = None, status: str = "", since: int = 0, before: int = 0) -> dict[str, Any]:
    params: dict[str, Any] = {"status": status, "since": since, "before": before}
    if assignment_ids:
        params["assignmentids"] = assignment_ids
    return await client.call("mod_assign_get_submissions", **params)


async def get_submission_status(client: MoodleClient, assignment_id: int, user_id: int = 0) -> dict[str, Any]:
    return await client.call(
        "mod_assign_get_submission_status",
        assignid=assignment_id,
        userid=user_id,
    )


async def list_participants(client: MoodleClient, assignment_id: int, *, group_id: int = 0, filter_: str = "", skip: int = 0, limit: int = 0, only_active: bool = False, include_enrolments: bool = True) -> list[dict[str, Any]]:
    return await client.call(
        "mod_assign_list_participants",
        assignid=assignment_id,
        groupid=group_id,
        filter=filter_,
        skip=skip,
        limit=limit,
        onlyactive=only_active,
        includeenrolments=include_enrolments,
    )


async def get_participant(client: MoodleClient, assignment_id: int, user_id: int, *, embed_user: bool = True) -> dict[str, Any]:
    return await client.call(
        "mod_assign_get_participant",
        assignid=assignment_id,
        userid=user_id,
        embeduser=embed_user,
    )


async def get_grades(client: MoodleClient, assignment_ids: list[int] | None = None, since: int = 0) -> dict[str, Any]:
    params: dict[str, Any] = {"since": since}
    if assignment_ids:
        params["assignmentids"] = assignment_ids
    return await client.call("mod_assign_get_grades", **params)


async def save_submission(client: MoodleClient, assignment_id: int, plugindata: dict[str, Any]) -> dict[str, Any]:
    return await client.call(
        "mod_assign_save_submission",
        assignmentid=assignment_id,
        plugindata=plugindata,
    )


async def submit_for_grading(client: MoodleClient, assignment_id: int, accept_submission_statement: bool = False) -> dict[str, Any]:
    return await client.call(
        "mod_assign_submit_for_grading",
        assignmentid=assignment_id,
        acceptsubmissionstatement=accept_submission_statement,
    )


async def save_grade(client: MoodleClient, assignment_id: int, user_id: int, grade: float, *, attempt_number: int = -1, add_attempt: bool = False, workflow_state: str = "", apply_to_all: bool = False, plugindata: dict[str, Any] | None = None) -> dict[str, Any]:
    return await client.call(
        "mod_assign_save_grade",
        assignmentid=assignment_id,
        userid=user_id,
        grade=grade,
        attemptnumber=attempt_number,
        addattempt=add_attempt,
        workflowstate=workflow_state,
        applytoall=apply_to_all,
        plugindata=plugindata or {},
    )
