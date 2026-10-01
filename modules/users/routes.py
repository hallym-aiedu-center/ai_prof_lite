from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from core.config import openai_key_mode
from core.lang import AUTO_LANGUAGE, SUPPORTED_LANGUAGES, resolve_language, translate
from core.openai.usage import list_usage_events, usage_summary
from core.templates import templates
from modules.auth.service import verify_user_password
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from modules.users.service import (
    delete_account,
    get_user,
    update_language,
    update_profile,
)

router = APIRouter(prefix="/settings")


@router.get("/profile")
async def profile_page(request: Request):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    user = await get_user(user_id)

    return templates.TemplateResponse(
        request=request,
        name="settings/profile.html",
        context={
            "user": user,
            "active_page": "profile",
            "csrf_token": get_csrf_token(request),
            "saved": request.query_params.get("saved") == "1",
            "openai_usage": await usage_summary(user_id),
            "openai_server_mode": openai_key_mode() == "server",
            "delete_failed": request.query_params.get("delete_failed") == "1",
        },
    )


@router.post("/profile")
async def save_profile(
    request: Request,
    name: str = Form(""),
    nickname: str = Form(""),
    phone: str = Form(""),
    language: str = Form("auto"),
    openai_budget_usd: str = Form(""),
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)

    allowed_languages = {AUTO_LANGUAGE, *SUPPORTED_LANGUAGES}
    if language not in allowed_languages:
        language = AUTO_LANGUAGE

    if openai_key_mode() == "server":
        current = await get_user(user_id)
        budget = current.get("openai_budget_usd") if current else None
    else:
        budget = None
        if openai_budget_usd.strip():
            try:
                budget = round(float(openai_budget_usd), 2)
            except ValueError as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    422, "OpenAI 비용 한도는 숫자로 입력하세요."
                ) from exc
            if budget <= 0 or budget > 100000:
                from fastapi import HTTPException

                raise HTTPException(
                    422, "OpenAI 비용 한도는 $0 초과 $100,000 이하로 입력하세요."
                )

    await update_profile(
        user_id=user_id,
        name=name,
        nickname=nickname,
        phone=phone,
        language=language,
        openai_budget_usd=budget,
    )

    return RedirectResponse(
        url="/settings/profile?saved=1",
        status_code=303,
    )


@router.post("/language")
async def save_language(
    request: Request,
    language: str = Form(...),
    return_to: str = Form("/dashboard"),
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)

    allowed_languages = {AUTO_LANGUAGE, *SUPPORTED_LANGUAGES}
    if language not in allowed_languages:
        language = AUTO_LANGUAGE

    await update_language(user_id=user_id, language=language)

    # Only allow local redirects. This form is rendered by our own templates,
    # but keep the endpoint safe if it is called directly.
    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/dashboard"

    return RedirectResponse(url=return_to, status_code=303)


@router.get("/openai-usage")
async def openai_usage_page(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()

    return templates.TemplateResponse(
        request=request,
        name="settings/openai_usage.html",
        context={
            "user": await get_user(user_id),
            "active_page": "openai_usage",
            "csrf_token": get_csrf_token(request),
            "openai_usage": await usage_summary(user_id),
            "usage_events": await list_usage_events(user_id, limit=100),
        },
    )


@router.post("/account/delete")
async def delete_account_route(
    request: Request,
    password: str = Form(...),
    confirmation: str = Form(...),
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)
    user = await get_user(user_id)
    language = resolve_language(request, user)
    expected_confirmation = translate("settings.profile.delete_account", language)
    if confirmation.strip() != expected_confirmation:
        return RedirectResponse(
            url="/settings/profile?delete_failed=1",
            status_code=303,
        )
    if not await verify_user_password(user_id=user_id, password=password):
        return RedirectResponse(
            url="/settings/profile?delete_failed=1",
            status_code=303,
        )

    await delete_account(user_id)
    request.session.clear()
    return RedirectResponse(url="/login?account_deleted=1", status_code=303)
