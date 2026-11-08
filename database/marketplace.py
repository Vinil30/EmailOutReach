"""The data marketplace: contacts users buy with credits, kept inside Mailzen.

Bought contacts live in ownedContacts and are only ever emailed by automation; their addresses are never
returned to the browser, so the data can't be downloaded or copied out. Every purchase is a marketplaceJobs
record: credits are reserved up front, charged per contact actually delivered, and the rest is refunded
(idempotently), including after a crash."""
import re
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo.errors import BulkWriteError, DuplicateKeyError

from database.credits import add_credits, spend_credits
from database.fxns import _now, _serialize_many, as_utc, db, emailsSent, leads, leadSends, users

ownedContacts = db["ownedContacts"]
marketplaceJobs = db["marketplaceJobs"]
searchCache = db["searchCache"]

SEARCH_CACHE_DAYS = 7
MAX_DATABASE_PACK = 500


class MarketplaceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def ensure_marketplace_indexes() -> None:
    ownedContacts.create_index([("user_id", 1), ("email", 1)], unique=True)
    ownedContacts.create_index([("user_id", 1), ("status", 1), ("created_at", 1)])
    # Indexes for the "is this recruiter new to this user?" lookups, which match on the address first.
    ownedContacts.create_index([("email", 1), ("user_id", 1)])
    emailsSent.create_index([("recipient_email", 1), ("user_id", 1)])
    leadSends.create_index([("lead_id", 1), ("user_id", 1)])
    marketplaceJobs.create_index([("user_id", 1), ("created_at", -1)])
    # At most one web search per user at a time, enforced by the database, not just by a check.
    marketplaceJobs.create_index("user_id", name="one_running_web_job", unique=True,
                                 partialFilterExpression={"status": "running", "type": "web"})
    searchCache.create_index("created_at", expireAfterSeconds=SEARCH_CACHE_DAYS * 24 * 3600)


# ---------- Owned contacts ----------

def owned_counts(user_id: str) -> dict[str, int]:
    counts = {"available": 0, "sent": 0, "skipped": 0, "failed": 0, "bounced": 0}
    for row in ownedContacts.aggregate([{"$match": {"user_id": str(user_id)}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts


def next_owned_contact(user_id: str) -> dict[str, Any] | None:
    """The oldest bought contact not emailed yet; automation works through these in order."""
    return ownedContacts.find_one({"user_id": str(user_id), "status": "available"}, sort=[("created_at", 1), ("_id", 1)])


def mark_owned(contact_id: Any, status: str, reason: str = "", email_id: str | None = None) -> None:
    ownedContacts.update_one({"_id": contact_id}, {"$set": {"status": status, "reason": reason, "email_id": email_id, "updated_at": _now()}})


def owned_contacts_view(user_id: str, status: str | None = None, skip: int = 0, limit: int = 50) -> dict[str, Any]:
    """What the user may see about contacts they bought: never the email address."""
    query: dict[str, Any] = {"user_id": str(user_id)}
    if status:
        query["status"] = status
    fields = {"name": 1, "company": 1, "role": 1, "source": 1, "status": 1, "reason": 1, "created_at": 1, "updated_at": 1}
    rows = _serialize_many(ownedContacts.find(query, fields).sort("updated_at", -1).skip(skip).limit(limit))
    return {"contacts": rows, "total": ownedContacts.count_documents(query)}


def contact_history(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for row in ownedContacts.find({"user_id": str(user_id), "status": {"$ne": "available"}}).sort("updated_at", -1).limit(limit):
        rows.append({"company": row.get("company") or "—", "name": row.get("name") or "", "role": row.get("role") or "",
                     "status": row.get("status"), "reason": row.get("reason") or "", "at": row.get("updated_at")})
    return rows


def _new_contacts_pipeline(user_id: str, match: dict[str, Any]) -> list[dict[str, Any]]:
    """Active database recruiters this user doesn't own, hasn't emailed, and hasn't reached through the old allowance."""
    uid = str(user_id)
    return [
        {"$match": {"active": True, **match}},
        {"$sort": {"created_at": 1, "_id": 1}},
        {"$lookup": {"from": ownedContacts.name, "localField": "email", "foreignField": "email",
                     "pipeline": [{"$match": {"user_id": uid}}, {"$limit": 1}, {"$project": {"_id": 1}}], "as": "_owned"}},
        {"$match": {"_owned": {"$size": 0}}},
        {"$lookup": {"from": emailsSent.name, "localField": "email", "foreignField": "recipient_email",
                     "pipeline": [{"$match": {"user_id": uid}}, {"$limit": 1}, {"$project": {"_id": 1}}], "as": "_sent"}},
        {"$match": {"_sent": {"$size": 0}}},
        {"$addFields": {"_lead_id": {"$toString": "$_id"}}},
        {"$lookup": {"from": leadSends.name, "localField": "_lead_id", "foreignField": "lead_id",
                     "pipeline": [{"$match": {"user_id": uid}}, {"$limit": 1}, {"$project": {"_id": 1}}], "as": "_old"}},
        {"$match": {"_old": {"$size": 0}}},
        {"$project": {"_owned": 0, "_sent": 0, "_old": 0, "_lead_id": 0}},
    ]


def _role_match(keywords: list[str]) -> dict[str, Any]:
    words = [word.strip() for word in keywords if word and word.strip()]
    if not words:
        return {}
    pattern = "|".join(re.escape(word) for word in words)
    regex = {"$regex": pattern, "$options": "i"}
    return {"$or": [{"role": regex}, {"company": regex}, {"details": regex}, {"tags": regex}]}


def available_database_contacts(user_id: str, keywords: list[str] | None = None) -> int:
    rows = list(leads.aggregate(_new_contacts_pipeline(user_id, _role_match(keywords or [])) + [{"$count": "n"}]))
    return rows[0]["n"] if rows else 0


def take_database_contacts(user_id: str, job_id: str, count: int, price: int, keywords: list[str] | None = None,
                           source: str = "database") -> int:
    """Move up to `count` matching database recruiters into the user's owned contacts. Returns how many were added."""
    if count <= 0:
        return 0
    candidates = list(leads.aggregate(_new_contacts_pipeline(user_id, _role_match(keywords or [])) + [{"$limit": count}]))
    docs = [_owned_doc(user_id, job_id, lead, source, price) for lead in candidates]
    return _insert_owned(docs)


def _owned_doc(user_id: str, job_id: str, lead: dict[str, Any], source: str, price: int) -> dict[str, Any]:
    now = _now()
    return {
        "user_id": str(user_id), "email": lead["email"].lower(), "name": lead.get("name", ""), "company": lead.get("company", ""),
        "role": lead.get("role", ""), "details": lead.get("details", ""), "lead_id": str(lead["_id"]) if lead.get("_id") else None,
        "source": source, "price": int(price), "job_id": job_id, "status": "available", "created_at": now, "updated_at": now,
    }


def _insert_owned(docs: list[dict[str, Any]]) -> int:
    """Insert, skipping any the user already owns (a parallel purchase can't double-sell the same contact)."""
    if not docs:
        return 0
    try:
        return len(ownedContacts.insert_many(docs, ordered=False).inserted_ids)
    except BulkWriteError as exc:
        return exc.details.get("nInserted", 0)


def add_owned(user_id: str, job_id: str, lead: dict[str, Any], source: str, price: int) -> bool:
    try:
        ownedContacts.insert_one(_owned_doc(user_id, job_id, lead, source, price))
        return True
    except DuplicateKeyError:
        return False


def owns_or_emailed(user_id: str, email: str) -> bool:
    email = email.lower()
    return bool(ownedContacts.find_one({"user_id": str(user_id), "email": email}, {"_id": 1})
                or emailsSent.find_one({"user_id": str(user_id), "recipient_email": email}, {"_id": 1}))


def save_search_tags(user_id: str, tags: list[str]) -> None:
    users.update_one({"_id": ObjectId(user_id)}, {"$set": {"profile.search_tags": tags}})


# ---------- Jobs (every purchase) ----------

def create_job(user_id: str, job_type: str, target: int, reserved: int, details: dict[str, Any]) -> dict[str, Any]:
    """Create the job, then reserve its credits. Raises MarketplaceError if another web search is running or credits are short."""
    now = _now()
    job = {"user_id": str(user_id), "type": job_type, "target": int(target), "reserved": int(reserved), "spent": 0, "refunded": 0,
           "delivered": 0, "from_database": 0, "from_web": 0, "status": "running", "message": "", "stats": {},
           "created_at": now, "updated_at": now, **details}
    try:
        job["_id"] = marketplaceJobs.insert_one(job).inserted_id
    except DuplicateKeyError as exc:
        raise MarketplaceError("A web search is already running. Wait for it to finish first.", 409) from exc
    if not spend_credits(user_id, reserved, f"{job_type}_reserve", f"Reserved for {target} contacts", ref=str(job["_id"])):
        marketplaceJobs.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "message": "Not enough credits", "reserved": 0}})
        raise MarketplaceError("You don't have enough credits for this. Buy more in the marketplace.", 402)
    return job


def record_delivery(job_id: ObjectId, cost: int, source: str) -> None:
    field = "from_database" if source == "database" else "from_web"
    marketplaceJobs.update_one({"_id": job_id}, {"$inc": {"delivered": 1, "spent": int(cost), field: 1}, "$set": {"updated_at": _now()}})


def finish_job(job_id: ObjectId, status: str, message: str = "", stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """Close the job and refund whatever was reserved but not spent (exactly once, even if called again)."""
    job = marketplaceJobs.find_one({"_id": job_id})
    refund = max(0, int(job["reserved"]) - int(job["spent"]))
    if refund:
        add_credits(job["user_id"], refund, "refund", f"Unused credits from {job['type']} purchase", idem=f"refund:{job_id}", ref=str(job_id))
    update = {"status": status, "message": message, "refunded": refund, "finished_at": _now(), "updated_at": _now()}
    if stats is not None:
        update["stats"] = stats
    marketplaceJobs.update_one({"_id": job_id}, {"$set": update})
    return marketplaceJobs.find_one({"_id": job_id})


def jobs_for(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = _serialize_many(marketplaceJobs.find({"user_id": str(user_id)}).sort("created_at", -1).limit(limit))
    for row in rows:
        (row.get("stats") or {}).pop("emails", None)
    return rows


def recover_interrupted_jobs() -> int:
    """At startup: jobs that were running when the server stopped get their unspent credits back."""
    count = 0
    for job in marketplaceJobs.find({"status": "running"}):
        finish_job(job["_id"], "interrupted", "Stopped because the server restarted. Unused credits were returned.")
        count += 1
    return count


# ---------- Search cache (shared by every user) ----------

def cached_search(key: str) -> list[dict[str, Any]] | None:
    row = searchCache.find_one({"_id": key})
    return row["results"] if row else None


def store_search(key: str, query: str, results: list[dict[str, Any]]) -> None:
    searchCache.update_one({"_id": key}, {"$set": {"query": query, "results": results, "created_at": _now()}}, upsert=True)


# ---------- One-time move from plan allowances to credits ----------

def migrate_allowances(database_price: int) -> int:
    """Accounts that bought Pro/Premium when plans included recruiters keep what they paid for: the unused
    recruiters become credits (at the database contact price). Runs once per account."""
    legacy_limits = {"pro": 200, "premium": 500}
    stored = db["settings"].find_one({"_id": "pricing"}) or {}
    for plan in legacy_limits:
        legacy_limits[plan] = int((stored.get(plan) or {}).get("contacts", legacy_limits[plan]))
    moved = 0
    now = _now()
    for user in users.find({"db_base": {"$exists": True}, "credits_migrated": {"$ne": True}}):
        until = as_utc(user.get("plan_until"))
        remaining = 0
        if user.get("plan") in legacy_limits and until and until > now:
            used = leadSends.count_documents({"user_id": str(user["_id"]), "status": "sent"}) - int(user.get("db_base") or 0)
            remaining = max(0, legacy_limits[user["plan"]] - max(0, used))
        if remaining:
            add_credits(str(user["_id"]), remaining * database_price, "migration",
                        f"{remaining} unused recruiters from your plan, converted to credits", idem=f"migration:{user['_id']}")
            moved += 1
        users.update_one({"_id": user["_id"]}, {"$set": {"credits_migrated": True}, "$unset": {"db_base": ""}})
    return moved


def admin_job_summary(limit: int = 30) -> dict[str, Any]:
    since = _now() - timedelta(days=30)
    totals = list(marketplaceJobs.aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$type", "jobs": {"$sum": 1}, "delivered": {"$sum": "$delivered"}, "spent": {"$sum": "$spent"},
                    "searches": {"$sum": "$stats.searches"}, "pages": {"$sum": "$stats.pages"}}},
    ]))
    recent = _serialize_many(marketplaceJobs.find().sort("created_at", -1).limit(limit))
    for row in recent:
        (row.get("stats") or {}).pop("emails", None)
    return {"last_30_days": {row["_id"]: row for row in totals}, "recent": recent}
