from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.rate_limit import classify_route, get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Must run after AuthMiddleware has set request.state.user — added
    before it in main.py so it ends up as the inner wrapper (Starlette
    middleware executes in reverse add order on the way in)."""

    async def dispatch(self, request: Request, call_next):
        user = getattr(request.state, "user", None)
        if user is None:
            return await call_next(request)

        route_class = classify_route(request.url.path, request.method)
        if route_class is None:
            return await call_next(request)

        allowed, retry_after = get_rate_limiter().check(user["sub"], route_class)
        if not allowed:
            return JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": f"Too many requests for {route_class}",
                    }
                },
                status_code=429,
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )

        return await call_next(request)
