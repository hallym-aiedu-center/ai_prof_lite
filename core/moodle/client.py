import os
from pathlib import Path
from typing import Any

import httpx

from core.moodle.exceptions import MoodleAPIError
from core.moodle.url_policy import parse_base_url, resolve_target


class MoodleClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 120.0,
        verify_ssl: bool = True,
    ):
        if not base_url:
            raise RuntimeError("Moodle base URL is required.")

        if not token:
            raise RuntimeError("Moodle token is required.")

        self.base_url = str(parse_base_url(base_url)).rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    async def validate_target(self):
        return await resolve_target(self.base_url)

    async def _post(self, endpoint: str, **kwargs):
        pinned, headers, extensions = await self.validate_target()
        async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl,
                                     follow_redirects=False, trust_env=False) as http:
            response = await http.post(str(pinned).rstrip('/') + endpoint,
                                       headers=headers, extensions=extensions, **kwargs)
            if response.is_redirect:
                raise ValueError('Moodle 리다이렉트는 허용하지 않습니다. 최종 HTTPS 주소를 등록하세요.')
            response.raise_for_status()
            return response

    async def call(
        self,
        function: str,
        **params: Any,
    ) -> Any:
        data = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }

        response = await self._post('/webservice/rest/server.php', data=data)

        result = response.json()

        if isinstance(result, dict) and (
            "exception" in result
            or "errorcode" in result
        ):
            raise MoodleAPIError(result)

        return result

    async def upload_file(
        self,
        path: str | Path,
        *,
        field_name: str = "file_1",
    ) -> list[dict]:
        path = Path(path)

        if not path.is_file():
            raise FileNotFoundError(path)

        with path.open("rb") as file_handle:
            files = {
                field_name: (
                    path.name,
                    file_handle,
                    "application/octet-stream",
                )
            }

            response = await self._post('/webservice/upload.php',
                                        data={'token': self.token}, files=files)

        result = response.json()

        if isinstance(result, dict) and (
            "exception" in result
            or "errorcode" in result
        ):
            raise MoodleAPIError(result)

        return result


def get_moodle_client(
    *,
    base_url: str,
    token: str,
) -> MoodleClient:
    """Build a Moodle client from explicitly supplied user-owned credentials."""
    resolved_url = str(base_url or "").strip()
    resolved_token = str(token or "").strip()
    if not resolved_url or not resolved_token:
        raise RuntimeError("Explicit Moodle URL and token are required.")

    verify_ssl = (
        os.getenv("MOODLE_VERIFY_SSL", "true")
        .strip()
        .lower()
        not in {"0", "false", "no"}
    )

    return MoodleClient(
        base_url=resolved_url,
        token=resolved_token,
        timeout=float(os.getenv("MOODLE_TIMEOUT", "120")),
        verify_ssl=verify_ssl,
    )
