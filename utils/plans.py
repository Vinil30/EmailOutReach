"""Plan limits. General accounts get a small lifetime allowance; premium is weekly and time-limited."""
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from database.fxns import as_utc, emailsSent, get_user_by_id, is_premium
from utils.legal import UNSIGNED_MESSAGE, legal_status

GENERAL_LIFETIME_LIMIT = int(os.environ.get("GENERAL_LIFETIME_LIMIT", "20"))
PREMIUM_WEEKLY_LIMIT = int(os.environ.get("PREMIUM_WEEKLY_LIMIT", "100"))
PREMIUM_DAYS = int(os.environ.get("PREMIUM_DAYS", "30"))
PREMIUM_URL = os.environ.get("PREMIUM_URL", "https://srotabase.com/@vmarena/email-automation-premium")


AI_PREMIUM_MESSAGE = "AI writing is a Premium feature. Use a template, or upgrade to Premium."


class QuotaExceeded(Exception):
    pass


def require_ai(user: dict[str, Any]) -> None:
    """AI research and writing cost money per email, so only Premium accounts may use them."""
    if not is_premium(user):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=AI_PREMIUM_MESSAGE)


def week_start(now: datetime | None = None) -> datetime:
    """Premium allowances reset every Monday at 00:00 UTC."""
    now = now or datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def quota_status(user: dict[str, Any]) -> dict[str, Any]:
    user_id = str(user["_id"])
    premium = is_premium(user)
    lifetime_sent = emailsSent.count_documents({"user_id": user_id})
    if premium:
        start = week_start()
        used = emailsSent.count_documents({"user_id": user_id, "sent_at": {"$gte": start}}) if lifetime_sent else 0
        limit = PREMIUM_WEEKLY_LIMIT
        resets_at = start + timedelta(days=7)
    else:
        used = lifetime_sent
        limit = GENERAL_LIFETIME_LIMIT
        resets_at = None
    until = as_utc(user.get("premium_until"))
    return {
        "plan": "premium" if premium else "general",
        "period": "week" if premium else "lifetime",
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "resets_at": resets_at,
        "premium_until": until,
        "premium_expired": bool(until and not premium),
        "lifetime_sent": lifetime_sent,
        "premium_url": PREMIUM_URL,
    }


def ensure_can_send(user_id: str) -> dict[str, Any]:
    user = get_user_by_id(user_id)
    if not user:
        raise QuotaExceeded("Account not found")
    if not legal_status(user)["signed"]:
        raise QuotaExceeded(UNSIGNED_MESSAGE)
    quota = quota_status(user)
    if quota["remaining"] <= 0:
        if quota["plan"] == "premium":
            raise QuotaExceeded(f"Weekly limit of {quota['limit']} emails reached. It resets on Monday.")
        raise QuotaExceeded(f"The General plan includes {quota['limit']} emails. Upgrade to Premium to keep sending.")
    return quota
