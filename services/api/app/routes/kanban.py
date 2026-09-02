from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.kanban_storage import get_kanban_storage

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


class CreateBoardBody(BaseModel):
    title: str


@router.post("/api/v1/boards")
async def create_board(request: Request, body: CreateBoardBody):
    storage = get_kanban_storage()
    board = await storage.create_board(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"], title=body.title
    )
    return JSONResponse(
        {"id": board.id, "title": board.title, "columns": board.columns, "created_at": board.created_at},
        status_code=201,
    )


@router.get("/api/v1/boards")
async def list_boards(request: Request):
    storage = get_kanban_storage()
    boards = await storage.list_boards(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse({"boards": boards}, status_code=200)


@router.get("/api/v1/boards/{board_id}")
async def get_board(request: Request, board_id: str):
    storage = get_kanban_storage()
    board = await storage.get_board_with_cards(user_jwt=request.state.user_jwt, board_id=board_id)
    if board is None:
        return _error("not_found", "Board not found", 404)
    return JSONResponse(board, status_code=200)


class CreateCardBody(BaseModel):
    column_name: str
    title: str
    description: str = ""
    document_id: str | None = None


@router.post("/api/v1/boards/{board_id}/cards")
async def create_card(request: Request, board_id: str, body: CreateCardBody):
    storage = get_kanban_storage()
    card = await storage.create_card(
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        board_id=board_id,
        column_name=body.column_name,
        title=body.title,
        description=body.description,
        document_id=body.document_id,
    )
    if card is None:
        return _error("not_found", "Board not found", 404)
    return JSONResponse(card, status_code=201)


class UpdateCardBody(BaseModel):
    column_name: str | None = None
    position: float | None = None
    title: str | None = None
    description: str | None = None
    document_id: str | None = None


@router.patch("/api/v1/cards/{card_id}")
async def update_card(request: Request, card_id: str, body: UpdateCardBody):
    """Also the move/reorder endpoint — dragging a card to a new column
    or a new spot within one is just a PATCH with a new column_name
    and/or position, computed client-side (see kanban_storage.py's
    module docstring for why position is a float)."""
    storage = get_kanban_storage()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return _error("empty_update", "No fields to update", 422)
    card = await storage.update_card(user_jwt=request.state.user_jwt, card_id=card_id, updates=updates)
    if card is None:
        return _error("not_found", "Card not found", 404)
    return JSONResponse(card, status_code=200)


@router.delete("/api/v1/cards/{card_id}")
async def delete_card(request: Request, card_id: str):
    storage = get_kanban_storage()
    deleted = await storage.delete_card(user_jwt=request.state.user_jwt, card_id=card_id)
    if not deleted:
        return _error("not_found", "Card not found", 404)
    return JSONResponse({"id": card_id, "deleted": True}, status_code=200)
