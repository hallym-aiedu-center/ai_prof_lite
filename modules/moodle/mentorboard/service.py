from core.moodle.client import MoodleClient


async def get_posts(
    client: MoodleClient,
    *,
    cmid: int,
):
    return await client.call(
        "mod_mentorboard_get_posts",
        cmid=int(cmid),
    )


async def create_post(
    client: MoodleClient,
    *,
    cmid: int,
    subject: str,
    message: str,
    draftitemid: int = 0,
):
    return await client.call(
        "mod_mentorboard_create_post",
        cmid=int(cmid),
        subject=subject,
        message=message,
        draftitemid=int(draftitemid),
    )
