"""Checks every send goes through, whichever path it comes from (automation, auto lists, the review queue).

- Never email an address the user has already emailed, or one on their suppression list.
- One send at a time per user, so parallel lists and automation can't overrun the daily cap together.
- Automated sends keep at least the minimum gap after the user's previous send, across all runners.
"""
import re
import threading
import time
from typing import Any

from database.fxns import as_utc, emailsSent, get_user_by_id
from utils.pacing import SEND_GAP_MIN_SECONDS

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

ALREADY_EMAILED = "You've already emailed this address, so it was skipped. Mailzen never emails the same person twice."
SUPPRESSED = "This address is on your suppression list, so it was skipped."


def user_lock(user_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(user_id), threading.Lock())


def already_emailed(user_id: str, address: str) -> bool:
    pattern = f"^{re.escape((address or '').strip())}$"
    return bool(emailsSent.find_one({"user_id": str(user_id), "recipient_email": {"$regex": pattern, "$options": "i"}}, {"_id": 1}))


def is_suppressed(user: dict[str, Any] | None, address: str) -> bool:
    return (address or "").strip().lower() in {email.lower() for email in (user or {}).get("suppressed_emails") or []}


def skip_reason(user_id: str, address: str) -> tuple[str, str] | None:
    """(status, message) when this address must not be emailed, else None."""
    if is_suppressed(get_user_by_id(user_id), address):
        return "SUPPRESSED", SUPPRESSED
    if already_emailed(user_id, address):
        return "DUPLICATE_SUPPRESSED", ALREADY_EMAILED
    return None


def wait_for_gap(user_id: str) -> None:
    """Sleep until the minimum gap since this user's last send has passed (call while holding user_lock)."""
    last = emailsSent.find_one({"user_id": str(user_id), "sent_at": {"$exists": True}}, {"sent_at": 1}, sort=[("sent_at", -1)])
    if not last or not last.get("sent_at"):
        return
    elapsed = time.time() - as_utc(last["sent_at"]).timestamp()
    if 0 <= elapsed < SEND_GAP_MIN_SECONDS:
        time.sleep(SEND_GAP_MIN_SECONDS - elapsed)
