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
]


def ensure_indexes() -> None:
    try:
        users.create_index("email", unique=True)
        emailsSent.create_index([("user_id", 1), ("created_at", -1)])
        emailsSent.create_index("send_fingerprint", unique=True, sparse=True)
        emailsGenerated.create_index([("user_id", 1), ("email_status", 1), ("created_at", -1)])
        emailsGenerated.create_index([("user_id", 1), ("outreach_status", 1), ("updated_at", -1)])
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


def create_user(email: str, password: str, name: str | None = None) -> dict[str, Any]:
    normalized_email = email.lower().strip()
    if get_user_by_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

    result = users.insert_one(
        {
            "email": normalized_email,
            "name": name,
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
    return serialized


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
):
    data = {
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


def get_waiting_emails(user_id: str) -> list[dict[str, Any]]:
    docs = emailsGenerated.find({"user_id": str(user_id), "email_status": False}).sort("created_at", -1)
    return _serialize_many(docs)


def get_sent_emails(user_id: str) -> list[dict[str, Any]]:
    docs = emailsSent.find({"user_id": str(user_id), "email_status": True}).sort("created_at", -1)
    return _serialize_many(docs)


def get_waiting_email(mail_id: str, user_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(mail_id):
        return None
    return emailsGenerated.find_one({"_id": ObjectId(mail_id), "user_id": str(user_id), "email_status": False})


def mark_generated_email_sent(mail_id: str, user_id: str, email_response: dict[str, Any] | None = None) -> dict[str, Any]:
    generated = get_waiting_email(mail_id, user_id)
    if not generated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")

    generated.pop("_id", None)
    generated["email_status"] = True
    generated["email_response"] = email_response
    generated["updated_at"] = _now()
    sent_result = emailsSent.insert_one(generated)
    emailsGenerated.delete_one({"_id": ObjectId(mail_id), "user_id": str(user_id)})
    sent_doc = emailsSent.find_one({"_id": sent_result.inserted_id})
    return _serialize_doc(sent_doc)


def update_generated_email_details(
    mail_id: str,
    user_id: str,
    email_subject: str,
    email_body: str,
    deliverability_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not ObjectId.is_valid(mail_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")
    updated = emailsGenerated.find_one_and_update(
        {"_id": ObjectId(mail_id), "user_id": str(user_id), "email_status": False},
        {
            "$set": {
                "written_email_details": {"email_subject": email_subject, "email_body": email_body},
                "deliverability_risk": deliverability_risk,
                "outreach_status": "REVIEW_APPROVED",
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
    }

    path = ensure_rejected_csv(user_id)
    with path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REJECTED_COLUMNS)
        writer.writerow(row)

    emailsGenerated.delete_one({"_id": ObjectId(mail_id), "user_id": str(user_id)})
    return {"mail_id": mail_id, "rejected_csv": str(path)}
