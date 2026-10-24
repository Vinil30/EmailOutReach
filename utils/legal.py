"""Legal documents each account must sign, and the record of who signed which version.

Bumping a document's version makes every account sign it again on their next visit."""
import hashlib
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

DOCUMENTS = {
    "privacy": {"title": "Privacy Policy", "url": "/privacy", "template": "privacy.html", "version": "2026-10-24"},
    "terms-student": {"title": "Terms for Students & Job Seekers", "url": "/terms/students", "template": "terms_students.html", "version": "2026-10-24"},
    "terms-campaigner": {"title": "Terms for Campaigns & Businesses", "url": "/terms/campaigners", "template": "terms_campaigners.html", "version": "2026-10-24"},
}

UNSIGNED_MESSAGE = "Sign the Terms and Privacy Policy before sending. Reload the app to see them."


def required_documents(role: str | None) -> list[str]:
    return ["privacy", "terms-campaigner" if role == "campaigner" else "terms-student"]


def document_hash(doc_id: str) -> str:
    """SHA-256 of the exact page text, so a signature proves which wording was agreed to."""
    with open(f"templates/{DOCUMENTS[doc_id]['template']}", "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def clean_signature(signature: str | None) -> str:
    name = " ".join((signature or "").split())
    if len(name) < 3 or not any(char.isalpha() for char in name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type your full name to sign")
    if len(name) > 120:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature is too long")
    return name


def legal_status(user: dict[str, Any] | None) -> dict[str, Any]:
    signed = (user or {}).get("legal") or {}
    documents = []
    for doc_id in required_documents((user or {}).get("role")):
        meta = DOCUMENTS[doc_id]
        record = signed.get(doc_id) or {}
        documents.append({
            "id": doc_id, "title": meta["title"], "url": meta["url"], "version": meta["version"],
            "signed": record.get("version") == meta["version"],
            "signed_at": record.get("signed_at"), "signature": record.get("signature"),
        })
    return {"signed": all(doc["signed"] for doc in documents), "documents": documents}


def signature_records(role: str | None, signature: str, signed_at: datetime) -> dict[str, dict[str, Any]]:
    return {
        doc_id: {"version": DOCUMENTS[doc_id]["version"], "sha256": document_hash(doc_id), "signature": signature, "signed_at": signed_at}
        for doc_id in required_documents(role)
    }


def require_signed(user: dict[str, Any]) -> None:
    if not legal_status(user)["signed"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UNSIGNED_MESSAGE)
