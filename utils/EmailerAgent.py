import base64
import email.utils
import os
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import requests
from fastapi import HTTPException, status


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


@dataclass
class GmailSendFailure(Exception):
    reason: str
    transient: bool
    status_code: int | None = None
    detail: str | None = None


class GmailOAuthClient:
    token_url = "https://oauth2.googleapis.com/token"

    def __init__(self):
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")

    def authorization_url(self, state: str) -> str:
        if not self.client_id or not self.redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing GOOGLE_CLIENT_ID or GOOGLE_REDIRECT_URI",
            )
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SEND_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        query = requests.models.RequestEncodingMixin._encode_params(params)
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        return self._token_request(
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            }
        )

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        return self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )

    def _token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET",
            )
        try:
            response = requests.post(self.token_url, data=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google OAuth failed: {exc}",
            ) from exc


class EmailerAgent:
    def __init__(self, email_details, recipient_email, email_from, gmail_tokens: dict[str, Any] | None = None):
        self.recipient_email = recipient_email
        self.email_from = email_from
        self.email_subject = email_details.email_subject
        self.email_body = email_details.email_body
        self.gmail_tokens = gmail_tokens or {}

    def SendEmail(self):
        access_token = self.gmail_tokens.get("access_token")
        if not access_token:
            raise GmailSendFailure("Gmail authorization required", transient=False, status_code=401)

        message = self._build_raw_message()
        try:
            response = requests.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                json={"raw": message},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=float(os.environ.get("GMAIL_SEND_TIMEOUT_SECONDS", "20")),
            )
        except requests.Timeout as exc:
            raise GmailSendFailure("Gmail timeout", transient=True, detail=str(exc)) from exc
        except requests.RequestException as exc:
            raise GmailSendFailure("Gmail network error", transient=True, detail=str(exc)) from exc

        if response.status_code in (401, 403):
            raise GmailSendFailure("Gmail authorization expired or revoked", transient=False, status_code=response.status_code)
        if response.status_code == 429:
            raise GmailSendFailure("Gmail rate limit", transient=True, status_code=429)
        if 500 <= response.status_code < 600:
            raise GmailSendFailure("Gmail server error", transient=True, status_code=response.status_code)
        if response.status_code in (400, 404):
            raise GmailSendFailure("Permanent Gmail send failure or invalid recipient", transient=False, status_code=response.status_code)
        if not response.ok:
            raise GmailSendFailure("Gmail send failed", transient=False, status_code=response.status_code)

        return response.json()

    def send_with_retries(self, max_attempts: int | None = None, base_delay_seconds: float | None = None) -> dict[str, Any]:
        attempts = max_attempts or int(os.environ.get("GMAIL_MAX_SEND_ATTEMPTS", "3"))
        delay = base_delay_seconds if base_delay_seconds is not None else float(os.environ.get("GMAIL_RETRY_BASE_SECONDS", "1"))
        history = []

        for attempt in range(1, attempts + 1):
            try:
                response = self.SendEmail()
                return {"status": "SENT", "attempt": attempt, "max_attempts": attempts, "response": response, "history": history}
            except GmailSendFailure as exc:
                history.append(
                    {
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "status": "RETRYING" if exc.transient and attempt < attempts else "FAILED",
                        "reason": exc.reason,
                        "transient": exc.transient,
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    }
                )
                if not exc.transient or attempt >= attempts:
                    return {
                        "status": "FAILED_TRANSIENT" if exc.transient else "FAILED_PERMANENT",
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "reason": exc.reason,
                        "history": history,
                    }
                time.sleep(delay * (2 ** (attempt - 1)))

        return {"status": "FAILED_TRANSIENT", "attempt": attempts, "max_attempts": attempts, "reason": "Retry attempts exhausted", "history": history}

    def _build_raw_message(self) -> str:
        message = EmailMessage()
        message["From"] = self.email_from
        message["To"] = self.recipient_email
        message["Subject"] = self.email_subject
        message["Date"] = email.utils.formatdate(localtime=True)
        message.set_content("HTML email body is included as an alternative part.")
        message.add_alternative(self.email_body, subtype="html")
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        return encoded.rstrip("=")
