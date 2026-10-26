import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from database.fxns import (
    create_campaign,
    get_campaign,
    get_campaign_doc,
    get_current_user,
    get_overview_stats,
    list_campaigns,
    project_catalog,
    ready_draft_ids,
    update_campaign,
)
from utils import campaign_runner
from utils.contacts import normalize_contacts, read_contacts_frame
from utils.legal import require_signed
from utils.plans import limit_message, quota_status, require_ai
from utils.spam_guard import analyze_email_risk
from utils.templating import merge_fields, render_template, with_compliance_footer

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

MODES = ("auto", "review")
WRITING_MODES = ("ai", "template")


class ModeIn(BaseModel):
    mode: str


def _parse_brief(brief_json: str | None) -> dict:
    if not brief_json:
        return {}
    try:
        brief = json.loads(brief_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign brief is not valid JSON") from exc
    if not isinstance(brief, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign brief must be an object")
    return {key: value for key, value in brief.items() if isinstance(value, (str, bool))}


def _role(user: dict) -> str:
    return user.get("role") or "student"


def _campaign_type(user: dict) -> str:
    return "campaign" if _role(user) == "campaigner" else "outreach"


def _template_sample(user: dict, brief: dict, contact: dict | None) -> dict | None:
    if brief.get("writing_mode") != "template" or not contact:
        return None
    variables = contact.get("variables", {})
    subject = render_template(brief.get("subject_template", ""), variables)
    body = render_template(brief.get("body_template", ""), variables, html=True)
    if _role(user) == "campaigner":
        body = with_compliance_footer(body, user.get("profile") or {})
    risk = analyze_email_risk(subject, body, recipient_email=contact["recipient_email"], campaign_type=_campaign_type(user))
    return {"recipient_email": contact["recipient_email"], "email_subject": subject, "email_body": body, "risk": risk.model_dump()}


def _load_contacts(user: dict, file: UploadFile | None, contacts_text: str | None) -> dict:
    frame = read_contacts_frame(file, contacts_text)
    return normalize_contacts(frame, set(user.get("suppressed_emails") or []))


@router.get("/stats")
async def stats(current_user=Depends(get_current_user)):
    return get_overview_stats(str(current_user["_id"]))


@router.get("")
async def campaigns_index(current_user=Depends(get_current_user)):
    return {"campaigns": list_campaigns(str(current_user["_id"]))}


@router.post("/preview")
async def preview_campaign(
    file: UploadFile | None = File(None),
    contacts_text: str | None = Form(None),
    brief_json: str | None = Form(None),
    current_user=Depends(get_current_user),
):
    brief = _parse_brief(brief_json)
    parsed = _load_contacts(current_user, file, contacts_text)
    contacts = parsed["contacts"]
    template_fields = merge_fields(f"{brief.get('subject_template', '')} {brief.get('body_template', '')}")
    available = set()
    for contact in contacts:
        available.update(contact["variables"])
    return {
        "total": len(contacts),
        "contacts": contacts[:8],
        "skipped": parsed["skipped"],
        "columns": parsed["columns"],
        "merge_fields": template_fields,
        "missing_fields": [field for field in template_fields if field not in available],
        "sample": _template_sample(current_user, brief, contacts[0] if contacts else None),
        "estimated_seconds": _estimate_seconds(len(contacts), brief),
    }


def _estimate_seconds(total: int, brief: dict, mode: str | None = None) -> int:
    if total <= 1:
        return 0
    per_contact = 0
    if brief.get("writing_mode") != "template":
        per_contact = campaign_runner.process_start_delay_seconds()
    if (mode or brief.get("mode")) == "auto":
        per_contact = max(per_contact, campaign_runner.email_delay_seconds())
    return per_contact * (total - 1)


@router.post("", status_code=status.HTTP_201_CREATED)
async def launch_campaign(
    name: str = Form(...),
    email_from: str = Form(...),
    mode: str = Form("review"),
    file: UploadFile | None = File(None),
    contacts_text: str | None = Form(None),
    brief_json: str | None = Form(None),
    current_user=Depends(get_current_user),
):
    require_signed(current_user)
    if mode not in MODES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mode must be 'auto' or 'review'")
    brief = _parse_brief(brief_json)
    writing_mode = brief.get("writing_mode") or "template"
    if writing_mode not in WRITING_MODES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown writing mode")
    if writing_mode == "template" and not (brief.get("subject_template") and brief.get("body_template")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template campaigns need a subject and a body")
    if writing_mode == "ai":
        require_ai(current_user)
    brief["writing_mode"] = writing_mode

    parsed = _load_contacts(current_user, file, contacts_text)
    if not parsed["contacts"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid contacts to send to")
    if mode == "auto" and quota_status(current_user)["remaining"] <= 0:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=limit_message(quota_status(current_user)))

    user_id = str(current_user["_id"])
    catalog = project_catalog(user_id) if _role(current_user) == "student" else {}
    campaign = create_campaign(
        user_id,
        {
            "name": name.strip() or "Untitled campaign",
            "mode": mode,
            "role": _role(current_user),
            "campaign_type": _campaign_type(current_user),
            "writing_mode": writing_mode,
            "brief": brief,
            "email_from": email_from.strip(),
            "total": len(parsed["contacts"]),
            "skipped": parsed["skipped"],
            "contacts": parsed["contacts"],
            "estimated_seconds": _estimate_seconds(len(parsed["contacts"]), brief, mode),
        },
    )
    campaign_runner.start(campaign, current_user, catalog)
    return {key: value for key, value in campaign.items() if key != "contacts"}


@router.get("/{campaign_id}")
async def campaign_detail(campaign_id: str, current_user=Depends(get_current_user)):
    campaign = get_campaign(campaign_id, str(current_user["_id"]))
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    campaign.pop("contacts", None)
    return campaign


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, current_user=Depends(get_current_user)):
    if not get_campaign_doc(campaign_id, str(current_user["_id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return {"cancelling": campaign_runner.cancel(campaign_id)}


@router.post("/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    doc = get_campaign_doc(campaign_id, user_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    if campaign_runner.is_running(campaign_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign is already running")
    processed = int(doc.get("processed") or 0)
    if processed >= len(doc.get("contacts", [])):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Every contact has already been processed")
    require_signed(current_user)
    if doc.get("mode") == "auto" and quota_status(current_user)["remaining"] <= 0:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=limit_message(quota_status(current_user)))

    campaign = dict(doc)
    campaign["id"] = str(campaign.pop("_id"))
    catalog = project_catalog(user_id) if campaign.get("role") == "student" else {}
    campaign_runner.start(campaign, current_user, catalog, start_index=processed)
    return {"resumed": True, "from_index": processed}


@router.post("/{campaign_id}/mode")
async def switch_mode(campaign_id: str, payload: ModeIn, current_user=Depends(get_current_user)):
    """Switch a list between review-first and auto-send, even while it's running.

    Auto-send applies to contacts not processed yet and to this list's drafts waiting in Review that passed
    the spam check; review-first turns the remaining contacts into drafts."""
    user_id = str(current_user["_id"])
    doc = get_campaign_doc(campaign_id, user_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    if payload.mode not in MODES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mode must be 'auto' or 'review'")
    if payload.mode == "auto":
        require_signed(current_user)
        quota = quota_status(current_user)
        if quota["remaining"] <= 0:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=limit_message(quota))
    update_campaign(campaign_id, {"mode": payload.mode})

    remaining = max(0, len(doc.get("contacts", [])) - int(doc.get("processed") or 0))
    ready = len(ready_draft_ids(user_id, campaign_id)) if payload.mode == "auto" else 0
    started = False
    # A list that isn't running only needs restarting when auto-send has something to do.
    if payload.mode == "auto" and not campaign_runner.is_running(campaign_id) and (remaining or ready) and doc.get("status") not in ("queued", "cancelled"):
        campaign = dict(doc, mode="auto")
        campaign["id"] = str(campaign.pop("_id"))
        catalog = project_catalog(user_id) if campaign.get("role") == "student" else {}
        campaign_runner.start(campaign, current_user, catalog, start_index=int(doc.get("processed") or 0))
        started = True
    return {"mode": payload.mode, "remaining_contacts": remaining, "ready_drafts": ready, "started": started}
