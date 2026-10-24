import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt

from database.fxns import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    _now,
    disconnect_gmail,
    get_current_user,
    public_user,
    save_gmail_tokens,
)
from utils.EmailerAgent import GMAIL_SEND_SCOPE, GmailOAuthClient
from utils.GmailAuth import token_payload_with_expiry

router = APIRouter(prefix="/gmail", tags=["gmail"])

STATE_PURPOSE = "gmail_state"
NONCE_COOKIE = "mz_gmail_nonce"
STATE_MINUTES = 15


@router.get("/status")
async def gmail_status(current_user=Depends(get_current_user)):
    return {
        "connected": bool(current_user.get("gmail_tokens", {}).get("refresh_token") or current_user.get("gmail_tokens", {}).get("access_token")),
        "scope": GMAIL_SEND_SCOPE,
        "user": public_user(current_user),
    }


@router.get("/connect")
async def connect_gmail(response: Response, current_user=Depends(get_current_user)):
    # The state is short-lived, can't be used to sign in, and only completes in the browser that started it.
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode(
        {"sub": str(current_user["_id"]), "purpose": STATE_PURPOSE, "nonce": nonce, "exp": _now() + timedelta(minutes=STATE_MINUTES)},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    response.set_cookie(NONCE_COOKIE, nonce, max_age=STATE_MINUTES * 60, httponly=True, samesite="lax",
                        secure=os.environ.get("APP_ENV") == "production", path="/gmail")
    return {"authorization_url": GmailOAuthClient().authorization_url(state)}


@router.get("/callback")
async def gmail_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code or state")

    try:
        payload = jwt.decode(state, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id or payload.get("purpose") != STATE_PURPOSE:
            raise JWTError("Not a Gmail connect state")
        if not secrets.compare_digest(str(payload.get("nonce") or ""), request.cookies.get(NONCE_COOKIE) or ""):
            raise JWTError("Started in a different browser")
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This Gmail connect link has expired or was opened in a different browser. Go back to Mailzen and press Connect Gmail again.") from exc

    tokens = GmailOAuthClient().exchange_code(code)
    save_gmail_tokens(user_id, token_payload_with_expiry(tokens))
    redirect = RedirectResponse("/dashboard?gmail=connected", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(NONCE_COOKIE, path="/gmail")
    return redirect


@router.post("/disconnect")
async def disconnect(current_user=Depends(get_current_user)):
    disconnect_gmail(str(current_user["_id"]))
    return {"connected": False}
