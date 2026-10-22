from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from database.admin import get_automation, lead_send_counts, lead_send_history, remaining_leads
from database.fxns import get_current_user, is_premium, project_catalog
from utils import premium_runner
from utils.job_templates import MERGE_FIELD_HELP, TEMPLATES, get_template, profile_variables
from utils.legal import require_signed
from utils.plans import quota_status
from utils.spam_guard import analyze_email_risk
from utils.templating import render_template, with_compliance_footer

router = APIRouter(prefix="/api", tags=["automation"])

SAMPLE_CONTACT = {"first_name": "Priya", "name": "Priya Kapoor", "company": "Brightloop", "role": "Engineering Manager"}


class TemplatePreviewIn(BaseModel):
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    contact: dict[str, str] | None = None
    drop_empty_lines: bool = True


def _sample_variables(user: dict, contact: dict | None = None) -> dict:
    profile = user.get("profile") or {}
    return {**profile_variables(profile, project_catalog(str(user["_id"]))), **(contact or SAMPLE_CONTACT)}


def _render_preview(subject: str, body: str, variables: dict, user: dict | None = None, drop: bool = True) -> dict:
    """Render exactly as a send would, including the campaign footer, and score it."""
    subject = render_template(subject, variables, drop_empty_lines=drop)
    body = render_template(body, variables, html=True, drop_empty_lines=drop)
    campaign_type = "outreach"
    if user and user.get("role") == "campaigner":
        body = with_compliance_footer(body, user.get("profile") or {})
        campaign_type = "campaign"
    risk = analyze_email_risk(subject, body, campaign_type=campaign_type).model_dump()
    return {"preview_subject": subject, "preview_body": body, "risk": risk}


@router.get("/plan")
async def plan(current_user=Depends(get_current_user)):
    return quota_status(current_user)


@router.get("/templates")
async def templates(current_user=Depends(get_current_user)):
    """Every template rendered with the user's own profile and a sample contact, plus its spam score."""
    profile = current_user.get("profile") or {}
    variables = _sample_variables(current_user)
    rendered = []
    for template in TEMPLATES:
        item = {key: template.get(key) for key in ("id", "name", "description", "ai", "custom", "premium")}
        source = template
        if template.get("custom"):
            source = {"subject": profile.get("custom_subject") or "", "body": profile.get("custom_body") or ""}
            item.update({"subject_template": source["subject"], "body_template": source["body"]})
        elif not template.get("ai"):
            item.update({"subject_template": template["subject"], "body_template": template["body"]})
        if source.get("subject") or source.get("body"):
            item.update(_render_preview(source.get("subject", ""), source.get("body", ""), variables))
        rendered.append(item)
    ai_allowed = is_premium(current_user)
    selected = get_template(profile.get("template_id"))
    if selected.get("ai") and not ai_allowed:
        selected = get_template(None)
    return {
        "templates": rendered,
        "selected": selected["id"],
        "ai_allowed": ai_allowed,
        "projects": list(project_catalog(str(current_user["_id"]))),
        "featured_project": variables.get("project_name", ""),
        "fields": MERGE_FIELD_HELP,
        "sample_contact": SAMPLE_CONTACT,
    }


@router.post("/templates/preview")
async def template_preview(payload: TemplatePreviewIn, current_user=Depends(get_current_user)):
    variables = _sample_variables(current_user, payload.contact)
    return _render_preview(payload.subject, payload.body, variables, current_user, payload.drop_empty_lines)


@router.get("/automation")
async def automation_status(current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    state = get_automation(current_user)
    if state.get("status") in ("running", "stopping") and not premium_runner.is_running(user_id):
        state["status"] = "stopped"
    quota = quota_status(current_user)
    template = get_template((current_user.get("profile") or {}).get("template_id"))
    premium = quota["plan"] == "premium"
    # General users only see the upgrade card, so skip the database-usage queries for them.
    return {
        "state": state,
        "quota": quota,
        "problems": premium_runner.preflight(current_user),
        "remaining_contacts": remaining_leads(user_id) if premium else None,
        "counts": lead_send_counts(user_id) if premium else {"sent": 0, "failed": 0},
        "history": lead_send_history(user_id) if premium else [],
        "template": template["name"],
        "writing": "ai" if template.get("ai") else "template",
    }


@router.post("/automation/start")
async def automation_start(current_user=Depends(get_current_user)):
    require_signed(current_user)
    problems = premium_runner.preflight(current_user)
    if problems:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problems[0])
    if quota_status(current_user)["remaining"] <= 0:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="This week's emails are used up. Automation can continue on Monday.")
    premium_runner.start(str(current_user["_id"]))
    return {"started": True}


@router.post("/automation/stop")
async def automation_stop(current_user=Depends(get_current_user)):
    return {"stopping": premium_runner.stop(str(current_user["_id"]))}
