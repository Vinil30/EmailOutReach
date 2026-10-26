"""Sending a draft from the review queue, shared by the Send button and lists switched to auto-send.

Every send goes through the same checks: the campaign footer is kept, the spam guard re-scores the final text,
and the per-user send guard blocks duplicates, unsubscribed addresses and sends past the plan limit."""
from fastapi import HTTPException, status

from database.fxns import get_user_by_id, get_waiting_email, record_generated_send_result, update_generated_email_details
from Graph import EmailDetails
from utils.EmailerAgent import EmailerAgent
from utils.GmailAuth import get_valid_gmail_tokens
from utils.plans import QuotaExceeded, ensure_can_send
from utils.send_guard import is_suppressed, skip_reason, user_lock
from utils.spam_guard import analyze_email_risk
from utils.templating import with_compliance_footer


def load_draft(mail_id: str, user_id: str, subject: str | None = None, body: str | None = None) -> tuple[dict, EmailDetails, str]:
    waiting_email = get_waiting_email(mail_id, user_id)
    if not waiting_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")
    stored_details = waiting_email["written_email_details"]
    email_details = EmailDetails(
        email_subject=subject or stored_details["email_subject"],
        email_body=body or stored_details["email_body"],
    )
    campaign_type = waiting_email.get("campaign_type") or "outreach"
    if campaign_type == "campaign":
        # Edits in the review queue can't remove the sender identity and opt-out line campaigns must carry.
        owner = get_user_by_id(user_id) or {}
        email_details.email_body = with_compliance_footer(email_details.email_body, owner.get("profile") or {})
    return waiting_email, email_details, campaign_type


def risk_for(waiting_email: dict, email_details: EmailDetails, campaign_type: str):
    return analyze_email_risk(
        email_details.email_subject,
        email_details.email_body,
        waiting_email["email_from"],
        waiting_email["recipient_email"],
        campaign_type=campaign_type,
    )


def send_draft(mail_id: str, user_id: str, subject: str | None = None, body: str | None = None) -> dict:
    """Re-check and send one draft. Raises HTTPException 400/402/404/409 when it can't be sent.

    Returns {"email", "blocked": True, "deliverability_risk"} when the spam guard holds it,
    otherwise {"email", "failed": bool}."""
    waiting_email, email_details, campaign_type = load_draft(mail_id, user_id, subject, body)
    if is_suppressed(get_user_by_id(user_id), waiting_email["recipient_email"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This recipient is on your suppression list")

    risk = risk_for(waiting_email, email_details, campaign_type)
    updated_email = update_generated_email_details(mail_id, user_id, email_details.email_subject, email_details.email_body, risk.model_dump())
    if risk.action != "SEND":
        return {"email": updated_email, "blocked": True, "deliverability_risk": risk.model_dump()}

    # Serialised per user, so a double-click or a parallel list can't send twice or overrun the plan limit.
    with user_lock(user_id):
        skip = skip_reason(user_id, waiting_email["recipient_email"])
        if skip:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=skip[1])
        try:
            ensure_can_send(user_id)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc

        try:
            gmail_tokens = get_valid_gmail_tokens(user_id)
        except HTTPException as exc:
            send_result = {
                "status": "FAILED_PERMANENT",
                "attempt": 0,
                "reason": exc.detail,
                "history": [{"attempt": 0, "status": "FAILED", "reason": exc.detail, "transient": False}],
            }
            return {"email": record_generated_send_result(mail_id, user_id, send_result, risk.model_dump()), "failed": True}

        emailer = EmailerAgent(
            email_details=email_details,
            recipient_email=waiting_email["recipient_email"],
            email_from=waiting_email["email_from"],
            gmail_tokens=gmail_tokens,
        )
        send_result = emailer.send_with_retries()
        sent_email = record_generated_send_result(mail_id, user_id, send_result, risk.model_dump())
        return {"email": sent_email, "failed": send_result.get("status") != "SENT"}
