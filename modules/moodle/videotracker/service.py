import math
from pathlib import Path

from core.moodle.client import MoodleClient


_TRACKER_COMPONENTS = ("videotracker", "simplevideotracker")


async def _resolve_tracker_component(client: MoodleClient) -> str:
    """Return the tracker component exposed by the current Moodle token."""
    cached = getattr(client, "_video_tracker_component", None)
    if cached in _TRACKER_COMPONENTS:
        return cached

    site_info = await client.call("core_webservice_get_site_info")
    functions = site_info.get("functions", []) if isinstance(site_info, dict) else []
    available = {
        item.get("name") if isinstance(item, dict) else item
        for item in functions
    }

    for component in _TRACKER_COMPONENTS:
        required = {
            f"mod_{component}_create_activity",
            f"mod_{component}_set_video",
        }
        if required.issubset(available):
            setattr(client, "_video_tracker_component", component)
            return component

    raise RuntimeError(
        "Moodle token does not expose a compatible VideoTracker web service "
        "(mod_videotracker_* or mod_simplevideotracker_*)."
    )


async def create_activity(
    *,
    client: MoodleClient,
    course_id: int,
    section_num: int,
    name: str,
    intro: str = "",
):
    """
    Create a new Moodle VideoTracker-compatible activity.

    Supports both mod_videotracker and mod_simplevideotracker.
    """
    component = await _resolve_tracker_component(client)
    function = f"mod_{component}_create_activity"

    result = await client.call(
        function,
        courseid=int(course_id),
        sectionnum=int(section_num),
        name=name,
        intro=intro,
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(  # noqa: TRY004
            f"{function} returned an unexpected response."
        )

    if not result.get("success"):
        raise RuntimeError(f"VideoTracker activity creation failed: {result}")

    cmid = result.get("cmid")

    if not cmid:
        raise RuntimeError("VideoTracker was created but CMID was not returned.")

    return result


async def set_video_from_file(
    *,
    client: MoodleClient,
    cmid: int,
    path: str | Path,
    duration: float | None = None,
):
    """
    Upload local MP4 into Moodle draft storage and attach it
    to the target VideoTracker-compatible activity.
    """
    component = await _resolve_tracker_component(client)
    function = f"mod_{component}_set_video"

    duration_value = None
    if duration is not None:
        duration_value = float(duration)
        if not math.isfinite(duration_value) or duration_value <= 0:
            raise ValueError("Video duration must be a finite positive number.")

    uploaded = await client.upload_file(path)

    if not uploaded:
        raise RuntimeError("Moodle upload.php returned no file.")

    first = uploaded[0]

    draftitemid = first.get("itemid") or first.get("draftitemid")

    if not draftitemid:
        raise RuntimeError(f"Could not resolve Moodle draft item id: {first}")

    params = {
        "cmid": int(cmid),
        "draftitemid": int(draftitemid),
    }

    if duration_value is not None:
        params["duration"] = duration_value

    return await client.call(
        function,
        **params,
    )


async def create_activity_and_set_video(
    *,
    client: MoodleClient,
    course_id: int,
    section_num: int,
    name: str,
    intro: str,
    video_path: str | Path,
    duration: float | None = None,
):
    created = await create_activity(
        client=client,
        course_id=course_id,
        section_num=section_num,
        name=name,
        intro=intro,
    )

    uploaded = await set_video_from_file(
        client=client,
        cmid=int(created["cmid"]),
        path=video_path,
        duration=duration,
    )

    return {
        "activity": created,
        "video": uploaded,
    }
