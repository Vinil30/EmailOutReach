import asyncio
import os
import time
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
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
from Graph import EmailDetails, OutreachInput, run_outreach
from utils.EmailerAgent import EmailerAgent
from utils.GmailAuth import get_valid_gmail_tokens
from utils.spam_guard import analyze_email_risk

router = APIRouter(prefix="/human", tags=["human"])

REQUIRED_COLUMNS = {"company_name", "recipient_name", "recipient_email"}
MIN_PROCESS_START_DELAY_SECONDS = 30


class SendMailIn(BaseModel):
    mail_id: str
    email_subject: str | None = None
    email_body: str | None = None


class RejectMailIn(BaseModel):
    mail_id: str
    email_subject: str | None = None
    email_body: str | None = None


def _process_start_delay_seconds() -> int:
    configured_delay = int(os.environ.get("BATCH_PROCESS_START_DELAY_SECONDS", str(MIN_PROCESS_START_DELAY_SECONDS)))
    return max(MIN_PROCESS_START_DELAY_SECONDS, configured_delay)


def _read_input_file(file: UploadFile) -> pd.DataFrame:
    filename = (file.filename or "").lower()
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    if filename.endswith(".csv"):
        return pd.read_csv(BytesIO(content))
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(content))

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a CSV or Excel file")


def _normalize_rows(df: pd.DataFrame) -> list[dict]:
    df = df.rename(columns={column: str(column).strip().lower() for column in df.columns})
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required columns: {', '.join(sorted(missing))}",
        )

    rows = []
    for _, row in df.fillna("").iterrows():
        rows.append(
            {
                "company_name": str(row["company_name"]).strip(),
                "recipient_name": str(row["recipient_name"]).strip(),
                "recipient_email": str(row["recipient_email"]).strip(),
                "details": str(row.get("details", "")).strip(),
            }
        )
    return [row for row in rows if row["company_name"] and row["recipient_email"]]


@router.post("/generate")
async def generate_for_review(
    file: UploadFile = File(...),
    email_from: str = Form(...),
    current_user=Depends(get_current_user),
):
    rows = _normalize_rows(_read_input_file(file))
    results = []
    process_start_delay_seconds = _process_start_delay_seconds()

    for index, row in enumerate(rows):
        started_at = time.monotonic()
        state = run_outreach(
            OutreachInput(
                user_id=str(current_user["_id"]),
                company_name=row["company_name"],
                recipient_name=row["recipient_name"],
                recipient_email=row["recipient_email"],
                email_from=email_from,
                details=row["details"],
            ),
            automate=False,
        )
        results.append(
            {
                "db_id": state.get("db_id"),
                "company_name": state.get("company_name"),
                "recipient_email": state.get("recipient_email"),
                "email_status": state.get("final_email_status", False),
                "outreach_status": state.get("outreach_status"),
                "deliverability_risk": state.get("deliverability_risk"),
            }
        )
        if index < len(rows) - 1:
            elapsed_seconds = time.monotonic() - started_at
            await asyncio.sleep(max(0, process_start_delay_seconds - elapsed_seconds))

    return {"processed": len(results), "process_start_delay_seconds": process_start_delay_seconds, "results": results}


@router.get("/waiting-emails")
async def get_human_mails(current_user=Depends(get_current_user)):
    return {"emails": get_waiting_emails(str(current_user["_id"]))}


@router.post("/send-mail")
async def send_mail(payload: SendMailIn, current_user=Depends(get_current_user)):
    waiting_email = get_waiting_email(payload.mail_id, str(current_user["_id"]))
    if not waiting_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiting email not found")

    stored_details = waiting_email["written_email_details"]
    email_details = EmailDetails(
        email_subject=payload.email_subject or stored_details["email_subject"],
        email_body=payload.email_body or stored_details["email_body"],
    )
    risk = analyze_email_risk(
        email_details.email_subject,
        email_details.email_body,
        waiting_email["email_from"],
        waiting_email["recipient_email"],
    )
    updated_email = update_generated_email_details(
        payload.mail_id,
        str(current_user["_id"]),
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
        gmail_tokens = get_valid_gmail_tokens(str(current_user["_id"]))
    except HTTPException as exc:
        send_result = {
            "status": "FAILED_PERMANENT",
            "attempt": 0,
            "reason": exc.detail,
            "history": [{"attempt": 0, "status": "FAILED", "reason": exc.detail, "transient": False}],
        }
        failed_email = record_generated_send_result(
            payload.mail_id,
            str(current_user["_id"]),
            send_result,
            risk.model_dump(),
        )
        return {"email": failed_email, "failed": True}

    emailer = EmailerAgent(
        email_details=email_details,
        recipient_email=waiting_email["recipient_email"],
        email_from=waiting_email["email_from"],
        gmail_tokens=gmail_tokens,
    )
    send_result = emailer.send_with_retries()
    sent_email = record_generated_send_result(
        payload.mail_id,
        str(current_user["_id"]),
        send_result,
        risk.model_dump(),
    )
    return {"email": sent_email, "failed": send_result.get("status") != "SENT"}


@router.post("/reject-mail")
async def reject_mail(payload: RejectMailIn, current_user=Depends(get_current_user)):
    result = reject_generated_email(
        payload.mail_id,
        str(current_user["_id"]),
        payload.email_subject,
        payload.email_body,
    )
    return result


@router.get("/rejected-csv")
async def rejected_csv(current_user=Depends(get_current_user)):
    path = ensure_rejected_csv(str(current_user["_id"]))
    return FileResponse(path, media_type="text/csv", filename="rejected_by_human.csv")
