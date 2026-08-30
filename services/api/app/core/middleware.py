from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.auth import verify_jwt

# Applied globally so every future route is covered by default — a route
# has to opt out (by being added here), not opt in to auth.
EXEMPT_PATHS = {"/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": {"code": "unauthorized", "message": "Missing bearer token"}},
                status_code=401,
            )

        token = auth_header[len("Bearer "):]
        try:
            claims = verify_jwt(token)
        except HTTPException:
            return JSONResponse(
                {"error": {"code": "unauthorized", "message": "Invalid or expired token"}},
                status_code=401,
            )

        request.state.user = claims
        # Downstream Supabase Storage/PostgREST calls use this token directly
        # instead of a service-role key, so RLS enforces the same ownership
        # rules the API layer already checked — no extra secret needed.
        request.state.user_jwt = token
        return await call_next(request)
