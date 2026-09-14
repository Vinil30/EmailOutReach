import asyncio
import os
import time
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from database.fxns import get_current_user, get_sent_emails
from Graph import OutreachInput, run_outreach

router = APIRouter(prefix="/automated", tags=["automated"])

REQUIRED_COLUMNS = {"company_name", "recipient_name", "recipient_email"}
MIN_EMAIL_DELAY_SECONDS = 60
MIN_PROCESS_START_DELAY_SECONDS = 30


def _email_delay_seconds() -> int:
    configured_delay = int(os.environ.get("AUTOMATED_EMAIL_DELAY_SECONDS", str(MIN_EMAIL_DELAY_SECONDS)))
    return max(MIN_EMAIL_DELAY_SECONDS, configured_delay)


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

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Upload a CSV or Excel file",
    )


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


@router.post("/run")
async def run_automated_outreach(
    file: UploadFile = File(...),
    email_from: str = Form(...),
    current_user=Depends(get_current_user),
):
    rows = _normalize_rows(_read_input_file(file))
    results = []

    email_delay_seconds = _email_delay_seconds()
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
            automate=True,
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
            remaining_start_delay = max(0, process_start_delay_seconds - elapsed_seconds)
            await asyncio.sleep(max(email_delay_seconds, remaining_start_delay))

    return {
        "processed": len(results),
        "delay_seconds": email_delay_seconds,
        "process_start_delay_seconds": process_start_delay_seconds,
        "results": results,
    }


@router.get("/sent-emails")
async def sent_emails(current_user=Depends(get_current_user)):
    return {"emails": get_sent_emails(str(current_user["_id"]))}
