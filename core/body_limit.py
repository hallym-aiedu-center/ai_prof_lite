from collections.abc import Mapping

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    """Bound request bodies while streaming, before multipart spools to disk.

    ``path_limits`` may apply a smaller limit to sensitive endpoints such as
    authentication forms while keeping the larger upload budget elsewhere.
    Paths are normalized without a trailing slash.
    """

    def __init__(
        self,
        app,
        max_bytes: int,
        path_limits: Mapping[str, int] | None = None,
    ):
        self.app = app
        self.max_bytes = int(max_bytes)
        self.path_limits = {
            (path.rstrip("/") or "/"): int(limit)
            for path, limit in (path_limits or {}).items()
        }

    def _max_bytes_for(self, scope) -> int:
        path = str(scope.get("path") or "/").rstrip("/") or "/"
        return self.path_limits.get(path, self.max_bytes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        max_bytes = self._max_bytes_for(scope)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse(
                {"detail": "잘못된 Content-Length입니다."}, status_code=400
            )(scope, receive, send)
        if declared < 0 or declared > max_bytes:
            return await JSONResponse(
                {"detail": "요청 본문 허용 크기를 초과했습니다."}, status_code=413
            )(scope, receive, send)

        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="요청 본문 허용 크기를 초과했습니다.",
                    )
            return message

        await self.app(scope, limited_receive, send)
