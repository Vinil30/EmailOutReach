from datetime import datetime, timedelta, timezone
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.collection import Collection
from pymongo import ReturnDocument

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("MONGO_DB_NAME", "OutReach")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-this-secret-key")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

if os.environ.get("APP_ENV") == "production" and JWT_SECRET_KEY == "change-this-secret-key":
    raise RuntimeError("Set JWT_SECRET_KEY before running in production")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

db_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=int(os.environ.get("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")),
    connectTimeoutMS=int(os.environ.get("MONGO_CONNECT_TIMEOUT_MS", "20000")),
    socketTimeoutMS=int(os.environ.get("MONGO_SOCKET_TIMEOUT_MS", "20000")),
)
db = db_client[DB_NAME]
users: Collection = db["users"]
emailsSent: Collection = db["emailsSent"]
emailsGenerated: Collection = db["emailsHold"]
projects: Collection = db["projects"]
campaigns: Collection = db["campaigns"]
leads: Collection = db["leads"]
leadSends: Collection = db["leadSends"]
premiumGrants: Collection = db["premiumGrants"]

ADMIN_EMAILS = {email.strip().lower() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()}

ROLES = ("student", "campaigner")
STUDENT_PROFILE_FIELDS = ("full_name", "headline", "school", "skills", "goal", "portfolio_url", "resume_url", "signature")
TEMPLATE_FIELDS = ("template_id", "custom_subject", "custom_body", "featured_project")
CAMPAIGNER_PROFILE_FIELDS = (
    "full_name",
    "organization",
    "website",
    "offer",
    "audience",
    "tone",
    "physical_address",
    "unsubscribe_text",
    "signature",
)
REJECTED_DIR = Path(os.environ.get("REJECTED_EMAILS_DIR", "database/rejected"))
REJECTED_COLUMNS = [
    "rejected_at",
    "user_id",
    "mail_id",
    "company_name",
    "recipient_name",
    "recipient_email",
    "email_from",
    "email_subject",
    "email_body",
    "relevant_projects",
    "campaign_name",
]


def ensure_indexes() -> None:
    try:
        users.create_index("email", unique=True)
        emailsSent.create_index([("user_id", 1), ("created_at", -1)])
        emailsSent.create_index("send_fingerprint", unique=True, sparse=True)
        emailsGenerated.create_index([("user_id", 1), ("email_status", 1), ("created_at", -1)])
        emailsGenerated.create_index([("user_id", 1), ("outreach_status", 1), ("updated_at", -1)])
        emailsGenerated.create_index([("user_id", 1), ("campaign_id", 1)])
        emailsSent.create_index([("user_id", 1), ("campaign_id", 1)])
        projects.create_index([("user_id", 1), ("created_at", -1)])
        campaigns.create_index([("user_id", 1), ("created_at", -1)])
        emailsSent.create_index([("user_id", 1), ("sent_at", -1)])
        leads.create_index("email", unique=True)
        leads.create_index([("active", 1), ("created_at", 1)])
        leadSends.create_index([("user_id", 1), ("lead_id", 1)], unique=True)
        leadSends.create_index([("user_id", 1), ("created_at", -1)])
        premiumGrants.create_index([("email", 1), ("created_at", -1)])
        users.update_many(
            {"automation.status": "running"},
            {"$set": {"automation.status": "stopped", "automation.message": "Stopped because the server restarted. Press Start to resume."}},
        )
        # Background runs die with the process; surface that instead of showing them as running forever.
        campaigns.update_many(
            {"status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "interrupted", "updated_at": _now()}},
        )
    except PyMongoError as exc:
        if os.environ.get("REQUIRE_MONGO_ON_STARTUP", "false").lower() == "true":
            raise
        print(f"MongoDB index creation skipped during startup: {exc}", flush=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120000)
    return f"{salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, stored_digest = password_hash.split("$", 1)
    except ValueError:
        return False
    candidate = _hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, stored_digest)


def _serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    serialized = dict(doc)
    serialized["id"] = str(serialized.pop("_id"))
    return serialized


def _serialize_many(docs) -> list[dict[str, Any]]:
    return [_serialize_doc(doc) for doc in docs]


def _rejected_csv_path(user_id: str) -> Path:
    safe_user_id = "".join(char for char in str(user_id) if char.isalnum() or char in ("-", "_"))
    return REJECTED_DIR / f"{safe_user_id}_rejected_by_human.csv"


def ensure_rejected_csv(user_id: str) -> Path:
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    path = _rejected_csv_path(user_id)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=REJECTED_COLUMNS)
            writer.writeheader()
    return path


def get_user_by_email(email: str) -> dict[str, Any] | None:
    return users.find_one({"email": email.lower().strip()})


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(user_id):
        return None
    return users.find_one({"_id": ObjectId(user_id)})


def create_user(email: str, password: str, name: str | None = None, role: str = "student") -> dict[str, Any]:
    normalized_email = email.lower().strip()
    if get_user_by_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    if role not in ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")

    result = users.insert_one(
        {
            "email": normalized_email,
            "name": name,
            "role": role,
            "profile": {"full_name": name or ""},
            "password_hash": _hash_password(password),
            "created_at": _now(),
        }
    )
    user = users.find_one({"_id": result.inserted_id})
    return public_user(user)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_email(email)
    if not user or not _verify_password(password, user.get("password_hash", "")):
        return None
    return user


def create_access_token(user_id: str) -> str:
    expires_at = _now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def public_user(user: dict[str, Any] | None) -> dict[str, Any]:
    serialized = _serialize_doc(user)
    if not serialized:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    serialized.pop("password_hash", None)
    serialized.pop("gmail_tokens", None)
    serialized["gmail_connected"] = bool(user.get("gmail_tokens", {}).get("refresh_token") or user.get("gmail_tokens", {}).get("access_token"))
    serialized["role"] = user.get("role") or "student"
    serialized["profile"] = user.get("profile") or {}
    serialized["is_admin"] = is_admin(user)
    premium_until = user.get("premium_until")
    serialized["premium_until"] = premium_until
    serialized["is_premium"] = is_premium(user)
    serialized.pop("automation", None)
    serialized.pop("suppressed_emails", None)
    return serialized


def is_admin(user: dict[str, Any] | None) -> bool:
    return bool(user) and (user.get("email", "").lower() in ADMIN_EMAILS or bool(user.get("is_admin")))


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_premium(user: dict[str, Any] | None) -> bool:
    until = as_utc((user or {}).get("premium_until"))
    return bool(until and until > _now())


def update_user_profile(user_id: str, role: str | None, profile: dict[str, Any]) -> dict[str, Any]:
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    next_role = role or user.get("role") or "student"
    if next_role not in ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")

    allowed = set(STUDENT_PROFILE_FIELDS) | set(CAMPAIGNER_PROFILE_FIELDS) | set(TEMPLATE_FIELDS)
    merged = dict(user.get("profile") or {})
    merged.update({key: str(value or "").strip() for key, value in profile.items() if key in allowed})
    users.update_one(
        {"_id": user["_id"]},
        {"$set": {"role": next_role, "profile": merged, "name": merged.get("full_name") or user.get("name")}},
    )
    return public_user(users.find_one({"_id": user["_id"]}))


def set_suppressed_emails(user_id: str, emails: list[str]) -> None:
    if ObjectId.is_valid(user_id):
        users.update_one({"_id": ObjectId(user_id)}, {"$set": {"suppressed_emails": emails}})


def list_projects(user_id: str) -> list[dict[str, Any]]:
    return _serialize_many(projects.find({"user_id": str(user_id)}).sort("created_at", 1))


def project_catalog(user_id: str) -> dict[str, str]:
    """Projects as name -> description, the shape the project selector and writer consume."""
    catalog = {}
    for project in projects.find({"user_id": str(user_id)}).sort("created_at", 1):
        parts = [project.get("summary", "")]
        if project.get("tech"):
            parts.append(f"Tech: {project['tech']}.")
        if project.get("impact"):
            parts.append(f"Impact: {project['impact']}.")
        if project.get("link"):
            parts.append(f"Link: {project['link']}")
        catalog[project["name"]] = " ".join(part for part in parts if part)
    return catalog


def _clean_project(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: str(data.get(key) or "").strip() for key in ("name", "summary", "tech", "impact", "link")}
    if not cleaned["name"] or not cleaned["summary"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project name and summary are required")
    return cleaned


def create_project(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    doc = _clean_project(data)
    doc.update({"user_id": str(user_id), "created_at": _now(), "updated_at": _now()})
    result = projects.insert_one(doc)
    return _serialize_doc(projects.find_one({"_id": result.inserted_id}))


def update_project(user_id: str, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    updated = projects.find_one_and_update(
        {"_id": ObjectId(project_id), "user_id": str(user_id)},
        {"$set": {**_clean_project(data), "updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return _serialize_doc(updated)


def delete_project(user_id: str, project_id: str) -> None:
    if ObjectId.is_valid(project_id):
        projects.delete_one({"_id": ObjectId(project_id), "user_id": str(user_id)})


def create_campaign(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    doc = dict(data)
    doc.update(
        {
            "user_id": str(user_id),
            "status": "queued",
            "processed": 0,
            "errors": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    result = campaigns.insert_one(doc)
    return _serialize_doc(campaigns.find_one({"_id": result.inserted_id}))


def update_campaign(
    campaign_id: str,
    fields: dict[str, Any] | None = None,
    inc: dict[str, int] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    update: dict[str, Any] = {"$set": {**(fields or {}), "updated_at": _now()}}
    if inc:
        update["$inc"] = inc
    if error:
        update["$push"] = {"errors": {"$each": [error], "$slice": -50}}
    campaigns.update_one({"_id": ObjectId(campaign_id)}, update)


def get_campaign_doc(campaign_id: str, user_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(campaign_id):
        return None
    return campaigns.find_one({"_id": ObjectId(campaign_id), "user_id": str(user_id)})


def _empty_counts() -> dict[str, int]:
    return {"sent": 0, "waiting": 0, "flagged": 0, "failed": 0}


def _campaign_counts(user_id: str, campaign_ids: list[str]) -> dict[str, dict[str, int]]:
    counts = {cid: _empty_counts() for cid in campaign_ids}
    match = {"user_id": str(user_id), "campaign_id": {"$in": campaign_ids}}
    for row in emailsSent.aggregate([{"$match": match}, {"$group": {"_id": "$campaign_id", "n": {"$sum": 1}}}]):
        counts.setdefault(row["_id"], _empty_counts())["sent"] = row["n"]
    pipeline = [{"$match": match}, {"$group": {"_id": {"c": "$campaign_id", "s": "$outreach_status"}, "n": {"$sum": 1}}}]
    for row in emailsGenerated.aggregate(pipeline):
        bucket = counts.setdefault(row["_id"]["c"], _empty_counts())
        state = row["_id"].get("s") or ""
        if state.startswith("FAILED"):
            bucket["failed"] += row["n"]
        elif state == "REGENERATE":
            bucket["flagged"] += row["n"]
        bucket["waiting"] += row["n"]
    return counts


def _with_counts(user_id: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized = _serialize_many(docs)
    counts = _campaign_counts(user_id, [doc["id"] for doc in serialized])
    for doc in serialized:
        doc["counts"] = counts.get(doc["id"], _empty_counts())
    return serialized


def list_campaigns(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    docs = list(campaigns.find({"user_id": str(user_id)}, {"contacts": 0}).sort("created_at", -1).limit(limit))
    return _with_counts(user_id, docs)


def get_campaign(campaign_id: str, user_id: str) -> dict[str, Any] | None:
    doc = get_campaign_doc(campaign_id, user_id)
    return _with_counts(user_id, [doc])[0] if doc else None


def get_overview_stats(user_id: str) -> dict[str, Any]:
    uid = str(user_id)
    sent = list(
        emailsSent.aggregate(
            [
                {"$match": {"user_id": uid}},
                {"$group": {"_id": None, "avg": {"$avg": "$deliverability_risk.score"}, "n": {"$sum": 1}}},
            ]
        )
    )
    # One pass over the drafts instead of three separate counts.
    drafts = list(
        emailsGenerated.aggregate(
            [
                {"$match": {"user_id": uid}},
                {"$group": {
                    "_id": None,
                    "waiting": {"$sum": {"$cond": [{"$eq": ["$email_status", False]}, 1, 0]}},
                    "flagged": {"$sum": {"$cond": [{"$eq": ["$outreach_status", "REGENERATE"]}, 1, 0]}},
                    "failed": {"$sum": {"$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$outreach_status", ""]}, "regex": "^FAILED"}}, 1, 0,
                    ]}},
                }},
            ]
        )
    )
    draft_counts = drafts[0] if drafts else {}
    return {
        "sent": sent[0]["n"] if sent else 0,
        "avg_sent_risk": round(sent[0]["avg"] or 0, 2) if sent else 0,
        "waiting": draft_counts.get("waiting", 0),
        "flagged": draft_counts.get("flagged", 0),
        "failed": draft_counts.get("failed", 0),
        "campaigns": campaigns.count_documents({"user_id": uid}),
        "projects": projects.count_documents({"user_id": uid}),
    }


def save_gmail_tokens(user_id: str, token_payload: dict[str, Any]) -> None:
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    existing = get_gmail_tokens(user_id) or {}
    if "refresh_token" not in token_payload and existing.get("refresh_token"):
        token_payload["refresh_token"] = existing["refresh_token"]
    token_payload["updated_at"] = _now()
    users.update_one({"_id": ObjectId(user_id)}, {"$set": {"gmail_tokens": token_payload}})


def get_gmail_tokens(user_id: str) -> dict[str, Any] | None:
    user = get_user_by_id(user_id)
    if not user:
        return None
    return user.get("gmail_tokens")


def disconnect_gmail(user_id: str) -> None:
    if ObjectId.is_valid(user_id):
        users.update_one({"_id": ObjectId(user_id)}, {"$unset": {"gmail_tokens": ""}})


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_error
    except JWTError as exc:
        raise credentials_error from exc

    user = get_user_by_id(user_id)
    if not user:
        raise credentials_error
    return user


def save_email(
    projects,
    written_email_details,
    company_name,
    recipient_name,
    recipient_email,
    email_from,
    email_status,
    user_id,
    email_response: dict[str, Any] | None = None,
    deliverability_risk: dict[str, Any] | None = None,
    outreach_status: str | None = None,
    send_fingerprint: str | None = None,
    send_attempts: list[dict[str, Any]] | None = None,
    campaign_id: str | None = None,
    campaign_name: str | None = None,
    campaign_type: str | None = None,
    failure_reason: str | None = None,
):
    data = {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "campaign_type": campaign_type,
        "failure_reason": failure_reason,
        "user_id": str(user_id),
        "relevant_projects": projects or [],
        "written_email_details": written_email_details.model_dump(),
        "email_from": email_from,
        "company_name": company_name,
        "recipient_name": recipient_name,
        "recipient_email": recipient_email,
        "email_status": bool(email_status),
        "email_response": email_response,
        "deliverability_risk": deliverability_risk,
        "outreach_status": outreach_status or ("SENT" if email_status else "REVIEW_REQUIRED"),
        "send_fingerprint": send_fingerprint,
        "send_attempts": send_attempts or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    collection = emailsSent if email_status else emailsGenerated
    resp = collection.insert_one(data)
    return str(resp.inserted_id)


def make_send_fingerprint(user_id: str, recipient_email: str, email_subject: str, email_body: str) -> str:
    normalized = "\n".join(
        [
            str(user_id).strip(),
            recipient_email.lower().strip(),
            email_subject.strip(),
            email_body.strip(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_waiting_emails(user_id: str, campaign_id: str | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"user_id": str(user_id), "email_status": False}
    if campaign_id:
        query["campaign_id"] = campaign_id
    return _serialize_many(emailsGenerated.find(query).sort("created_at", -1))


def get_sent_emails(user_id: str, campaign_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"user_id": str(user_id), "email_status": True}
    if campaign_id:
        query["campaign_id"] = campaign_id
    return _serialize_many(emailsSent.find(query).sort("updated_at", -1).limit(limit))


def get_waiting_email(mail_id: str, user_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(mail_id):
        return None
    return emailsGenerated.find_one({"_id": ObjectId(mail_id), "user_id": str(user_id), "email_status": False})


def update_generated_email_details(
    mail_id: str,
    user_id: str,
    email_subject: str,
    email_body: str,
    deliverability_risk: dict[str, Any] | None = None,
    outreach_status: str = "REVIEW_APPROVED",
) -> dict[str, Any]:
    if not ObjectId.is_valid(mail_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")
    updated = emailsGenerated.find_one_and_update(
        {"_id": ObjectId(mail_id), "user_id": str(user_id), "email_status": False},
        {
            "$set": {
                "written_email_details": {"email_subject": email_subject, "email_body": email_body},
                "deliverability_risk": deliverability_risk,
                "outreach_status": outreach_status,
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")
    return _serialize_doc(updated)


def record_generated_send_result(
    mail_id: str,
    user_id: str,
    send_result: dict[str, Any],
    deliverability_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated = get_waiting_email(mail_id, user_id)
    if not generated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")

    details = generated.get("written_email_details", {})
    fingerprint = make_send_fingerprint(
        user_id,
        generated.get("recipient_email", ""),
        details.get("email_subject", ""),
        details.get("email_body", ""),
    )

    if emailsSent.find_one({"send_fingerprint": fingerprint, "user_id": str(user_id)}):
        duplicate_update = {
            "outreach_status": "DUPLICATE_SUPPRESSED",
            "send_fingerprint": fingerprint,
            "email_response": {"status": "DUPLICATE_SUPPRESSED"},
            "updated_at": _now(),
        }
        emailsGenerated.update_one({"_id": ObjectId(mail_id)}, {"$set": duplicate_update})
        generated.update(duplicate_update)
        return _serialize_doc(generated)

    generated.pop("_id", None)
    generated["send_fingerprint"] = fingerprint
    generated["send_attempts"] = send_result.get("history", [])
    generated["email_response"] = send_result
    generated["deliverability_risk"] = deliverability_risk or generated.get("deliverability_risk")
    generated["updated_at"] = _now()

    if send_result.get("status") == "SENT":
        generated["email_status"] = True
        generated["outreach_status"] = "SENT"
        generated["sent_at"] = _now()
        sent_result = emailsSent.insert_one(generated)
        emailsGenerated.delete_one({"_id": ObjectId(mail_id), "user_id": str(user_id)})
        return _serialize_doc(emailsSent.find_one({"_id": sent_result.inserted_id}))

    generated["email_status"] = False
    generated["outreach_status"] = send_result.get("status", "FAILED")
    generated["failure_reason"] = send_result.get("reason")
    emailsGenerated.update_one(
        {"_id": ObjectId(mail_id), "user_id": str(user_id)},
        {"$set": generated},
    )
    generated["_id"] = ObjectId(mail_id)
    return _serialize_doc(generated)


def reject_generated_email(
    mail_id: str,
    user_id: str,
    email_subject: str | None = None,
    email_body: str | None = None,
) -> dict[str, Any]:
    generated = get_waiting_email(mail_id, user_id)
    if not generated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")

    stored_details = generated.get("written_email_details", {})
    row = {
        "rejected_at": _now().isoformat(),
        "user_id": str(user_id),
        "mail_id": str(generated["_id"]),
        "company_name": generated.get("company_name", ""),
        "recipient_name": generated.get("recipient_name", ""),
        "recipient_email": generated.get("recipient_email", ""),
        "email_from": generated.get("email_from", ""),
        "email_subject": email_subject or stored_details.get("email_subject", ""),
        "email_body": email_body or stored_details.get("email_body", ""),
        "relevant_projects": json.dumps(generated.get("relevant_projects", [])),
        "campaign_name": generated.get("campaign_name") or "",
    }

    path = ensure_rejected_csv(user_id)
    with path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REJECTED_COLUMNS)
        writer.writerow(row)

    emailsGenerated.delete_one({"_id": ObjectId(mail_id), "user_id": str(user_id)})
    return {"mail_id": mail_id, "rejected_csv": str(path)}
