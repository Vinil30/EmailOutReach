"""Admin-managed data: the shared lead database, Pro/Premium grants, and per-user lead usage."""
import re
from datetime import timedelta
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.fxns import (
    PAID_PLANS,
    _now,
    _serialize_doc,
    _serialize_many,
    add_bad_address,
    as_utc,
    emailsSent,
    get_user_by_email,
    leads,
    plan_of,
    db,
    premiumGrants,
    users,
)

LEAD_FIELDS = ("email", "name", "company", "role", "details")


# ---------- Plan grants (Pro / Premium) ----------

def grant_plan(email: str, plan: str, days: int, granted_by: str, note: str = "") -> dict[str, Any]:
    """Give an account Pro or Premium for `days`. Works before the person signs up.

    Buying the same plan again extends it from the current expiry; switching plans starts now. Plans don't
    include contacts: those are bought with credits in the marketplace."""
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan must be 'pro' or 'premium'")
    email = email.strip().lower()
    user = get_user_by_email(email)
    now = _now()
    if user:
        current = as_utc(user.get("plan_until"))
        same_plan = plan_of(user) == plan
        start = current if same_plan and current and current > now else now
        until = start + timedelta(days=days)
        users.update_one({"_id": user["_id"]}, {"$set": {"plan": plan, "plan_until": until}})
    else:
        pending = premiumGrants.find_one({"email": email, "pending": True}, sort=[("created_at", -1)])
        same_plan = pending and (pending.get("plan") or "premium") == plan
        pending_until = as_utc(pending["until"]) if same_plan else None
        until = max(now, pending_until or now) + timedelta(days=days)
    premiumGrants.insert_one(
        {
            "email": email,
            "plan": plan,
            "days": days,
            "until": until,
            "pending": not user,
            "granted_by": granted_by,
            "note": note,
            "created_at": now,
        }
    )
    return {"email": email, "plan": plan, "plan_until": until, "account_exists": bool(user)}


def revoke_plan(email: str, revoked_by: str) -> None:
    email = email.strip().lower()
    users.update_one({"email": email}, {"$unset": {"plan": "", "plan_until": ""}})
    premiumGrants.update_many({"email": email, "pending": True}, {"$set": {"pending": False, "revoked": True}})
    premiumGrants.insert_one({"email": email, "days": 0, "revoked": True, "granted_by": revoked_by, "created_at": _now()})


def apply_pending_plan(user: dict[str, Any]) -> None:
    """Called at signup so a grant made before the account existed takes effect."""
    pending = premiumGrants.find_one({"email": user["email"], "pending": True}, sort=[("created_at", -1)])
    if pending and as_utc(pending["until"]) > _now():
        users.update_one({"_id": user["_id"]}, {"$set": {"plan": pending.get("plan") or "premium", "plan_until": pending["until"]}})
    premiumGrants.update_many({"email": user["email"], "pending": True}, {"$set": {"pending": False}})


def recent_grants(limit: int = 30) -> list[dict[str, Any]]:
    grants = _serialize_many(premiumGrants.find().sort("created_at", -1).limit(limit))
    for grant in grants:
        grant.setdefault("plan", "premium")
    return grants


# ---------- Users overview ----------

def list_users_overview(query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    from database.marketplace import ownedContacts
    from utils.plans import week_start

    filt: dict[str, Any] = {}
    if query:
        filt["email"] = {"$regex": re.escape(query.lower())}
    start = week_start()
    listed = list(users.find(filt).sort("created_at", -1).limit(limit))
    ids = [str(user["_id"]) for user in listed]
    totals = {row["_id"]: row for row in emailsSent.aggregate([
        {"$match": {"user_id": {"$in": ids}}},
        {"$group": {
            "_id": "$user_id",
            "total": {"$sum": 1},
            "week": {"$sum": {"$cond": [{"$gte": ["$sent_at", start]}, 1, 0]}},
        }},
    ])}
    owned = {row["_id"]: row for row in ownedContacts.aggregate([
        {"$match": {"user_id": {"$in": ids}}},
        {"$group": {"_id": "$user_id", "total": {"$sum": 1}, "left": {"$sum": {"$cond": [{"$eq": ["$status", "available"]}, 1, 0]}}}},
    ])}
    rows = []
    for user in listed:
        uid = str(user["_id"])
        stats = totals.get(uid, {})
        plan = plan_of(user)
        rows.append({
            "id": uid,
            "email": user.get("email"),
            "name": (user.get("profile") or {}).get("full_name") or user.get("name") or "",
            "role": user.get("role") or "student",
            "plan": plan,
            "plan_until": user.get("plan_until"),
            "credits": int(user.get("credits") or 0),
            "contacts": {"total": owned.get(uid, {}).get("total", 0), "left": owned.get(uid, {}).get("left", 0)},
            "sent_total": stats.get("total", 0),
            "sent_week": stats.get("week", 0),
            "automation": (user.get("automation") or {}).get("status", "idle"),
            "gmail_connected": bool((user.get("gmail_tokens") or {}).get("refresh_token")),
            "created_at": user.get("created_at"),
        })
    return rows


# ---------- Lead database ----------

def _clean_lead(data: dict[str, Any]) -> dict[str, Any]:
    lead = {key: str(data.get(key) or "").strip() for key in LEAD_FIELDS}
    lead["email"] = lead["email"].lower()
    return lead


def add_lead(data: dict[str, Any]) -> dict[str, Any]:
    lead = _clean_lead(data)
    if not lead["email"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")
    lead.update({"active": True, "created_at": _now()})
    try:
        result = leads.insert_one(lead)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That email is already in the database") from exc
    return _serialize_doc(leads.find_one({"_id": result.inserted_id}))


def import_leads(rows: list[dict[str, Any]]) -> dict[str, int]:
    added = duplicates = 0
    for row in rows:
        lead = _clean_lead(row)
        if not lead["email"]:
            continue
        result = leads.update_one(
            {"email": lead["email"]},
            {"$setOnInsert": {**lead, "active": True, "created_at": _now()}},
            upsert=True,
        )
        if result.upserted_id:
            added += 1
        else:
            duplicates += 1
    return {"added": added, "duplicates": duplicates}


def update_lead(lead_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    allowed = {key: value for key, value in fields.items() if key in (*LEAD_FIELDS[1:], "active")}
    updated = leads.find_one_and_update({"_id": ObjectId(lead_id)}, {"$set": allowed}, return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return _serialize_doc(updated)


def report_bounce(user_id: str, email_id: str) -> bool:
    """The user got "Address not found" for a sent email: never send to that address again, from any account.

    A marketplace contact is also taken out of the shared database, so nobody else is sold it. Credits aren't
    refunded automatically (anyone could claim a bounce); the admin can add credits by hand after checking."""
    if not ObjectId.is_valid(email_id):
        return False
    sent = emailsSent.find_one({"_id": ObjectId(email_id), "user_id": str(user_id), "email_status": True})
    if not sent:
        return False
    emailsSent.update_one({"_id": sent["_id"]}, {"$set": {"bounced": True, "bounced_at": _now()}})
    add_bad_address(sent["recipient_email"], "Reported bounce: address not found", "user", str(user_id))
    lead = leads.find_one({"email": sent["recipient_email"].lower()}, {"_id": 1})
    if lead:
        deactivate_lead(lead["_id"], "Bounced: address not found")
    db["ownedContacts"].update_one({"user_id": str(user_id), "email": sent["recipient_email"].lower()},
                                   {"$set": {"status": "bounced", "reason": "Reported bounce", "updated_at": _now()}})
    return True


def deactivate_lead(lead_id: Any, reason: str) -> None:
    """Undeliverable recruiters leave the active database for everyone; the admin can see why."""
    if ObjectId.is_valid(str(lead_id)):
        leads.update_one({"_id": ObjectId(str(lead_id))}, {"$set": {"active": False, "inactive_reason": reason, "deactivated_at": _now()}})


def delete_lead(lead_id: str) -> None:
    if ObjectId.is_valid(lead_id):
        leads.delete_one({"_id": ObjectId(lead_id)})


def list_leads(query: str = "", skip: int = 0, limit: int = 50) -> dict[str, Any]:
    filt: dict[str, Any] = {}
    if query:
        pattern = {"$regex": re.escape(query), "$options": "i"}
        filt = {"$or": [{"email": pattern}, {"name": pattern}, {"company": pattern}, {"role": pattern}]}
    docs = list(leads.find(filt).sort("created_at", -1).skip(skip).limit(limit))
    # How many users have bought each contact.
    usage = {row["_id"]: row["n"] for row in db["ownedContacts"].aggregate([
        {"$match": {"email": {"$in": [doc["email"] for doc in docs]}}},
        {"$group": {"_id": "$email", "n": {"$sum": 1}}},
    ])}
    rows = _serialize_many(docs)
    for row in rows:
        row["times_used"] = usage.get(row["email"], 0)
    return {
        "leads": rows,
        "total": leads.count_documents(filt),
        "active": leads.count_documents({"active": True}),
        "unverified": leads.count_documents({"active": True, "verified_at": {"$exists": False}}),
    }


# ---------- Deliverability checks on the recruiter database ----------

def check_lead_domains(emails: list[str]) -> int:
    """Deactivate recruiters whose domain can't receive email (free DNS check). Returns how many."""
    from utils.email_check import dead_domains

    dead = dead_domains(emails)
    if dead:
        leads.update_many({"email": {"$in": list(dead)}, "active": True},
                          {"$set": {"active": False, "inactive_reason": "Domain doesn't accept email", "deactivated_at": _now()}})
    return len(dead)


def verify_leads(limit: int = 1000) -> dict[str, int]:
    """Mailbox-level check (paid provider) for active recruiters not verified yet; undeliverable ones are
    deactivated and added to the shared bad-address list."""
    from utils.email_check import verify_address

    checked = removed = 0
    for lead in leads.find({"active": True, "verified_at": {"$exists": False}}, {"email": 1}).limit(limit):
        deliverable, provider_status = verify_address(lead["email"])
        if provider_status in ("error", "not_configured"):
            break  # the provider is down or out of credits; try again later
        checked += 1
        update: dict[str, Any] = {"verified_at": _now(), "verify_status": provider_status}
        if deliverable is False:
            removed += 1
            update.update(active=False, inactive_reason=f"Mailbox check: {provider_status}", deactivated_at=_now())
            add_bad_address(lead["email"], f"Mailbox check: {provider_status}", "verification")
        leads.update_one({"_id": lead["_id"]}, {"$set": update})
    return {"checked": checked, "removed": removed}


# ---------- Automation state on the user document ----------

def set_automation(user_id: str, fields: dict[str, Any]) -> None:
    users.update_one({"_id": ObjectId(user_id)}, {"$set": {f"automation.{key}": value for key, value in fields.items()}})


def get_automation(user: dict[str, Any]) -> dict[str, Any]:
    return dict(user.get("automation") or {"status": "idle"})


def admin_stats() -> dict[str, Any]:
    from utils.plans import week_start

    now = _now()
    return {
        "users": users.count_documents({}),
        "pro_active": users.count_documents({"plan": "pro", "plan_until": {"$gt": now}}),
        "premium_active": users.count_documents({"plan": "premium", "plan_until": {"$gt": now}}),
        "leads_active": leads.count_documents({"active": True}),
        "leads_total": leads.count_documents({}),
        "sent_week": emailsSent.count_documents({"sent_at": {"$gte": week_start()}}),
        "automations_running": users.count_documents({"automation.status": "running"}),
        "credits_held": next(iter(users.aggregate([{"$group": {"_id": None, "n": {"$sum": "$credits"}}}])), {}).get("n", 0),
    }
