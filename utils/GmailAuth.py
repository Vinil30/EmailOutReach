from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from database.fxns import get_gmail_tokens, save_gmail_tokens
from utils.EmailerAgent import GmailOAuthClient


def token_payload_with_expiry(payload: dict[str, Any]) -> dict[str, Any]:
    token_payload = dict(payload)
    expires_in = int(token_payload.get("expires_in") or 3600)
    token_payload["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)).isoformat()
    return token_payload


def get_valid_gmail_tokens(user_id: str) -> dict[str, Any]:
    tokens = get_gmail_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connect Gmail before sending")

    expires_at = tokens.get("expires_at")
    if tokens.get("access_token") and expires_at:
        try:
            if datetime.fromisoformat(expires_at) > datetime.now(timezone.utc):
                return tokens
        except ValueError:
            pass

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gmail authorization expired or revoked")

    refreshed = GmailOAuthClient().refresh_access_token(refresh_token)
    merged = dict(tokens)
    merged.update(token_payload_with_expiry(refreshed))
    save_gmail_tokens(user_id, merged)
    return merged
