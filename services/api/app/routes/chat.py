from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.chat.playground import get_chat_playground_storage
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


@router.get("/api/v1/chat/sessions")
async def list_sessions(request: Request):
    storage = get_chat_storage()
    sessions = await storage.list_sessions(user_jwt=request.state.user_jwt)
    return JSONResponse({"sessions": sessions})


@router.get("/api/v1/chat/sessions/{session_id}/messages")
async def get_messages(request: Request, session_id: str):
    """Stage 2.4 — history for reopening a past conversation, with each
    message's retrieved_chunk_ids resolved to retrieved_document_ids so
    the frontend can replay the same graph pulse that happened live,
    without re-deriving anything from the (possibly different by now)
    live retrieval pipeline."""
    storage = get_chat_storage()
    messages = await storage.get_messages(
        user_jwt=request.state.user_jwt, session_id=session_id
    )
    if messages is None:
        return _error("not_found", "Chat session not found", 404)
    return JSONResponse({"messages": messages})


@router.get("/api/v1/chat/sessions/{session_id}/messages/{message_id}/prompt")
async def get_prompt_breakdown(request: Request, session_id: str, message_id: str):
    """Stage 4.4 — read-only token/cost playground: reconstructs the
    prompt actually sent for a past assistant message."""
    storage = get_chat_playground_storage()
    breakdown = await storage.get_prompt_breakdown(
        user_jwt=request.state.user_jwt, session_id=session_id, message_id=message_id
    )
    if breakdown is None:
        return _error("not_found", "Chat message not found", 404)
    return JSONResponse(breakdown)


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
