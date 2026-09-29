import secrets
from hmac import compare_digest

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from modules.users.service import get_user_status


class ActiveSessionMiddleware(BaseHTTPMiddleware):
    """Invalidate an existing signed session as soon as its account is disabled/deleted."""

    async def dispatch(self, request: Request, call_next):
        value = request.session.get("user_id")
        if value is not None:
            try:
                user_id = int(value)
            except (TypeError, ValueError):
                request.session.clear()
            else:
                status = await get_user_status(user_id)
                if status != "active":
                    request.session.clear()
        return await call_next(request)


class AuthenticatedUploadMiddleware(BaseHTTPMiddleware):
    """Reject anonymous multipart upload routes before FastAPI parses the body.

    Form/File dependencies are resolved before the endpoint function executes, so an
    authentication check inside the route is too late to prevent multipart spooling.
    This middleware runs inside SessionMiddleware and after ActiveSessionMiddleware.
    """

    _PROTECTED_UPLOADS = {
        ("POST", "/lectures"),
        ("POST", "/instructor"),
        ("POST", "/instructor/avatar"),
    }

    async def dispatch(self, request: Request, call_next):
        key = (request.method.upper(), request.url.path.rstrip("/") or "/")
        if key in self._PROTECTED_UPLOADS and current_user_id(request) is None:
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return login_redirect()
        return await call_next(request)


def current_user_id(request: Request) -> int | None:
    value = request.session.get("user_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def require_user_id(request: Request) -> int:
    user_id = current_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, supplied_token: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not supplied_token or not compare_digest(expected, supplied_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
