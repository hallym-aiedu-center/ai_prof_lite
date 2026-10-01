from __future__ import annotations

from typing import Any

from .client import MoodleClient


async def upload(client: MoodleClient, path: str) -> list[dict[str, Any]]:
    return await client.upload_file(path)


async def upload_draft(client: MoodleClient, path: str) -> int:
    uploaded = await client.upload_file(path)
    if not uploaded:
        raise RuntimeError("Moodle file upload returned no draft metadata.")
    first = uploaded[0]
    draft_id = first.get("itemid") or first.get("draftitemid")
    if not draft_id:
        raise RuntimeError(f"Could not resolve Moodle draft item id: {first}")
    return int(draft_id)
