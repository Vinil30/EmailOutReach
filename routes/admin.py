from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, Field

from database.admin import (
    add_lead,
    admin_stats,
    delete_lead,
    grant_premium,
    import_leads,
    list_leads,
    list_users_overview,
    recent_grants,
    revoke_premium,
    update_lead,
)
from database.fxns import get_current_user, is_admin
from utils.contacts import EMAIL_PATTERN, read_contacts_frame
from utils.plans import PREMIUM_DAYS

router = APIRouter(prefix="/api/admin", tags=["admin"])

LEAD_ALIASES = {
    "email": ("email", "recipient_email", "email_address", "e-mail", "mail"),
    "name": ("name", "recipient_name", "full_name", "contact_name"),
    "company": ("company", "company_name", "organization", "organisation", "org"),
    "role": ("role", "title", "job_title", "designation", "position"),
    "details": ("details", "notes", "context", "about"),
}


async def require_admin(current_user=Depends(get_current_user)):
    if not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return current_user


class GrantIn(BaseModel):
    email: EmailStr
    days: int = Field(default=PREMIUM_DAYS, ge=1, le=366)
    note: str = ""


class RevokeIn(BaseModel):
    email: EmailStr


class LeadIn(BaseModel):
    email: EmailStr
    name: str = ""
    company: str = ""
    role: str = ""
    details: str = ""


class LeadPatch(BaseModel):
    name: str | None = None
    company: str | None = None
    role: str | None = None
    details: str | None = None
    active: bool | None = None


@router.get("/stats")
async def stats(admin=Depends(require_admin)):
    return admin_stats()


@router.get("/users")
async def users_overview(q: str = "", admin=Depends(require_admin)):
    return {"users": list_users_overview(q), "grants": recent_grants()}


@router.post("/premium")
async def grant(payload: GrantIn, admin=Depends(require_admin)):
    return grant_premium(payload.email, payload.days, admin["email"], payload.note)


@router.post("/premium/revoke")
async def revoke(payload: RevokeIn, admin=Depends(require_admin)):
    revoke_premium(payload.email, admin["email"])
    return {"revoked": payload.email}


@router.get("/leads")
async def leads_index(q: str = "", skip: int = 0, limit: int = 50, admin=Depends(require_admin)):
    return list_leads(q, max(0, skip), min(200, max(1, limit)))


@router.post("/leads", status_code=status.HTTP_201_CREATED)
async def leads_add(payload: LeadIn, admin=Depends(require_admin)):
    return add_lead(payload.model_dump())


@router.post("/leads/import")
async def leads_import(
    file: UploadFile | None = File(None),
    contacts_text: str | None = Form(None),
    admin=Depends(require_admin),
):
    frame = read_contacts_frame(file, contacts_text)
    frame = frame.rename(columns={column: str(column).strip().lower().replace(" ", "_") for column in frame.columns})
    resolved = {field: next((alias for alias in aliases if alias in frame.columns), None) for field, aliases in LEAD_ALIASES.items()}
    if not resolved["email"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not find an email column")
    rows, invalid = [], 0
    for _, row in frame.fillna("").iterrows():
        lead = {field: str(row[column]).strip() if column else "" for field, column in resolved.items()}
        if EMAIL_PATTERN.match(lead["email"]):
            rows.append(lead)
        elif lead["email"]:
            invalid += 1
    result = import_leads(rows)
    result["invalid"] = invalid
    return result


@router.patch("/leads/{lead_id}")
async def leads_patch(lead_id: str, payload: LeadPatch, admin=Depends(require_admin)):
    return update_lead(lead_id, {key: value for key, value in payload.model_dump().items() if value is not None})


@router.delete("/leads/{lead_id}")
async def leads_delete(lead_id: str, admin=Depends(require_admin)):
    delete_lead(lead_id)
    return {"deleted": lead_id}
