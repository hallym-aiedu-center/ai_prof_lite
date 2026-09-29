# core/openai/sessions.py

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class RealtimeSession:
    connection: Any
    lock: asyncio.Lock


class RealtimeSessionManager:
    def __init__(self):
        self._sessions: dict[str, RealtimeSession] = {}
        self._lock = asyncio.Lock()

    async def set(self, session_id: str, connection):
        async with self._lock:
            self._sessions[session_id] = RealtimeSession(
                connection=connection,
                lock=asyncio.Lock(),
            )

    async def get(self, session_id: str):
        return self._sessions.get(session_id)

    async def remove(self, session_id: str):
        async with self._lock:
            return self._sessions.pop(session_id, None)


realtime_sessions = RealtimeSessionManager()
