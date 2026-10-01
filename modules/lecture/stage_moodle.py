from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.lecture.checkpoints import get_stage
from modules.lecture.composer import media_duration
from modules.lecture.moodle_deployment import (
    MoodleCreateState,
    MoodleDeploymentSpec,
    MoodleVideoState,
    deploy_moodle_video,
)
from modules.lecture.repository import get_publish_schedule
from modules.moodle.service import get_user_moodle_client
from modules.moodle.videotracker.service import create_activity, set_video_from_file


class _StageMoodleCreateMarker:
    def __init__(self, ctx: Any):
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

    async def load_video(self) -> MoodleVideoState:
        previous = await get_stage(self.ctx.job.lecture_id, "moodle_video")
        if not previous:
            return MoodleVideoState()
        if previous["status"] == "completed":
            return MoodleVideoState(
                status="completed",
                result=(previous.get("outputs") or {}).get("result"),
            )
        return MoodleVideoState(status="running")

    async def mark_video_running(self) -> None:
        await self.ctx.checkpoint("moodle_video", "running", {})

    async def mark_video_completed(self, result) -> None:
        await self.ctx.checkpoint("moodle_video", "completed", {"result": result})


async def deploy_stage(ctx: Any):
    lecture = ctx.lecture
    if not lecture["upload_to_moodle"]:
        return {"result": None}

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
