from pathlib import Path

from core.moodle.client import MoodleClient


async def create_activity(
    *,
    client: MoodleClient,
    course_id: int,
    section_num: int,
    name: str,
    intro: str = "",
):
    """
    Create a new Moodle mod_videotracker activity.

    Requires the Moodle plugin external function:
        mod_videotracker_create_activity
    """
    result = await client.call(
        "mod_videotracker_create_activity",
        courseid=int(course_id),
        sectionnum=int(section_num),
        name=name,
        intro=intro,
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "mod_videotracker_create_activity "
            "returned an unexpected response."
        )

    if not result.get("success"):
        raise RuntimeError(
            "VideoTracker activity creation failed: "
            f"{result}"
        )

    cmid = result.get("cmid")

    if not cmid:
        raise RuntimeError(
            "VideoTracker was created but "
            "CMID was not returned."
        )

    return result


async def set_video_from_file(
    *,
    client: MoodleClient,
    cmid: int,
    path: str | Path,
):
    """
    Upload local MP4 into Moodle draft storage and attach it
    to the target custom VideoTracker activity.
    """
    uploaded = await client.upload_file(
        path
    )

    if not uploaded:
        raise RuntimeError(
            "Moodle upload.php returned no file."
        )

    first = uploaded[0]

    draftitemid = (
        first.get("itemid")
        or first.get("draftitemid")
    )

    if not draftitemid:
        raise RuntimeError(
            "Could not resolve Moodle draft item id: "
            f"{first}"
        )

    return await client.call(
        "mod_videotracker_set_video",
        cmid=int(cmid),
        draftitemid=int(
            draftitemid
        ),
    )


async def create_activity_and_set_video(
    *,
    client: MoodleClient,
    course_id: int,
    section_num: int,
    name: str,
    intro: str,
    video_path: str | Path,
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
    )

    return {
        "activity": created,
        "video": uploaded,
    }
