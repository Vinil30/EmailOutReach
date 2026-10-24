"""Plans and limits.

Free: a small lifetime allowance to the user's own lists. Pro and Premium: unlimited sending (capped per day so
Gmail doesn't suspend the account), plus a number of new recruiters from the shared database per purchase.
Premium also gets AI writing. Prices and limits are admin-editable and stored in the settings collection."""
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from database.fxns import as_utc, emailsSent, get_user_by_id, is_premium, leadSends, plan_of, settings
from utils.legal import UNSIGNED_MESSAGE, legal_status

PRO_URL = os.environ.get("PRO_URL", "https://srotabase.com/@vmarena/mailzen-pro")
PREMIUM_URL = os.environ.get("PREMIUM_URL", "https://srotabase.com/@vmarena/email-automation-premium")
PLAN_DAYS = int(os.environ.get("PLAN_DAYS", "30"))

# Sending days roll over at midnight India time, where most users are.
DAY_OFFSET = timedelta(hours=5, minutes=30)

DEFAULT_PRICING = {
    "currency": "₹",
    "free_emails": 20,
    "daily_cap": 100,
    "pro": {"price": 99, "contacts": 200},
    "premium": {"price": 249, "contacts": 500},
}
PLAN_NAMES = {"free": "Free", "pro": "Pro", "premium": "Premium"}

AI_PREMIUM_MESSAGE = "AI writing is part of Premium. Use a template, or upgrade to Premium."
DAILY_CAP_REASON = "Google may suspend accounts that send too many emails in a day, so Mailzen caps sending to keep your Gmail safe."


class QuotaExceeded(Exception):
    pass


def pricing() -> dict[str, Any]:
    """Current prices and limits, with the purchase links. Safe to show publicly."""
    stored = settings.find_one({"_id": "pricing"}) or {}
    data = {
        "currency": stored.get("currency") or DEFAULT_PRICING["currency"],
        "free_emails": int(stored.get("free_emails", DEFAULT_PRICING["free_emails"])),
        "daily_cap": int(stored.get("daily_cap", DEFAULT_PRICING["daily_cap"])),
        "days": PLAN_DAYS,
    }
    for plan, url in (("pro", PRO_URL), ("premium", PREMIUM_URL)):
        tier = {**DEFAULT_PRICING[plan], **(stored.get(plan) or {})}
        data[plan] = {"price": float(tier["price"]), "contacts": int(tier["contacts"]), "url": url}
    return data


def save_pricing(fields: dict[str, Any]) -> dict[str, Any]:
    current = pricing()
    update = {
        "currency": str(fields.get("currency") or current["currency"]).strip()[:4] or "₹",
        "free_emails": int(fields.get("free_emails", current["free_emails"])),
        "daily_cap": int(fields.get("daily_cap", current["daily_cap"])),
    }
    for plan in ("pro", "premium"):
        given = fields.get(plan) or {}
        update[plan] = {
            "price": float(given.get("price", current[plan]["price"])),
            "contacts": int(given.get("contacts", current[plan]["contacts"])),
        }
    if min(update["free_emails"], update["daily_cap"], update["pro"]["contacts"], update["premium"]["contacts"]) < 0 or min(update["pro"]["price"], update["premium"]["price"]) < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prices and limits can't be negative")
    if update["daily_cap"] < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The daily cap must be at least 1")
    settings.update_one({"_id": "pricing"}, {"$set": update}, upsert=True)
    return pricing()


def require_ai(user: dict[str, Any]) -> None:
    """AI research and writing cost money per email, so only Premium accounts may use them."""
    if not is_premium(user):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=AI_PREMIUM_MESSAGE)


def week_start(now: datetime | None = None) -> datetime:
    """Weeks start every Monday at 00:00 UTC (used for admin reporting)."""
    now = now or datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def day_start(now: datetime | None = None) -> datetime:
    """Midnight India time, as a UTC datetime."""
    local = (now or datetime.now(timezone.utc)) + DAY_OFFSET
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - DAY_OFFSET


def database_sent(user_id: str) -> int:
    return leadSends.count_documents({"user_id": str(user_id), "status": "sent"})


def database_allowance(user: dict[str, Any], prices: dict[str, Any] | None = None) -> dict[str, int]:
    """New recruiters left from the shared database for the current purchase.

    Each purchase records how many database emails the account had sent (db_base), so every purchase gives
    a full allowance, always of recruiters this user hasn't been sent to before."""
    plan = plan_of(user)
    if plan == "free":
        return {"limit": 0, "used": 0, "remaining": 0}
    prices = prices or pricing()
    limit = prices[plan]["contacts"]
    used = max(0, database_sent(str(user["_id"])) - int(user.get("db_base") or 0))
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def quota_status(user: dict[str, Any]) -> dict[str, Any]:
    user_id = str(user["_id"])
    plan = plan_of(user)
    prices = pricing()
    lifetime_sent = emailsSent.count_documents({"user_id": user_id})
    if plan == "free":
        used, limit, period, resets_at = lifetime_sent, prices["free_emails"], "lifetime", None
    else:
        start = day_start()
        used = emailsSent.count_documents({"user_id": user_id, "sent_at": {"$gte": start}}) if lifetime_sent else 0
        limit, period, resets_at = prices["daily_cap"], "day", start + timedelta(days=1)
    until = as_utc(user.get("plan_until"))
    return {
        "plan": plan,
        "plan_name": PLAN_NAMES[plan],
        "period": period,
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "resets_at": resets_at,
        "plan_until": until if plan != "free" else None,
        "plan_expired": bool(plan == "free" and until),
        "expired_plan_name": PLAN_NAMES.get(user.get("plan") or "", "") if plan == "free" and until else "",
        "lifetime_sent": lifetime_sent,
        "ai_allowed": plan == "premium",
        "database": database_allowance(user, prices),
        "daily_cap_reason": DAILY_CAP_REASON,
        "pricing": prices,
    }


def limit_message(quota: dict[str, Any]) -> str:
    if quota["plan"] == "free":
        return f"The Free plan includes {quota['limit']} emails. Upgrade to Pro or Premium for unlimited sending."
    return f"You've sent today's {quota['limit']} emails. {DAILY_CAP_REASON} Sending continues after midnight."


def ensure_can_send(user_id: str) -> dict[str, Any]:
    user = get_user_by_id(user_id)
    if not user:
        raise QuotaExceeded("Account not found")
    if not legal_status(user)["signed"]:
        raise QuotaExceeded(UNSIGNED_MESSAGE)
    quota = quota_status(user)
    if quota["remaining"] <= 0:
        raise QuotaExceeded(limit_message(quota))
    return quota
