"""Admin-managed data: the shared lead database, premium grants, and per-user lead usage."""
import re
from datetime import timedelta
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.fxns import (
    _now,
    _serialize_doc,
    _serialize_many,
    as_utc,
    emailsSent,
    get_user_by_email,
    is_premium,
    leadSends,
    leads,
    premiumGrants,
    users,
)

LEAD_FIELDS = ("email", "name", "company", "role", "details")


# ---------- Premium grants ----------

def grant_premium(email: str, days: int, granted_by: str, note: str = "") -> dict[str, Any]:
    """Extend premium from whichever is later: now or the current expiry. Works before the person signs up."""
    email = email.strip().lower()
    user = get_user_by_email(email)
    now = _now()
    if user:
        current = as_utc(user.get("premium_until"))
        start = current if current and current > now else now
        until = start + timedelta(days=days)
        users.update_one({"_id": user["_id"]}, {"$set": {"premium_until": until}})
    else:
        pending = premiumGrants.find_one({"email": email, "pending": True}, sort=[("created_at", -1)])
        until = (as_utc(pending["until"]) if pending else now) + timedelta(days=days)
    premiumGrants.insert_one(
        {
            "email": email,
            "days": days,
            "until": until,
            "pending": not user,
            "granted_by": granted_by,
            "note": note,
            "created_at": now,
        }
    )
    return {"email": email, "premium_until": until, "account_exists": bool(user)}


def revoke_premium(email: str, revoked_by: str) -> None:
    email = email.strip().lower()
    users.update_one({"email": email}, {"$unset": {"premium_until": ""}})
    premiumGrants.update_many({"email": email, "pending": True}, {"$set": {"pending": False, "revoked": True}})
    premiumGrants.insert_one({"email": email, "days": 0, "revoked": True, "granted_by": revoked_by, "created_at": _now()})


def apply_pending_premium(user: dict[str, Any]) -> None:
    """Called at signup so a grant made before the account existed takes effect."""
    pending = premiumGrants.find_one({"email": user["email"], "pending": True}, sort=[("created_at", -1)])
    if pending and as_utc(pending["until"]) > _now():
        users.update_one({"_id": user["_id"]}, {"$set": {"premium_until": pending["until"]}})
    premiumGrants.update_many({"email": user["email"], "pending": True}, {"$set": {"pending": False}})


def recent_grants(limit: int = 30) -> list[dict[str, Any]]:
    return _serialize_many(premiumGrants.find().sort("created_at", -1).limit(limit))


# ---------- Users overview ----------

def list_users_overview(query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    from utils.plans import week_start

    filt: dict[str, Any] = {}
    if query:
        filt["email"] = {"$regex": re.escape(query.lower())}
    start = week_start()
    totals = {row["_id"]: row for row in emailsSent.aggregate([
        {"$group": {
            "_id": "$user_id",
            "total": {"$sum": 1},
            "week": {"$sum": {"$cond": [{"$gte": ["$sent_at", start]}, 1, 0]}},
        }},
    ])}
    lead_counts = {row["_id"]: row["n"] for row in leadSends.aggregate([
        {"$match": {"status": "sent"}},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
    ])}
    rows = []
    for user in users.find(filt).sort("created_at", -1).limit(limit):
        uid = str(user["_id"])
        stats = totals.get(uid, {})
        rows.append({
            "id": uid,
            "email": user.get("email"),
            "name": (user.get("profile") or {}).get("full_name") or user.get("name") or "",
            "role": user.get("role") or "student",
            "is_premium": is_premium(user),
            "premium_until": user.get("premium_until"),
            "sent_total": stats.get("total", 0),
            "sent_week": stats.get("week", 0),
            "db_sent": lead_counts.get(uid, 0),
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


def delete_lead(lead_id: str) -> None:
    if ObjectId.is_valid(lead_id):
        leads.delete_one({"_id": ObjectId(lead_id)})


def list_leads(query: str = "", skip: int = 0, limit: int = 50) -> dict[str, Any]:
    filt: dict[str, Any] = {}
    if query:
        pattern = {"$regex": re.escape(query), "$options": "i"}
        filt = {"$or": [{"email": pattern}, {"name": pattern}, {"company": pattern}, {"role": pattern}]}
    docs = list(leads.find(filt).sort("created_at", -1).skip(skip).limit(limit))
    usage = {row["_id"]: row["n"] for row in leadSends.aggregate([
        {"$match": {"lead_id": {"$in": [str(doc["_id"]) for doc in docs]}, "status": "sent"}},
        {"$group": {"_id": "$lead_id", "n": {"$sum": 1}}},
    ])}
    rows = _serialize_many(docs)
    for row in rows:
        row["times_used"] = usage.get(row["id"], 0)
    return {"leads": rows, "total": leads.count_documents(filt), "active": leads.count_documents({"active": True})}


# ---------- Per-user lead usage (premium automation) ----------

def used_lead_ids(user_id: str) -> list[str]:
    return [row["lead_id"] for row in leadSends.find({"user_id": str(user_id)}, {"lead_id": 1})]


def next_lead_for(user_id: str) -> dict[str, Any] | None:
    """The oldest active lead this user hasn't been sent to yet, so stopping and restarting resumes in place."""
    used = [ObjectId(lead_id) for lead_id in used_lead_ids(user_id) if ObjectId.is_valid(lead_id)]
    return leads.find_one({"active": True, "_id": {"$nin": used}}, sort=[("created_at", 1), ("_id", 1)])


def remaining_leads(user_id: str) -> int:
    used = [ObjectId(lead_id) for lead_id in used_lead_ids(user_id) if ObjectId.is_valid(lead_id)]
    return leads.count_documents({"active": True, "_id": {"$nin": used}})


def record_lead_send(user_id: str, lead: dict[str, Any], outcome: str, email_id: str | None = None, reason: str = "") -> None:
    leadSends.update_one(
        {"user_id": str(user_id), "lead_id": str(lead["_id"])},
        {"$set": {
            "status": outcome,
            "company": lead.get("company", ""),
            "name": lead.get("name", ""),
            "role": lead.get("role", ""),
            "email_id": email_id,
            "reason": reason,
            "created_at": _now(),
        }},
        upsert=True,
    )


def lead_send_history(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """What a premium user may see about the database: companies and names they've emailed, never raw addresses."""
    rows = []
    for row in leadSends.find({"user_id": str(user_id)}).sort("created_at", -1).limit(limit):
        rows.append({
            "company": row.get("company") or "—",
            "name": row.get("name") or "",
            "role": row.get("role") or "",
            "status": row.get("status"),
            "reason": row.get("reason") or "",
            "at": row.get("created_at"),
        })
    return rows


def lead_send_counts(user_id: str) -> dict[str, int]:
    counts = {"sent": 0, "failed": 0}
    for row in leadSends.aggregate([{"$match": {"user_id": str(user_id)}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    return counts


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
        "premium_active": users.count_documents({"premium_until": {"$gt": now}}),
        "leads_active": leads.count_documents({"active": True}),
        "leads_total": leads.count_documents({}),
        "sent_week": emailsSent.count_documents({"sent_at": {"$gte": week_start()}}),
        "automations_running": users.count_documents({"automation.status": "running"}),
    }
