from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

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
from modules.users.service import get_user
from core.moodle.url_policy import parse_base_url, resolve_target


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


@router.get("/credentials")
async def credentials_page(request: Request):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    user = await get_user(user_id)
    credentials = await list_user_credentials(user_id)

    connected = {
        row["provider"]: row
        for row in credentials
    }

    return templates.TemplateResponse(
        request=request,
        name="settings/credentials.html",
        context={
            "user": user,
            "active_page": "credentials",
            "csrf_token": get_csrf_token(request),
            "providers": PROVIDERS,
            "connected": connected,
            "saved_provider": request.query_params.get("saved"),
            "removed_provider": request.query_params.get("removed"),
        },
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
        return RedirectResponse(
            url="/settings/credentials",
            status_code=303,
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
        return RedirectResponse(
            url="/settings/credentials",
            status_code=303,
        )

    metadata = {}

    if provider == "moodle":
        resolved_url = base_url.strip()

        if not resolved_url and existing:
            resolved_url = (
                existing["metadata"].get("base_url", "")
            )

        try:
            metadata["base_url"] = str(parse_base_url(resolved_url)).rstrip('/')
            await resolve_target(metadata["base_url"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    await revoke_user_credential(
        user_id=user_id,
        provider=provider,
    )

    return RedirectResponse(
        url=f"/settings/credentials?removed={provider}",
        status_code=303,
    )
