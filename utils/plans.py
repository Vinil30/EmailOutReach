"""Plans and limits.

Free: a small lifetime allowance to the user's own lists. Pro and Premium: unlimited sending (capped per day so
Gmail doesn't suspend the account) and automation; Premium also gets AI writing. Contacts are not part of any
plan: they're bought with credits in the marketplace. Prices, limits, credit packs and the credit price of a
contact are admin-editable and stored in the settings collection."""
import copy
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from database.fxns import as_utc, emailsSent, get_user_by_id, is_premium, plan_of, settings
from utils.legal import UNSIGNED_MESSAGE, legal_status

PLAN_DAYS = int(os.environ.get("PLAN_DAYS", "30"))

# Sending days roll over at midnight India time, where most users are.
DAY_OFFSET = timedelta(hours=5, minutes=30)

DEFAULT_PRICING = {
    "currency": "₹",
    "free_emails": 20,
    "daily_cap": 100,
    "pro": {"price": 99},
    "premium": {"price": 249},
    # Credits a contact costs: from our recruiter database, or freshly found by web search.
    "contact_credits": {"database": 2, "web": 5},
    # Credit packs sold through Razorpay; the price is in rupees.
    "packs": [
        {"id": "p1", "credits": 100, "price": 99},
        {"id": "p2", "credits": 500, "price": 449},
        {"id": "p3", "credits": 1000, "price": 849},
    ],
}
PACK_IDS = ("p1", "p2", "p3")
PLAN_NAMES = {"free": "Free", "pro": "Pro", "premium": "Premium"}

AI_PREMIUM_MESSAGE = "AI writing is part of Premium. Use a template, or upgrade to Premium."
DAILY_CAP_REASON = "Google may suspend accounts that send too many emails in a day, so Mailzen caps sending to keep your Gmail safe."


class QuotaExceeded(Exception):
    pass


_pricing_cache: dict[str, Any] = {"value": None, "at": 0.0}
PRICING_CACHE_SECONDS = 30


def pricing() -> dict[str, Any]:
    """Current prices and limits, with the purchase links. Safe to show publicly.

    Read on almost every request, so it's cached briefly; saving new prices clears the cache."""
    if _pricing_cache["value"] and time.monotonic() - _pricing_cache["at"] < PRICING_CACHE_SECONDS:
        return copy.deepcopy(_pricing_cache["value"])
    value = _load_pricing()
    _pricing_cache.update(value=value, at=time.monotonic())
    return copy.deepcopy(value)


def _load_pricing() -> dict[str, Any]:
    stored = settings.find_one({"_id": "pricing"}) or {}
    data = {
        "currency": stored.get("currency") or DEFAULT_PRICING["currency"],
        "free_emails": int(stored.get("free_emails", DEFAULT_PRICING["free_emails"])),
        "daily_cap": int(stored.get("daily_cap", DEFAULT_PRICING["daily_cap"])),
        "days": PLAN_DAYS,
    }
    for plan in ("pro", "premium"):
        tier = {**DEFAULT_PRICING[plan], **(stored.get(plan) or {})}
        data[plan] = {"price": float(tier["price"])}
    contact_credits = {**DEFAULT_PRICING["contact_credits"], **(stored.get("contact_credits") or {})}
    data["contact_credits"] = {source: int(value) for source, value in contact_credits.items()}
    stored_packs = {pack.get("id"): pack for pack in stored.get("packs") or []}
    data["packs"] = [
        {"id": pack["id"], "credits": int(stored_packs.get(pack["id"], pack)["credits"]), "price": float(stored_packs.get(pack["id"], pack)["price"])}
        for pack in DEFAULT_PRICING["packs"]
    ]
    return data


def pack_by_id(pack_id: str) -> dict[str, Any] | None:
    return next((pack for pack in pricing()["packs"] if pack["id"] == pack_id and pack["credits"] > 0 and pack["price"] > 0), None)


def save_pricing(fields: dict[str, Any]) -> dict[str, Any]:
    current = pricing()
    update = {
        "currency": str(fields.get("currency") or current["currency"]).strip()[:4] or "₹",
        "free_emails": int(fields.get("free_emails", current["free_emails"])),
        "daily_cap": int(fields.get("daily_cap", current["daily_cap"])),
    }
    for plan in ("pro", "premium"):
        given = fields.get(plan) or {}
        update[plan] = {"price": float(given.get("price", current[plan]["price"]))}
    given_credits = fields.get("contact_credits") or {}
    update["contact_credits"] = {source: int(given_credits.get(source, current["contact_credits"][source])) for source in ("database", "web")}
    given_packs = {pack.get("id"): pack for pack in fields.get("packs") or []}
    update["packs"] = [
        {"id": pack["id"], "credits": int(given_packs.get(pack["id"], pack)["credits"]), "price": float(given_packs.get(pack["id"], pack)["price"])}
        for pack in current["packs"]
    ]
    numbers = [update["free_emails"], update["daily_cap"], update["pro"]["price"], update["premium"]["price"],
               *update["contact_credits"].values(), *(value for pack in update["packs"] for value in (pack["credits"], pack["price"]))]
    if min(numbers) < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prices and limits can't be negative")
    if update["daily_cap"] < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The daily cap must be at least 1")
    if min(update["contact_credits"].values()) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A contact must cost at least 1 credit")
    settings.update_one({"_id": "pricing"}, {"$set": update}, upsert=True)
    _pricing_cache["value"] = None
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
        "credits": int(user.get("credits") or 0),
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
