from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from core.openai.usage import list_usage_events, usage_summary
from modules.users.service import get_user, update_profile

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT / "templates"))


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
            "usage_events": await list_usage_events(user_id, limit=30),
        },
    )


@router.post("/profile")
async def save_profile(
    request: Request,
    name: str = Form(""),
    nickname: str = Form(""),
    phone: str = Form(""),
    language: str = Form("ko"),
    openai_budget_usd: str = Form(""),
    csrf_token: str = Form(...),
):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    verify_csrf(request, csrf_token)

    budget = None
    if openai_budget_usd.strip():
        try:
            budget = round(float(openai_budget_usd), 2)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(422, "OpenAI 비용 한도는 숫자로 입력하세요.") from exc
        if budget <= 0 or budget > 100000:
            from fastapi import HTTPException
            raise HTTPException(422, "OpenAI 비용 한도는 $0 초과 $100,000 이하로 입력하세요.")

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
