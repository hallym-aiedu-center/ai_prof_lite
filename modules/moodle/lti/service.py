from __future__ import annotations

from typing import Any

from core.moodle.client import MoodleClient


async def get_ltis(client: MoodleClient, course_ids: list[int] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if course_ids:
        params["courseids"] = course_ids
    return await client.call("mod_lti_get_ltis_by_courses", **params)


async def get_tool_launch_data(client: MoodleClient, tool_id: int) -> dict[str, Any]:
    return await client.call("mod_lti_get_tool_launch_data", toolid=tool_id)
