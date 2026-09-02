from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.todo_storage import get_todo_storage

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


class CreateTodoBody(BaseModel):
    title: str
    document_id: str | None = None


@router.post("/api/v1/todos")
async def create_todo(request: Request, body: CreateTodoBody):
    storage = get_todo_storage()
    todo = await storage.create_todo(
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        title=body.title,
        document_id=body.document_id,
    )
    return JSONResponse(todo, status_code=201)


@router.get("/api/v1/todos")
async def list_todos(request: Request):
    storage = get_todo_storage()
    todos = await storage.list_todos(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse({"todos": todos}, status_code=200)


class UpdateTodoBody(BaseModel):
    completed: bool | None = None
    title: str | None = None


@router.patch("/api/v1/todos/{todo_id}")
async def update_todo(request: Request, todo_id: str, body: UpdateTodoBody):
    storage = get_todo_storage()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return _error("empty_update", "No fields to update", 422)
    todo = await storage.update_todo(user_jwt=request.state.user_jwt, todo_id=todo_id, updates=updates)
    if todo is None:
        return _error("not_found", "Todo not found", 404)
    return JSONResponse(todo, status_code=200)


@router.delete("/api/v1/todos/{todo_id}")
async def delete_todo(request: Request, todo_id: str):
    storage = get_todo_storage()
    deleted = await storage.delete_todo(user_jwt=request.state.user_jwt, todo_id=todo_id)
    if not deleted:
        return _error("not_found", "Todo not found", 404)
    return JSONResponse({"id": todo_id, "deleted": True}, status_code=200)
