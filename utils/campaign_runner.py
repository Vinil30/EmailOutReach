import asyncio
import os
import time
from typing import Any

from database.fxns import _now, get_user_by_id, is_premium, update_campaign
from Graph import OutreachInput, run_outreach
from utils.pacing import average_send_gap, random_send_gap

MIN_PROCESS_START_DELAY_SECONDS = 30

_tasks: dict[str, asyncio.Task] = {}
_cancelled: set[str] = set()


def email_delay_seconds() -> float:
    """Average gap used for time estimates; real gaps are random per send."""
    return average_send_gap()


def process_start_delay_seconds() -> int:
    configured_delay = int(os.environ.get("BATCH_PROCESS_START_DELAY_SECONDS", str(MIN_PROCESS_START_DELAY_SECONDS)))
    return max(MIN_PROCESS_START_DELAY_SECONDS, configured_delay)


def is_running(campaign_id: str) -> bool:
    task = _tasks.get(campaign_id)
    return bool(task and not task.done())


def cancel(campaign_id: str) -> bool:
    if not is_running(campaign_id):
        return False
    _cancelled.add(campaign_id)
    return True


def start(campaign: dict[str, Any], user: dict[str, Any], catalog: dict[str, str], start_index: int = 0) -> None:
    campaign_id = campaign["id"]
    _cancelled.discard(campaign_id)
    _tasks[campaign_id] = asyncio.create_task(_run(campaign, user, catalog, start_index))


async def _sleep_unless_cancelled(campaign_id: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and campaign_id not in _cancelled:
        await asyncio.sleep(min(1.0, deadline - time.monotonic()))


async def _run(campaign: dict[str, Any], user: dict[str, Any], catalog: dict[str, str], start_index: int) -> None:
    campaign_id = campaign["id"]
    contacts = campaign.get("contacts", [])
    automate = campaign.get("mode") == "auto"
    uses_ai = campaign.get("writing_mode") != "template"
    update_campaign(campaign_id, {"status": "running", "started_at": _now(), "finished_at": None})

    try:
        for index in range(start_index, len(contacts)):
            if campaign_id in _cancelled:
                break
            if uses_ai and not is_premium(get_user_by_id(str(user["_id"]))):
                update_campaign(
                    campaign_id,
                    {"status": "quota", "finished_at": _now(), "current_contact": None, "next_send_at": None},
                    error={"email": None, "reason": "Premium ended, so AI writing stopped. Resend the rest with a template.", "at": _now()},
                )
                return
            contact = contacts[index]
            started_at = time.monotonic()
            update_campaign(campaign_id, {"current_contact": contact["recipient_email"], "next_send_at": None})
            sent_attempted = False
            try:
                state = await asyncio.to_thread(
                    run_outreach,
                    OutreachInput(
                        user_id=str(user["_id"]),
                        role=campaign.get("role", "student"),
                        campaign_id=campaign_id,
                        campaign_name=campaign.get("name"),
                        profile=user.get("profile") or {},
                        brief=campaign.get("brief") or {},
                        project_catalog=catalog,
                        company_name=contact.get("company_name", ""),
                        recipient_name=contact.get("recipient_name", ""),
                        recipient_email=contact["recipient_email"],
                        email_from=campaign["email_from"],
                        details=contact.get("details", ""),
                        variables=contact.get("variables", {}),
                    ),
                    automate,
                )
                skipped = state.get("outreach_status") in ("DUPLICATE_SUPPRESSED", "SUPPRESSED")
                sent_attempted = automate and not skipped and (state.get("deliverability_risk") or {}).get("action") == "SEND"
                if state.get("quota_blocked"):
                    update_campaign(
                        campaign_id,
                        {"status": "quota", "finished_at": _now(), "current_contact": None, "next_send_at": None},
                        error={"email": contact["recipient_email"], "reason": "Plan limit reached; the rest of this list was not sent.", "at": _now()},
                    )
                    return  # not counted as processed, so Resume retries this contact
                if skipped:
                    update_campaign(campaign_id, inc={"processed": 1}, error={"email": contact["recipient_email"], "reason": state.get("skip_reason", "Skipped"), "at": _now()})
                else:
                    update_campaign(campaign_id, inc={"processed": 1})
            except Exception as exc:
                update_campaign(
                    campaign_id,
                    inc={"processed": 1},
                    error={"email": contact["recipient_email"], "reason": str(exc)[:300], "at": _now()},
                )

            if index < len(contacts) - 1:
                elapsed = time.monotonic() - started_at
                wait = 0.0
                if sent_attempted:
                    wait = random_send_gap()
                if uses_ai:
                    wait = max(wait, process_start_delay_seconds() - elapsed)
                if wait > 0:
                    update_campaign(campaign_id, {"next_send_at": time.time() + wait})
                    await _sleep_unless_cancelled(campaign_id, wait)

        final_status = "cancelled" if campaign_id in _cancelled else "completed"
        update_campaign(
            campaign_id,
            {"status": final_status, "finished_at": _now(), "current_contact": None, "next_send_at": None},
        )
    except Exception as exc:
        update_campaign(
            campaign_id,
            {"status": "failed", "finished_at": _now(), "next_send_at": None},
            error={"email": None, "reason": str(exc)[:300], "at": _now()},
        )
    finally:
        _cancelled.discard(campaign_id)
        _tasks.pop(campaign_id, None)
