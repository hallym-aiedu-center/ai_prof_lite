from __future__ import annotations

import os

from core.config import openai_key_mode
from modules.credentials.service import get_credential


class MissingCredentialError(RuntimeError):
    """Raised when a feature requires a user-owned credential that is absent."""


async def require_user_openai_api_key(user_id: int) -> str:
    """Resolve the OpenAI key according to the installation credential policy."""
    if openai_key_mode() == "server":
        secret = os.getenv("SERVER_OPENAI_API_KEY", "").strip()
        if not secret:
            raise MissingCredentialError(
                "서버 OpenAI API Key가 설정되지 않았습니다. 서버 운영자에게 문의하세요."
            )
        return secret

    credential = await get_credential(
        user_id=user_id,
        provider="openai",
        credential_type="api_key",
    )
    secret = str((credential or {}).get("secret") or "").strip()
    if not secret:
        raise MissingCredentialError("OpenAI API Key를 먼저 등록하세요.")
    return secret


async def require_user_moodle_credential(user_id: int) -> tuple[str, str]:
    credential = await get_credential(
        user_id=user_id,
        provider="moodle",
        credential_type="webservice_token",
    )
    if not credential:
        raise MissingCredentialError(
            "Moodle 연결정보를 먼저 등록하세요. 서버 공용 Moodle 자격증명은 사용자 작업에 사용하지 않습니다."
        )

    base_url = (
        str((credential.get("metadata") or {}).get("base_url") or "")
        .strip()
        .rstrip("/")
    )
    token = str(credential.get("secret") or "").strip()
    if not base_url or not token:
        raise MissingCredentialError(
            "Moodle URL과 Web Service Token을 모두 등록하세요."
        )
    return base_url, token
