from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database.fxns import (
    ensure_rejected_csv,
    get_current_user,
    get_waiting_email,
    get_waiting_emails,
    record_generated_send_result,
    reject_generated_email,
    update_generated_email_details,
)
from Graph import EmailDetails
from utils.EmailerAgent import EmailerAgent
from utils.GmailAuth import get_valid_gmail_tokens
from utils.plans import QuotaExceeded, ensure_can_send
from utils.spam_guard import analyze_email_risk

router = APIRouter(prefix="/human", tags=["human"])


class MailEditIn(BaseModel):
    mail_id: str
    email_subject: str | None = None
    email_body: str | None = None


# Kept as distinct names so the request shapes stay self-documenting in /docs.
SendMailIn = MailEditIn
RejectMailIn = MailEditIn


def _load_draft(payload: MailEditIn, user_id: str) -> tuple[dict, EmailDetails, str]:
    waiting_email = get_waiting_email(payload.mail_id, user_id)
    if not waiting_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")
    stored_details = waiting_email["written_email_details"]
    email_details = EmailDetails(
        email_subject=payload.email_subject or stored_details["email_subject"],
        email_body=payload.email_body or stored_details["email_body"],
    )
    return waiting_email, email_details, waiting_email.get("campaign_type") or "outreach"


def _risk_for(waiting_email: dict, email_details: EmailDetails, campaign_type: str):
    return analyze_email_risk(
        email_details.email_subject,
        email_details.email_body,
        waiting_email["email_from"],
        waiting_email["recipient_email"],
        campaign_type=campaign_type,
    )


@router.get("/waiting-emails")
async def get_human_mails(campaign_id: str | None = None, current_user=Depends(get_current_user)):
    return {"emails": get_waiting_emails(str(current_user["_id"]), campaign_id)}


@router.post("/save-draft")
async def save_draft(payload: MailEditIn, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    waiting_email, email_details, campaign_type = _load_draft(payload, user_id)
    risk = _risk_for(waiting_email, email_details, campaign_type)
    email = update_generated_email_details(
        payload.mail_id,
        user_id,
        email_details.email_subject,
        email_details.email_body,
        risk.model_dump(),
        outreach_status=risk.action,
    )
    return {"email": email, "deliverability_risk": risk.model_dump()}


@router.post("/rewrite")
async def rewrite_draft(payload: MailEditIn, current_user=Depends(get_current_user)):
    """Ask the LLM to fix exactly what the spam guard flagged, then re-score."""
    from utils.EmailWriter import EmailWriter
    from utils.templating import with_compliance_footer

    user_id = str(current_user["_id"])
    waiting_email, email_details, campaign_type = _load_draft(payload, user_id)
    before = _risk_for(waiting_email, email_details, campaign_type)
    try:
        rewritten = await run_in_threadpool(
            EmailWriter().RewriteForDeliverability,
            email_details.email_subject,
            email_details.email_body,
            before.reasons or ["general polish for deliverability"],
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI rewrite failed: {exc}") from exc

    body = rewritten.email_body
    if campaign_type == "campaign":
        body = with_compliance_footer(body, current_user.get("profile") or {})
    rewritten = EmailDetails(email_subject=rewritten.email_subject, email_body=body)
    risk = _risk_for(waiting_email, rewritten, campaign_type)
    email = update_generated_email_details(
        payload.mail_id,
        user_id,
        rewritten.email_subject,
        rewritten.email_body,
        risk.model_dump(),
        outreach_status=risk.action,
    )
    return {"email": email, "previous_score": before.score, "deliverability_risk": risk.model_dump()}


@router.post("/send-mail")
async def send_mail(payload: SendMailIn, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    waiting_email, email_details, campaign_type = _load_draft(payload, user_id)
    if waiting_email["recipient_email"].lower() in set(current_user.get("suppressed_emails") or []):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This recipient is on your suppression list")

    risk = _risk_for(waiting_email, email_details, campaign_type)
    updated_email = update_generated_email_details(
        payload.mail_id,
        user_id,
        email_details.email_subject,
        email_details.email_body,
        risk.model_dump(),
    )
    if risk.action != "SEND":
        return {
            "email": updated_email,
            "blocked": True,
            "deliverability_risk": risk.model_dump(),
        }
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
        failed_email = record_generated_send_result(payload.mail_id, user_id, send_result, risk.model_dump())
        return {"email": failed_email, "failed": True}

    emailer = EmailerAgent(
        email_details=email_details,
        recipient_email=waiting_email["recipient_email"],
        email_from=waiting_email["email_from"],
        gmail_tokens=gmail_tokens,
    )
    send_result = await run_in_threadpool(emailer.send_with_retries)
    sent_email = record_generated_send_result(payload.mail_id, user_id, send_result, risk.model_dump())
    return {"email": sent_email, "failed": send_result.get("status") != "SENT"}


@router.post("/reject-mail")
async def reject_mail(payload: RejectMailIn, current_user=Depends(get_current_user)):
    return reject_generated_email(
        payload.mail_id,
        str(current_user["_id"]),
        payload.email_subject,
        payload.email_body,
    )


@router.get("/rejected-csv")
async def rejected_csv(current_user=Depends(get_current_user)):
    path = ensure_rejected_csv(str(current_user["_id"]))
    return FileResponse(path, media_type="text/csv", filename="rejected_by_human.csv")
