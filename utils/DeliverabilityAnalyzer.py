import email.utils
import os
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import requests
from fastapi import HTTPException, status


@dataclass
class DeliverabilityRisk:
    score: float
    level: str
    action: str
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "action": self.action,
            "reasons": self.reasons,
            "signals": self.signals,
            "raw": self.raw,
        }


class RspamdAnalyzer:
    def __init__(self, base_url: str | None = None, password: str | None = None, timeout_seconds: float | None = None):
        self.base_url = (base_url or os.environ.get("RSPAMD_URL") or "http://localhost:11333").rstrip("/")
        self.password = password if password is not None else os.environ.get("RSPAMD_PASSWORD")
        self.timeout_seconds = timeout_seconds or float(os.environ.get("RSPAMD_TIMEOUT_SECONDS", "10"))
        self.low_threshold = float(os.environ.get("SPAM_RISK_LOW_THRESHOLD", "4"))
        self.high_threshold = float(os.environ.get("SPAM_RISK_HIGH_THRESHOLD", "7"))

    def analyze(self, email_subject: str, email_body: str, email_from: str, recipient_email: str) -> DeliverabilityRisk:
        message = self._build_message(email_subject, email_body, email_from, recipient_email)
        headers = {"Content-Type": "message/rfc822"}
        if self.password:
            headers["Password"] = self.password

        try:
            response = requests.post(
                f"{self.base_url}/checkv2",
                data=message.as_bytes(),
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Rspamd spam/deliverability risk analysis unavailable: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Rspamd returned an invalid JSON response",
            ) from exc

        return self._risk_from_rspamd(payload)

    def _build_message(self, subject: str, body: str, email_from: str, recipient_email: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = email_from
        message["To"] = recipient_email
        message["Subject"] = subject
        message["Date"] = email.utils.formatdate(localtime=True)
        message.set_content("HTML email body is included as an alternative part.")
        message.add_alternative(body, subtype="html")
        return message

    def _risk_from_rspamd(self, payload: dict[str, Any]) -> DeliverabilityRisk:
        score = float(payload.get("score") or payload.get("required_score") or 0)
        symbols = payload.get("symbols") or {}
        reasons = self._extract_reasons(symbols)

        if score >= self.high_threshold:
            level = "HIGH"
            action = "BLOCK_REVIEW"
        elif score >= self.low_threshold:
            level = "MEDIUM"
            action = "REWRITE_REQUIRED"
        else:
            level = "LOW"
            action = "SEND"

        return DeliverabilityRisk(
            score=round(score, 2),
            level=level,
            action=action,
            reasons=reasons,
            signals=symbols,
            raw=payload,
        )

    def _extract_reasons(self, symbols: dict[str, Any]) -> list[str]:
        weighted_symbols: list[tuple[float, str]] = []
        for name, details in symbols.items():
            score = 0.0
            description = name
            if isinstance(details, dict):
                score = float(details.get("score") or 0)
                description = details.get("description") or name
            if score > 0:
                weighted_symbols.append((score, description))
        weighted_symbols.sort(reverse=True)
        return [description for _, description in weighted_symbols[:6]]
