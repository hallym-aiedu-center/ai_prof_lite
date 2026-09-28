from hmac import compare_digest

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from core.config import registration_code
from modules.auth.rate_limit import (
    check_login_rate_limit,
    reset_login_account,
)
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

    allowed, retry_after = check_login_rate_limit(request, email)
    if not allowed:
        response = templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "로그인 요청이 많습니다. 잠시 후 다시 시도하세요.",
                "email": email,
            },
            status_code=429,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response

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

    reset_login_account(email)
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
            "registration_required": bool(registration_code()),
        },
    )


@router.post("/register")
async def register(
    request: Request,
    name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    registration_code_input: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)

    required_code = registration_code()
    if required_code and not compare_digest(required_code, registration_code_input.strip()):
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "가입 코드가 올바르지 않습니다.",
                "name": name,
                "email": email,
                "registration_required": True,
            },
            status_code=403,
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "비밀번호가 일치하지 않습니다.",
                "name": name,
                "email": email,
                "registration_required": bool(required_code),
            },
            status_code=400,
        )

    try:
        user_id = await register_user(
            email=email,
            password=password,
            name=name,
        )
    except EmailAlreadyExistsError:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": "가입 요청을 처리할 수 없습니다. 입력 정보를 확인하세요.",
                "name": name,
                "email": email,
                "registration_required": bool(required_code),
            },
            status_code=400,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_csrf_token(request),
                "error": str(exc),
                "name": name,
                "email": email,
                "registration_required": bool(required_code),
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
