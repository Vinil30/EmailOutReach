import re
from io import BytesIO, StringIO

import pandas as pd
from fastapi import HTTPException, UploadFile, status

MAX_CONTACTS = 3000
EMAIL_PATTERN = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$")

# Accept the column names people actually use in exported spreadsheets.
COLUMN_ALIASES = {
    "recipient_email": ("recipient_email", "email", "email_address", "e-mail", "mail"),
    "recipient_name": ("recipient_name", "name", "full_name", "contact_name"),
    "first_name": ("first_name", "firstname", "first"),
    "last_name": ("last_name", "lastname", "last", "surname"),
    "company_name": ("company_name", "company", "organization", "organisation", "org"),
    "details": ("details", "notes", "context", "about"),
}


def read_contacts_frame(file: UploadFile | None, contacts_text: str | None) -> pd.DataFrame:
    if file is not None and file.filename:
        content = file.file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
        filename = file.filename.lower()
        if filename.endswith(".csv"):
            return pd.read_csv(BytesIO(content), dtype=str)
        if filename.endswith((".xlsx", ".xls")):
            return pd.read_excel(BytesIO(content), dtype=str)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a CSV or Excel file")

    text = (contacts_text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add contacts by uploading a file or pasting them")

    first_line = text.splitlines()[0].lower()
    if "@" in first_line:
        # Headerless paste: "email, name, company, details" per line.
        frame = pd.read_csv(StringIO(text), header=None, dtype=str, skipinitialspace=True, on_bad_lines="skip")
        columns = ["recipient_email", "recipient_name", "company_name", "details"]
        frame = frame.iloc[:, : len(columns)]
        frame.columns = columns[: frame.shape[1]]
        return frame
    return pd.read_csv(StringIO(text), dtype=str, skipinitialspace=True)


def normalize_contacts(df: pd.DataFrame, suppressed: set[str] | None = None) -> dict:
    df = df.rename(columns={column: str(column).strip().lower().replace(" ", "_") for column in df.columns})
    resolved = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        match = next((alias for alias in aliases if alias in df.columns), None)
        if match:
            resolved[canonical] = match
    if "recipient_email" not in resolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not find an email column. Name it 'email' or 'recipient_email'.",
        )

    suppressed = {email.lower() for email in (suppressed or set())}
    contacts, skipped, seen = [], [], set()
    for _, row in df.fillna("").iterrows():
        raw = {str(key): str(value).strip() for key, value in row.items()}

        def pick(field: str) -> str:
            return raw.get(resolved[field], "") if field in resolved else ""

        email = pick("recipient_email")
        first, last = pick("first_name"), pick("last_name")
        name = pick("recipient_name") or " ".join(part for part in (first, last) if part)
        if not email:
            continue
        lowered = email.lower()
        if not EMAIL_PATTERN.match(email):
            skipped.append({"email": email, "reason": "invalid email address"})
            continue
        if lowered in seen:
            skipped.append({"email": email, "reason": "duplicate in this list"})
            continue
        if lowered in suppressed:
            skipped.append({"email": email, "reason": "on your suppression list"})
            continue
        seen.add(lowered)

        company = pick("company_name")
        variables = {key: value for key, value in raw.items() if value}
        variables.update(
            {
                "email": email,
                "name": name,
                "first_name": first or (name.split()[0] if name else ""),
                "last_name": last or (" ".join(name.split()[1:]) if name else ""),
                "company": company,
            }
        )
        contacts.append(
            {
                "recipient_email": email,
                "recipient_name": name,
                "company_name": company,
                "details": pick("details"),
                "variables": {key: value for key, value in variables.items() if value},
            }
        )

    if len(contacts) > MAX_CONTACTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A campaign can include up to {MAX_CONTACTS} contacts; this list has {len(contacts)}.",
        )
    return {"contacts": contacts, "skipped": skipped, "columns": sorted(df.columns.tolist())}
