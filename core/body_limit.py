from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    """Bound the request while streaming, before multipart spools it to disk."""

    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse(
                {"detail": "잘못된 Content-Length입니다."}, status_code=400
            )(scope, receive, send)
        if declared < 0 or declared > self.max_bytes:
            return await JSONResponse(
                {"detail": "업로드 허용 크기를 초과했습니다."}, status_code=413
            )(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise HTTPException(
                        status_code=413, detail="업로드 허용 크기를 초과했습니다."
                    )
            return message

        await self.app(scope, limited_receive, send)
