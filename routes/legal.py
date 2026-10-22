from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from database.fxns import get_current_user, sign_legal_documents
from routes.auth import client_ip
from utils.legal import legal_status

router = APIRouter(prefix="/api/legal", tags=["legal"])


class SignIn(BaseModel):
    signature: str
    agree: bool = False


@router.get("")
async def status_for_user(current_user=Depends(get_current_user)):
    return legal_status(current_user)


@router.post("/sign")
async def sign(payload: SignIn, request: Request, current_user=Depends(get_current_user)):
    if not payload.agree:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tick the box to agree before signing")
    user = sign_legal_documents(str(current_user["_id"]), payload.signature, client_ip(request), request.headers.get("user-agent"))
    return {"user": user, "legal": user["legal"]}
