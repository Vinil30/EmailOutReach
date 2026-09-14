from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt

from database.fxns import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    disconnect_gmail,
    get_current_user,
    public_user,
    save_gmail_tokens,
)
from utils.EmailerAgent import GMAIL_SEND_SCOPE, GmailOAuthClient
from utils.GmailAuth import token_payload_with_expiry

router = APIRouter(prefix="/gmail", tags=["gmail"])


@router.get("/status")
async def gmail_status(current_user=Depends(get_current_user)):
    return {
        "connected": bool(current_user.get("gmail_tokens", {}).get("refresh_token") or current_user.get("gmail_tokens", {}).get("access_token")),
        "scope": GMAIL_SEND_SCOPE,
        "user": public_user(current_user),
    }


@router.get("/connect")
async def connect_gmail(current_user=Depends(get_current_user)):
    state = jwt.encode({"sub": str(current_user["_id"])}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return {"authorization_url": GmailOAuthClient().authorization_url(state)}


@router.get("/callback")
async def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code or state")

    try:
        payload = jwt.decode(state, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise JWTError("Missing user id")
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state") from exc

    tokens = GmailOAuthClient().exchange_code(code)
    save_gmail_tokens(user_id, token_payload_with_expiry(tokens))
    return HTMLResponse(
        """
        <!doctype html>
        <html>
        <head><title>Gmail Connected</title></head>
        <body>
            <p>Gmail is connected. You can close this tab and return to Outreach Desk.</p>
        </body>
        </html>
        """
    )


@router.post("/disconnect")
async def disconnect(current_user=Depends(get_current_user)):
    disconnect_gmail(str(current_user["_id"]))
    return {"connected": False}
