from __future__ import annotations

from typing import Any

from .client import MoodleClient


async def upload(client: MoodleClient, path: str) -> list[dict[str, Any]]:
    return await client.upload_file(path)


async def upload_draft(client: MoodleClient, path: str) -> int:
    return await client.upload_file_and_get_draft_id(path)
