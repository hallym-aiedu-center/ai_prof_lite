from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from core.config import openai_key_mode
from core.moodle.client import get_moodle_client
from core.moodle.exceptions import MoodleAPIError
from core.moodle.url_policy import parse_base_url, resolve_target
from core.openai.client import validate_api_key as validate_openai_api_key
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from modules.credentials.service import (
    get_credential,
    list_user_credentials,
    revoke_user_credential,
    save_credential,
)
from modules.moodle.courses.service import get_site_info
from modules.users.service import get_user

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT / "templates"))


PROVIDERS = {
    "openai": {
        "title": "OpenAI",
        "description": "Responses, Realtime, Image, Audio API",
        "credential_type": "api_key",
        "secret_label": "API Key",
        "secret_placeholder": "sk-...",
    },
    "moodle": {
        "title": "Moodle",
        "description": "LMS REST Web Service",
        "credential_type": "webservice_token",
        "secret_label": "Web Service Token",
        "secret_placeholder": "Moodle token",
    },
    "google": {
        "title": "Google",
        "description": "Google OAuth refresh token",
        "credential_type": "oauth_refresh_token",
        "secret_label": "Refresh Token",
        "secret_placeholder": "OAuth refresh token",
    },
    "github": {
        "title": "GitHub",
        "description": "GitHub personal/access token",
        "credential_type": "access_token",
        "secret_label": "Access Token",
        "secret_placeholder": "ghp_...",
    },
}


def _visible_providers() -> dict:
    if openai_key_mode() == "server":
        return {key: value for key, value in PROVIDERS.items() if key != "openai"}
    return PROVIDERS


async def _credentials_context(
    request: Request,
    user_id: int,
    *,
    error_provider: str | None = None,
    error_message: str | None = None,
    draft_base_url: str = "",
) -> dict:
    user = await get_user(user_id)
    credentials = await list_user_credentials(user_id)
    connected = {row["provider"]: row for row in credentials}
    return {
        "user": user,
        "active_page": "credentials",
        "csrf_token": get_csrf_token(request),
        "providers": _visible_providers(),
        "connected": connected,
        "saved_provider": request.query_params.get("saved"),
        "removed_provider": request.query_params.get("removed"),
        "error_provider": error_provider,
        "error_message": error_message,
        "draft_base_url": draft_base_url,
        "openai_key_mode": openai_key_mode(),
    }


@router.get("/credentials")
async def credentials_page(request: Request):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    return templates.TemplateResponse(
        request=request,
        name="settings/credentials.html",
        context=await _credentials_context(request, user_id),
    )


@router.post("/credentials/{provider}")
async def save_provider(
    request: Request,
    provider: str,
    secret: str = Form(""),
    base_url: str = Form(""),
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)

    spec = PROVIDERS.get(provider)
    if spec is None:
        return RedirectResponse(url="/settings/credentials", status_code=303)
    if provider == "openai" and openai_key_mode() == "server":
        raise HTTPException(
            status_code=403,
            detail="서버 공용 OpenAI API Key 모드에서는 사용자 키를 변경할 수 없습니다.",
        )

    existing = await get_credential(
        user_id=user_id,
        provider=provider,
        credential_type=spec["credential_type"],
    )

    resolved_secret = secret.strip()
    if not resolved_secret and existing:
        resolved_secret = existing["secret"]
    if not resolved_secret:
        return templates.TemplateResponse(
            request=request,
            name="settings/credentials.html",
            context=await _credentials_context(
                request,
                user_id,
                error_provider=provider,
                error_message=f"{spec['secret_label']}를 입력하세요.",
                draft_base_url=base_url.strip(),
            ),
            status_code=422,
        )

    metadata = {}
    resolved_url = ""
    if provider == "moodle":
        resolved_url = base_url.strip()
        if not resolved_url and existing:
            resolved_url = existing["metadata"].get("base_url", "")
        try:
            metadata["base_url"] = str(parse_base_url(resolved_url)).rstrip("/")
            await resolve_target(metadata["base_url"])
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name="settings/credentials.html",
                context=await _credentials_context(
                    request,
                    user_id,
                    error_provider=provider,
                    error_message=str(exc),
                    draft_base_url=resolved_url,
                ),
                status_code=422,
            )

    # Validate credentials before encrypting/persisting them.  Failed secrets are
    # never stored, and the secret itself is never echoed into the response.
    try:
        if provider == "openai":
            await validate_openai_api_key(resolved_secret)
        elif provider == "moodle":
            client = get_moodle_client(
                base_url=metadata["base_url"],
                token=resolved_secret,
            )
            await get_site_info(client)
    except Exception as exc:  # noqa: BLE001
        if provider == "openai":
            message = (
                "OpenAI API Key를 확인할 수 없습니다. 키와 API 접근 권한을 확인하세요."
            )
        else:
            if isinstance(exc, MoodleAPIError):
                error_code = str(exc.payload.get("errorcode") or "").lower()
                if error_code == "invalidtoken":
                    message = "Moodle token이 유효하지 않습니다."
                else:
                    message = "Moodle API 권한 또는 Web Service 설정을 확인하세요."
            else:
                message = "Moodle 서버에 연결할 수 없습니다. URL, TLS 인증서와 네트워크 상태를 확인하세요."
        return templates.TemplateResponse(
            request=request,
            name="settings/credentials.html",
            context=await _credentials_context(
                request,
                user_id,
                error_provider=provider,
                error_message=message,
                draft_base_url=resolved_url,
            ),
            status_code=422,
        )

    await save_credential(
        user_id=user_id,
        provider=provider,
        credential_type=spec["credential_type"],
        secret=resolved_secret,
        metadata=metadata,
    )

    return RedirectResponse(
        url=f"/settings/credentials?saved={provider}",
        status_code=303,
    )


@router.post("/credentials/{provider}/remove")
async def remove_provider(
    request: Request,
    provider: str,
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)

    if provider == "openai" and openai_key_mode() == "server":
        raise HTTPException(
            status_code=403,
            detail="서버 공용 OpenAI API Key 모드에서는 사용자 키를 변경할 수 없습니다.",
        )

    await revoke_user_credential(
        user_id=user_id,
        provider=provider,
    )

    return RedirectResponse(
        url=f"/settings/credentials?removed={provider}",
        status_code=303,
    )
