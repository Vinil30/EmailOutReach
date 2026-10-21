from fastapi import APIRouter
from pydantic import BaseModel, Field

from utils.spam_guard import analyze_email_risk

router = APIRouter(prefix="/spam", tags=["spam"])


class SpamCheckIn(BaseModel):
    email_subject: str = Field(default="", max_length=500)
    email_body: str = Field(default="", max_length=50000)
    campaign_type: str = "outreach"


@router.post("/check")
async def check(payload: SpamCheckIn):
    """Public, stateless pre-send check used by the editor, the Spam Lab and the landing page demo."""
    campaign_type = "campaign" if payload.campaign_type == "campaign" else "outreach"
    return analyze_email_risk(payload.email_subject, payload.email_body, campaign_type=campaign_type).model_dump()
