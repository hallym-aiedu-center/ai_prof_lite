from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from modules.auth.service import (
    EmailAlreadyExistsError,
    authenticate_user,
    register_user,
)
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    verify_csrf,
)


router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT / "templates"))


@router.get("/login")
async def login_page(request: Request):
    if current_user_id(request):
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "csrf_token": get_csrf_token(request),
            "error": None,
        },
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)

    user = await authenticate_user(
        email=email,
        password=password,
    )

    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "이메일 또는 비밀번호를 확인하세요.",
                "email": email,
            },
            status_code=400,
        )

    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["csrf_token"] = get_csrf_token(request)

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


@router.get("/register")
async def register_page(request: Request):
    if current_user_id(request):
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={
            "csrf_token": get_csrf_token(request),
            "error": None,
        },
    )


@router.post("/register")
async def register(
    request: Request,
    name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)

    if password != password_confirm:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "비밀번호가 일치하지 않습니다.",
                "name": name,
                "email": email,
            },
            status_code=400,
        )

    try:
        user_id = await register_user(
            email=email,
            password=password,
            name=name,
        )
    except (EmailAlreadyExistsError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": str(exc),
                "name": name,
                "email": email,
            },
            status_code=400,
        )

    request.session.clear()
    request.session["user_id"] = user_id
    request.session["csrf_token"] = get_csrf_token(request)

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    request.session.clear()

    return RedirectResponse(
        url="/login",
        status_code=303,
    )
