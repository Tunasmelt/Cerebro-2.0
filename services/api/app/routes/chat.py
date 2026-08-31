from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.chat.storage import get_chat_storage
from app.chat.stream import stream_chat

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


@router.post("/api/v1/chat/sessions")
async def create_session(request: Request):
    storage = get_chat_storage()
    session_id = await storage.create_session(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse({"id": session_id}, status_code=201)


class StreamBody(BaseModel):
    query: str


@router.post("/api/v1/chat/sessions/{session_id}/stream")
async def stream(request: Request, session_id: str, body: StreamBody):
    storage = get_chat_storage()
    session = await storage.get_session(
        user_jwt=request.state.user_jwt, session_id=session_id
    )
    # RLS already scopes this to the caller's own sessions, so a missing
    # row means "not found", never "exists but belongs to someone else" —
    # same 404-not-403 pattern as documents.py's confirm.
    if session is None:
        return _error("not_found", "Chat session not found", 404)

    return StreamingResponse(
        stream_chat(
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            session_id=session_id,
            query=body.query,
        ),
        media_type="text/event-stream",
    )
