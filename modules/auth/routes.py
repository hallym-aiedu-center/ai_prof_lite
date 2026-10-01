from hmac import compare_digest

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from core.config import registration_code
from core.templates import templates
from modules.auth.constraints import EMAIL_MAX_LENGTH, PASSWORD_MAX_LENGTH
from modules.auth.rate_limit import (
    check_login_rate_limit,
    check_register_rate_limit,
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


def _login_response(
    request: Request,
    *,
    error: str | None,
    email: str = "",
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "csrf_token": get_csrf_token(request),
            "error": error,
            "email": email,
            "account_deleted": request.query_params.get("account_deleted") == "1",
        },
        status_code=status_code,
    )


def _register_response(
    request: Request,
    *,
    error: str | None,
    name: str = "",
    email: str = "",
    registration_required: bool | None = None,
    status_code: int = 200,
):
    if registration_required is None:
        registration_required = bool(registration_code())
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={
            "csrf_token": get_csrf_token(request),
            "error": error,
            "name": name,
            "email": email,
            "registration_required": registration_required,
        },
        status_code=status_code,
    )


@router.get("/login")
async def login_page(request: Request):
    if current_user_id(request):
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return _login_response(request, error=None)


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(..., max_length=EMAIL_MAX_LENGTH),
    password: str = Form(..., max_length=PASSWORD_MAX_LENGTH),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)

    allowed, retry_after = check_login_rate_limit(request, email)
    if not allowed:
        response = _login_response(
            request,
            error="로그인 요청이 많습니다. 잠시 후 다시 시도하세요.",
            email=email,
            status_code=429,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response

    user = await authenticate_user(
        email=email,
        password=password,
    )

    if user is None:
        return _login_response(
            request,
            error="이메일 또는 비밀번호를 확인하세요.",
            email=email,
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

    return _register_response(request, error=None)


@router.post("/register")
async def register(
    request: Request,
    name: str = Form(""),
    email: str = Form(..., max_length=EMAIL_MAX_LENGTH),
    password: str = Form(..., max_length=PASSWORD_MAX_LENGTH),
    password_confirm: str = Form(..., max_length=PASSWORD_MAX_LENGTH),
    registration_code_input: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)

    allowed, retry_after = check_register_rate_limit(request)
    if not allowed:
        response = _register_response(
            request,
            error="회원가입 요청이 많습니다. 잠시 후 다시 시도하세요.",
            name=name,
            email=email,
            status_code=429,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response

    required_code = registration_code()
    if required_code and not compare_digest(
        required_code.encode("utf-8"),
        registration_code_input.strip().encode("utf-8"),
    ):
        return _register_response(
            request,
            error="가입 코드가 올바르지 않습니다.",
            name=name,
            email=email,
            registration_required=True,
            status_code=403,
        )

    if password != password_confirm:
        return _register_response(
            request,
            error="비밀번호가 일치하지 않습니다.",
            name=name,
            email=email,
            registration_required=bool(required_code),
            status_code=400,
        )

    try:
        user_id = await register_user(
            email=email,
            password=password,
            name=name,
        )
    except EmailAlreadyExistsError:
        return _register_response(
            request,
            error="가입 요청을 처리할 수 없습니다. 입력 정보를 확인하세요.",
            name=name,
            email=email,
            registration_required=bool(required_code),
            status_code=400,
        )
    except ValueError as exc:
        return _register_response(
            request,
            error=str(exc),
            name=name,
            email=email,
            registration_required=bool(required_code),
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
