"""Database automation (Pro and Premium): sends a user's chosen template to the shared lead database from their own Gmail.

Each purchase allows a number of new recruiters (see utils.plans.database_allowance); Pro sends templates only,
Premium may use AI writing.

Progress lives in the database (one leadSends row per user and lead), so Stop then Start
continues with the next lead the user hasn't emailed, even across server restarts.
"""
import asyncio
import time
from typing import Any

from bson import ObjectId

from database.admin import next_lead_for, record_lead_send, set_automation
from database.fxns import _now, emailsGenerated, get_user_by_id, is_paid, is_premium, project_catalog, users
from Graph import OutreachInput, run_outreach
from utils.job_templates import brief_for_profile
from utils.legal import UNSIGNED_MESSAGE, legal_status
from utils.pacing import random_send_gap
from utils.plans import DAILY_CAP_REASON, quota_status

CAMPAIGN_ID = "premium-db"
CAMPAIGN_NAME = "Recruiter database"

_tasks: dict[str, asyncio.Task] = {}
_stop: set[str] = set()


def is_running(user_id: str) -> bool:
    task = _tasks.get(user_id)
    return bool(task and not task.done())


def stop(user_id: str) -> bool:
    if not is_running(user_id):
        set_automation(user_id, {"status": "stopped", "next_send_at": None, "current": None})
        return False
    _stop.add(user_id)
    set_automation(user_id, {"status": "stopping"})
    return True


def start(user_id: str) -> None:
    if is_running(user_id):
        return
    _stop.discard(user_id)
    set_automation(user_id, {
        "status": "running",
        "started_at": _now(),
        "sent_this_run": 0,
        "message": "",
        "next_send_at": None,
    })
    _tasks[user_id] = asyncio.create_task(_run(user_id))


def allowance_message(quota: dict[str, Any]) -> str:
    database = quota["database"]
    upgrade = " or upgrade to Premium" if quota["plan"] == "pro" else ""
    return (f"You've emailed all {database['limit']} recruiters included with {quota['plan_name']} this time. "
            f"Renew{upgrade} to get a new batch of recruiters you haven't emailed yet.")


def preflight(user: dict[str, Any]) -> list[str]:
    """Reasons automation can't start yet, in the order the user should fix them."""
    problems = []
    profile = user.get("profile") or {}
    if not is_paid(user):
        problems.append("Upgrade to Pro or Premium to use our recruiter database.")
    if not legal_status(user)["signed"]:
        problems.append(UNSIGNED_MESSAGE)
    if not (user.get("gmail_tokens") or {}).get("refresh_token") and not (user.get("gmail_tokens") or {}).get("access_token"):
        problems.append("Connect Gmail so emails can be sent from your account.")
    if not profile.get("full_name"):
        problems.append("Add your name on the Profile page.")
    if not profile.get("resume_url"):
        problems.append("Add your resume link on the Profile page.")
    return problems


async def _sleep_unless_stopped(user_id: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and user_id not in _stop:
        await asyncio.sleep(min(1.0, deadline - time.monotonic()))


def _finish(user_id: str, status: str, message: str) -> None:
    set_automation(user_id, {"status": status, "message": message, "current": None, "next_send_at": None, "finished_at": _now()})


async def _run(user_id: str) -> None:
    try:
        while user_id not in _stop:
            user = get_user_by_id(user_id)
            problems = preflight(user)
            if problems:
                return _finish(user_id, "blocked", problems[0])
            quota = quota_status(user)
            if quota["database"]["remaining"] <= 0:
                return _finish(user_id, "allowance", allowance_message(quota))
            if quota["remaining"] <= 0:
                # Daily safety cap: wait until midnight, then carry on from the next recruiter.
                wait = max(60.0, quota["resets_at"].timestamp() - time.time())
                set_automation(user_id, {"current": None, "next_send_at": time.time() + wait,
                                         "message": f"Paused at today's {quota['limit']} emails. {DAILY_CAP_REASON} Continues after midnight."})
                await _sleep_unless_stopped(user_id, wait)
                set_automation(user_id, {"message": ""})
                continue

            lead = next_lead_for(user_id)
            if not lead:
                return _finish(user_id, "done", "You've reached every contact in the database. New contacts are added regularly.")

            set_automation(user_id, {"current": lead.get("company") or "next contact", "next_send_at": None})
            profile = user.get("profile") or {}
            state = await asyncio.to_thread(
                run_outreach,
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

            if state.get("final_email_status"):
                record_lead_send(user_id, lead, "sent", state.get("db_id"))
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
                if "Gmail" in reason or "authorization" in reason.lower():
                    return _finish(user_id, "blocked", f"{reason}. Reconnect Gmail, then press Start.")
                # A bad address shouldn't stall the run: mark it and move on.
                record_lead_send(user_id, lead, "failed", reason=reason or outcome)

            gap = random_send_gap()
            set_automation(user_id, {"current": None, "next_send_at": time.time() + gap})
            await _sleep_unless_stopped(user_id, gap)

        _finish(user_id, "stopped", "Stopped. Press Start to continue from the next company.")
    except Exception as exc:  # keep the state truthful if something unexpected breaks
        _finish(user_id, "error", f"Automation stopped: {str(exc)[:200]}")
    finally:
        _stop.discard(user_id)
        _tasks.pop(user_id, None)

