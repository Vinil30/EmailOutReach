import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from database.admin import report_bounce
from database.fxns import export_sent_emails, get_current_user, get_sent_email, list_sent_emails

router = APIRouter(prefix="/automated", tags=["automated"])


@router.get("/sent-emails")
def sent_emails(
    campaign_id: str | None = None,
    q: str = "",
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
):
    """One page of the Sent list, newest first, with just the fields a row shows."""
    return list_sent_emails(str(current_user["_id"]), campaign_id, q, skip, limit)


@router.get("/sent-export.csv")
def sent_export(campaign_id: str | None = None, q: str = "", current_user=Depends(get_current_user)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sent_at", "recipient_name", "recipient_email", "company", "subject", "campaign", "spam_score"])
    for email in export_sent_emails(str(current_user["_id"]), campaign_id, q):
        writer.writerow([
            email.get("sent_at") or email.get("updated_at"), email.get("recipient_name", ""), email.get("recipient_email", ""),
            email.get("company_name", ""), (email.get("written_email_details") or {}).get("email_subject", ""),
            email.get("campaign_name", ""), (email.get("deliverability_risk") or {}).get("score", ""),
        ])
    return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="sent_emails.csv"'})


@router.get("/sent-emails/{email_id}")
def sent_email_detail(email_id: str, current_user=Depends(get_current_user)):
    email = get_sent_email(str(current_user["_id"]), email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return email


@router.post("/sent-emails/{email_id}/bounced")
def sent_email_bounced(email_id: str, current_user=Depends(get_current_user)):
    """Gmail's "Address not found" reply only reaches the user's inbox, so they report it here."""
    if not report_bounce(str(current_user["_id"]), email_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return {"bounced": True}
