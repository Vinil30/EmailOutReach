from fastapi import APIRouter, Depends

from database.fxns import get_current_user, get_sent_emails

router = APIRouter(prefix="/automated", tags=["automated"])


@router.get("/sent-emails")
async def sent_emails(campaign_id: str | None = None, current_user=Depends(get_current_user)):
    return {"emails": get_sent_emails(str(current_user["_id"]), campaign_id)}
