from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
)
from modules.credentials.service import list_user_credentials
from modules.lecture.repository import list_lectures
from modules.users.service import get_user


router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT / "templates"))


@router.get("/")
async def root(request: Request):
    if current_user_id(request):
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return RedirectResponse(
        url="/login",
        status_code=303,
    )


@router.get("/dashboard")
async def dashboard(request: Request):
    user_id = current_user_id(request)

    if user_id is None:
        return login_redirect()

    user = await get_user(user_id)
    credentials = await list_user_credentials(user_id)
    lectures = await list_lectures(
        user_id=user_id,
        limit=8,
    )

    provider_map = {
        row["provider"]: row
        for row in credentials
    }

    provider_status = [
        {
            "key": "openai",
            "name": "OpenAI",
            "connected": "openai" in provider_map,
            "detail": "강의 설계 · 이미지 · 음성",
        },
        {
            "key": "moodle",
            "name": "Moodle",
            "connected": "moodle" in provider_map,
            "detail": "VideoTracker · Quiz · LMS",
        },
        {
            "key": "google",
            "name": "Google",
            "connected": "google" in provider_map,
            "detail": "OAuth 연결",
        },
        {
            "key": "github",
            "name": "GitHub",
            "connected": "github" in provider_map,
            "detail": "개발 연동",
        },
    ]

    completed = sum(
        1 for item in lectures
        if item["status"] == "completed"
    )
    running = sum(
        1 for item in lectures
        if item["status"] in {"queued", "running"}
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": user,
            "active_page": "dashboard",
            "csrf_token": get_csrf_token(request),
            "provider_status": provider_status,
            "connected_count": len(credentials),
            "lectures": lectures,
            "completed_count": completed,
            "running_count": running,
        },
    )
