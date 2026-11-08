"""Automation (Pro and Premium): emails the contacts a user bought in the marketplace, from their own Gmail.

Pro sends templates only; Premium may use AI writing. Each bought contact is emailed once: its status in
ownedContacts records the outcome, so Stop then Start continues with the next contact, even across restarts.
"""
import threading
import time
from typing import Any

from bson import ObjectId

from database.admin import deactivate_lead, set_automation
from database.fxns import DATABASE_CAMPAIGN_ID, _now, emailsGenerated, get_user_by_id, is_bad_address, is_paid, is_premium, project_catalog, users
from database.marketplace import mark_owned, next_owned_contact, ownedContacts
from Graph import OutreachInput, run_outreach
from utils.job_templates import brief_for_profile
from utils.legal import UNSIGNED_MESSAGE, legal_status
from utils.pacing import random_send_gap
from utils.plans import DAILY_CAP_REASON, quota_status
from utils.send_guard import SKIP_STATUSES

CAMPAIGN_ID = DATABASE_CAMPAIGN_ID
CAMPAIGN_NAME = "Marketplace contacts"

# Each user's automation is a daemon thread, so its waits and database calls never block the web server.
_tasks: dict[str, threading.Thread] = {}
_stop: set[str] = set()


def is_running(user_id: str) -> bool:
    task = _tasks.get(user_id)
    return bool(task and task.is_alive())


def stop(user_id: str) -> bool:
    if not is_running(user_id):
        set_automation(user_id, {"status": "stopped", "next_send_at": None, "current": None})
        return False
    _stop.add(user_id)
    set_automation(user_id, {"status": "stopping"})
    return True


def start(user_id: str) -> None:
    if is_running(user_id):
        # Started again while a stop was still finishing: cancel the stop instead of ignoring the Start.
        _stop.discard(user_id)
        set_automation(user_id, {"status": "running", "message": ""})
        return
    _stop.discard(user_id)
    set_automation(user_id, {
        "status": "running",
        "started_at": _now(),
        "sent_this_run": 0,
        "message": "",
        "next_send_at": None,
    })
    thread = threading.Thread(target=_run, args=(user_id,), name=f"automation-{user_id}", daemon=True)
    _tasks[user_id] = thread
    thread.start()


def preflight(user: dict[str, Any]) -> list[str]:
    """Reasons automation can't start yet, in the order the user should fix them."""
    problems = []
    profile = user.get("profile") or {}
    if not is_paid(user):
        problems.append("Automation is part of Pro and Premium. Upgrade to start it.")
    if not legal_status(user)["signed"]:
        problems.append(UNSIGNED_MESSAGE)
    if not (user.get("gmail_tokens") or {}).get("refresh_token") and not (user.get("gmail_tokens") or {}).get("access_token"):
        problems.append("Connect Gmail so emails can be sent from your account.")
    if not profile.get("full_name"):
        problems.append("Add your name on the Profile page.")
    if user.get("role") == "campaigner":
        problems.append("Recruiter automation is for job seekers. Switch to Job seeker mode on the Profile page to use it.")
    elif not profile.get("resume_url"):
        problems.append("Add your resume link on the Profile page.")
    return problems


def _sleep_unless_stopped(user_id: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and user_id not in _stop:
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _finish(user_id: str, status: str, message: str) -> None:
    set_automation(user_id, {"status": status, "message": message, "current": None, "next_send_at": None, "finished_at": _now()})


def _run(user_id: str) -> None:
    errors_in_a_row: list[str] = []
    try:
        while user_id not in _stop:
            user = get_user_by_id(user_id)
            problems = preflight(user)
            if problems:
                return _finish(user_id, "blocked", problems[0])
            quota = quota_status(user)
            if quota["remaining"] <= 0:
                # Daily safety cap: wait until midnight, then carry on from the next recruiter.
                wait = max(60.0, quota["resets_at"].timestamp() - time.time())
                set_automation(user_id, {"current": None, "next_send_at": time.time() + wait,
                                         "message": f"Paused at today's {quota['limit']} emails. {DAILY_CAP_REASON} Continues after midnight."})
                _sleep_unless_stopped(user_id, wait)
                set_automation(user_id, {"message": ""})
                continue

            lead = next_owned_contact(user_id)
            if not lead:
                return _finish(user_id, "done", "You've emailed every contact you have. Get more in the Marketplace, then press Start.")

            set_automation(user_id, {"current": lead.get("company") or "next contact", "next_send_at": None})
            profile = user.get("profile") or {}
            try:
                state = run_outreach(
                    OutreachInput(
                        user_id=user_id,
                        role="student",
                        campaign_id=CAMPAIGN_ID,
                        campaign_name=CAMPAIGN_NAME,
                        profile=profile,
                        brief=brief_for_profile(profile, ai_allowed=is_premium(user)),
                        project_catalog=project_catalog(user_id),
                        company_name=lead.get("company", ""),
                        recipient_name=lead.get("name", ""),
                        recipient_email=lead["email"],
                        email_from=user["email"],
                        details=" ".join(filter(None, [lead.get("role"), lead.get("details")])),
                        variables={
                            "first_name": (lead.get("name") or "").split(" ")[0],
                            "name": lead.get("name", ""),
                            "company": lead.get("company", ""),
                            "role": lead.get("role", ""),
                        },
                    ),
                    True,
                )
            except Exception as exc:
                # One unusable contact (or a writer hiccup) shouldn't end the run or leave its address in a draft.
                emailsGenerated.delete_many({"user_id": user_id, "campaign_id": CAMPAIGN_ID, "recipient_email": lead["email"]})
                mark_owned(lead["_id"], "failed", str(exc)[:200])
                errors_in_a_row.append(lead["_id"])
                if len(errors_in_a_row) >= 3:
                    # Probably not the contacts: give them back so they're retried after the problem is fixed.
                    ownedContacts.update_many({"_id": {"$in": errors_in_a_row}}, {"$set": {"status": "available", "reason": ""}})
                    return _finish(user_id, "error", f"Automation stopped after repeated errors: {str(exc)[:160]}")
                continue
            errors_in_a_row.clear()

            if state.get("final_email_status"):
                mark_owned(lead["_id"], "sent", email_id=state.get("db_id"))
                set_automation(user_id, {"last_sent_at": _now()})
                users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"automation.sent_this_run": 1}})
            else:
                # Unsent drafts would reveal database contacts, so they never reach the user's review queue.
                if state.get("db_id"):
                    emailsGenerated.delete_one({"_id": ObjectId(state["db_id"])})
                outcome = state.get("outreach_status") or "FAILED"
                reason = ((state.get("email_response") or {}).get("reason")) or ""
                if outcome == "REGENERATE":
                    reasons = ", ".join((state.get("deliverability_risk") or {}).get("reasons", []))
                    return _finish(user_id, "blocked", f"Your template was held by the spam guard ({reasons}). Adjust it on the Templates page, then press Start.")
                if outcome == "QUOTA_REACHED":
                    continue  # the next loop pass waits for the daily cap to reset
                if outcome in SKIP_STATUSES:
                    # Already emailed, unsubscribed or undeliverable: skipped, and nothing is sent.
                    mark_owned(lead["_id"], "skipped", state.get("skip_reason", ""))
                    if outcome in ("BAD_ADDRESS", "BAD_DOMAIN") and lead.get("lead_id"):
                        deactivate_lead(lead["lead_id"], state.get("skip_reason", "Undeliverable"))
                    continue
                if "Gmail" in reason or "authorization" in reason.lower():
                    return _finish(user_id, "blocked", f"{reason}. Reconnect Gmail, then press Start.")
                # A bad address shouldn't stall the run: mark it and move on.
                mark_owned(lead["_id"], "failed", reason or outcome)
                if is_bad_address(lead["email"]) and lead.get("lead_id"):
                    deactivate_lead(lead["lead_id"], "Gmail rejected the recipient")

            gap = random_send_gap()
            set_automation(user_id, {"current": None, "next_send_at": time.time() + gap})
            _sleep_unless_stopped(user_id, gap)

        _finish(user_id, "stopped", "Stopped. Press Start to continue from the next contact.")
    except Exception as exc:  # keep the state truthful if something unexpected breaks
        _finish(user_id, "error", f"Automation stopped: {str(exc)[:200]}")
    finally:
        _stop.discard(user_id)
        _tasks.pop(user_id, None)

