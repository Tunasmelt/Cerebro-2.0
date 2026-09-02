from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.account_storage import get_account_storage

router = APIRouter()


@router.delete("/api/v1/account")
async def wipe_account(request: Request):
    """Wipes all application data the caller owns. Does not delete the
    auth account itself — see account_storage.py's module docstring for
    why. Idempotent: calling this again on an already-empty account
    deletes zero rows and still returns 200, never an error."""
    storage = get_account_storage()
    result = await storage.wipe_account_data(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse(result, status_code=200)
