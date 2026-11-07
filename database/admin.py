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
    leadSends,
    leads,
    plan_of,
    premiumGrants,
    users,
)

LEAD_FIELDS = ("email", "name", "company", "role", "details")


# ---------- Plan grants (Pro / Premium) ----------

def _database_sent(user_id: str) -> int:
    return leadSends.count_documents({"user_id": str(user_id), "status": "sent"})


def grant_plan(email: str, plan: str, days: int, granted_by: str, note: str = "") -> dict[str, Any]:
    """Give an account Pro or Premium for `days`. Works before the person signs up.

    Buying the same plan again extends it from the current expiry; switching plans starts now. Every grant
    resets the database allowance, so each purchase gets a full batch of recruiters the user hasn't emailed."""
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
        users.update_one({"_id": user["_id"]}, {"$set": {"plan": plan, "plan_until": until, "db_base": _database_sent(str(user["_id"]))}})
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
    users.update_one({"email": email}, {"$unset": {"plan": "", "plan_until": "", "db_base": ""}})
    premiumGrants.update_many({"email": email, "pending": True}, {"$set": {"pending": False, "revoked": True}})
    premiumGrants.insert_one({"email": email, "days": 0, "revoked": True, "granted_by": revoked_by, "created_at": _now()})


def apply_pending_plan(user: dict[str, Any]) -> None:
    """Called at signup so a grant made before the account existed takes effect."""
    pending = premiumGrants.find_one({"email": user["email"], "pending": True}, sort=[("created_at", -1)])
    if pending and as_utc(pending["until"]) > _now():
        users.update_one({"_id": user["_id"]}, {"$set": {"plan": pending.get("plan") or "premium", "plan_until": pending["until"], "db_base": 0}})
    premiumGrants.update_many({"email": user["email"], "pending": True}, {"$set": {"pending": False}})


def recent_grants(limit: int = 30) -> list[dict[str, Any]]:
    grants = _serialize_many(premiumGrants.find().sort("created_at", -1).limit(limit))
    for grant in grants:
        grant.setdefault("plan", "premium")
    return grants


# ---------- Users overview ----------

def list_users_overview(query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    from utils.plans import pricing, week_start

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
    lead_counts = {row["_id"]: row["n"] for row in leadSends.aggregate([
        {"$match": {"user_id": {"$in": ids}, "status": "sent"}},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
    ])}
    prices = pricing()
    rows = []
    for user in listed:
        uid = str(user["_id"])
        stats = totals.get(uid, {})
        plan = plan_of(user)
        # Same maths as utils.plans.database_allowance, reusing the aggregated counts instead of a query per user.
        db_limit = prices[plan]["contacts"] if plan != "free" else 0
        db_used = max(0, lead_counts.get(uid, 0) - int(user.get("db_base") or 0)) if plan != "free" else 0
        rows.append({
            "id": uid,
            "email": user.get("email"),
            "name": (user.get("profile") or {}).get("full_name") or user.get("name") or "",
            "role": user.get("role") or "student",
            "plan": plan,
            "plan_until": user.get("plan_until"),
            "db_allowance": {"limit": db_limit, "used": db_used, "remaining": max(0, db_limit - db_used)},
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


def report_bounce(user_id: str, email_id: str) -> bool:
    """The user got "Address not found" for a sent email: never send to that address again, from any account.

    For a recruiter-database send, the recruiter is taken out of the database and the user gets that slot back."""
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
        leadSends.update_one({"user_id": str(user_id), "lead_id": str(lead["_id"])}, {"$set": {"status": "bounced"}})
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
    usage = {row["_id"]: row["n"] for row in leadSends.aggregate([
        {"$match": {"lead_id": {"$in": [str(doc["_id"]) for doc in docs]}, "status": "sent"}},
        {"$group": {"_id": "$lead_id", "n": {"$sum": 1}}},
    ])}
    rows = _serialize_many(docs)
    for row in rows:
        row["times_used"] = usage.get(row["id"], 0)
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


# ---------- Per-user lead usage (database automation) ----------

def _unused_leads_pipeline(user_id: str) -> list[dict[str, Any]]:
    """Active leads with no leadSends row for this user, using the (user_id, lead_id) index per lead
    instead of loading every lead the user has ever emailed."""
    return [
        {"$match": {"active": True}},
        {"$sort": {"created_at": 1, "_id": 1}},
        {"$addFields": {"_lead_id": {"$toString": "$_id"}}},
        {"$lookup": {
            "from": leadSends.name,
            "localField": "_lead_id",
            "foreignField": "lead_id",
            "pipeline": [{"$match": {"user_id": str(user_id)}}, {"$limit": 1}, {"$project": {"_id": 1}}],
            "as": "_used",
        }},
        {"$match": {"_used": {"$size": 0}}},
    ]


def next_lead_for(user_id: str) -> dict[str, Any] | None:
    """The oldest active lead this user hasn't been sent to yet, so stopping and restarting resumes in place."""
    rows = list(leads.aggregate(_unused_leads_pipeline(user_id) + [{"$limit": 1}, {"$project": {"_lead_id": 0, "_used": 0}}]))
    return rows[0] if rows else None


def remaining_leads(user_id: str) -> int:
    rows = list(leads.aggregate(_unused_leads_pipeline(user_id) + [{"$count": "n"}]))
    return rows[0]["n"] if rows else 0


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
    """What a paid user may see about the database: companies and names they've emailed, never raw addresses."""
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
        "pro_active": users.count_documents({"plan": "pro", "plan_until": {"$gt": now}}),
        "premium_active": users.count_documents({"plan": "premium", "plan_until": {"$gt": now}}),
        "leads_active": leads.count_documents({"active": True}),
        "leads_total": leads.count_documents({}),
        "sent_week": emailsSent.count_documents({"sent_at": {"$gte": week_start()}}),
        "automations_running": users.count_documents({"automation.status": "running"}),
    }
