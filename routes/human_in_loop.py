from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database.fxns import (
    ensure_rejected_csv,
    get_current_user,
    get_waiting_emails,
    reject_generated_email,
    update_generated_email_details,
)
from Graph import EmailDetails
from utils.draft_sender import load_draft, risk_for, send_draft
from utils.plans import require_ai

router = APIRouter(prefix="/human", tags=["human"])


class MailEditIn(BaseModel):
    mail_id: str
    email_subject: str | None = None
    email_body: str | None = None


# Kept as distinct names so the request shapes stay self-documenting in /docs.
SendMailIn = MailEditIn
RejectMailIn = MailEditIn


def _load_draft(payload: MailEditIn, user_id: str) -> tuple[dict, EmailDetails, str]:
    return load_draft(payload.mail_id, user_id, payload.email_subject, payload.email_body)


@router.get("/waiting-emails")
async def get_human_mails(campaign_id: str | None = None, current_user=Depends(get_current_user)):
    return {"emails": get_waiting_emails(str(current_user["_id"]), campaign_id)}


@router.post("/save-draft")
async def save_draft(payload: MailEditIn, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    waiting_email, email_details, campaign_type = _load_draft(payload, user_id)
    risk = risk_for(waiting_email, email_details, campaign_type)
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

    require_ai(current_user)
    user_id = str(current_user["_id"])
    waiting_email, email_details, campaign_type = _load_draft(payload, user_id)
    before = risk_for(waiting_email, email_details, campaign_type)
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
    risk = risk_for(waiting_email, rewritten, campaign_type)
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
    return await run_in_threadpool(send_draft, payload.mail_id, str(current_user["_id"]), payload.email_subject, payload.email_body)


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
