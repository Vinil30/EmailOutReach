"""Marketplace API: buy credits (Razorpay), spend them on contacts from our database or from live web search.

Rules that hold on the server no matter what the browser sends:
- Prices, pack sizes and amounts come from the server's pricing settings, never from the request.
- Credits are added only after Razorpay's signature checks out and the payment is captured for the exact amount,
  and only once per order (webhook and checkout both use the same idempotent fulfilment).
- Buying contacts needs a signed account on Pro or Premium (only automation can email them).
- Bought contacts' addresses are never returned, so they can't be downloaded.
"""
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from database.credits import balance, create_order_record, create_plan_order_record, fulfill_order, get_order, ledger
from database.fxns import as_utc, get_current_user, get_user_by_id, is_paid, plan_of
from database.marketplace import (
    MAX_DATABASE_PACK,
    MarketplaceError,
    available_database_contacts,
    create_job,
    finish_job,
    jobs_for,
    marketplaceJobs,
    owned_contacts_view,
    owned_counts,
    save_search_tags,
    take_database_contacts,
)
from utils import contact_finder, razorpay_client
from utils.legal import require_signed
from utils.plans import PLAN_DAYS, pack_by_id, pricing

router = APIRouter(prefix="/api", tags=["marketplace"])

UPGRADE_FOR_CONTACTS = "Contacts are emailed by automation, which is part of Pro and Premium. Upgrade to buy contacts."


class OrderIn(BaseModel):
    pack_id: str


class PlanOrderIn(BaseModel):
    plan: Literal["pro", "premium"]


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class DatabasePackIn(BaseModel):
    count: int = Field(ge=1, le=MAX_DATABASE_PACK)
    keywords: list[str] = Field(default_factory=list, max_length=10)


class TagsIn(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=contact_finder.MAX_TAGS)


class SearchIn(TagsIn):
    count: int = Field(ge=1, le=contact_finder.MAX_TARGET)


def _http(exc: MarketplaceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _require_buyer(user: dict) -> None:
    require_signed(user)
    if user.get("role") == "campaigner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Recruiter contacts are for job-seeker accounts.")
    if not is_paid(user):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=UPGRADE_FOR_CONTACTS)


@router.get("/marketplace")
def marketplace(current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    profile = current_user.get("profile") or {}
    prices = pricing()
    return {
        "credits": balance(user_id),
        "currency": prices["currency"],
        "packs": prices["packs"],
        "contact_credits": prices["contact_credits"],
        "payments_enabled": razorpay_client.enabled(),
        "search_enabled": contact_finder.search_enabled(),
        "can_buy_contacts": is_paid(current_user),
        "owned": owned_counts(user_id),
        "jobs": jobs_for(user_id),
        "tags": profile.get("search_tags") or contact_finder.suggest_tags(profile),
        "tags_saved": bool(profile.get("search_tags")),
        "limits": {"database": MAX_DATABASE_PACK, "web": contact_finder.MAX_TARGET},
    }


@router.get("/marketplace/available")
def database_available(keywords: str = "", current_user=Depends(get_current_user)):
    words = [word for word in keywords.split(",") if word.strip()][:10]
    return {"available": available_database_contacts(str(current_user["_id"]), words)}


@router.get("/marketplace/contacts")
def my_contacts(status_filter: str | None = Query(None, alias="status"), skip: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=200), current_user=Depends(get_current_user)):
    return owned_contacts_view(str(current_user["_id"]), status_filter, skip, limit)


@router.get("/marketplace/jobs/{job_id}")
def job_detail(job_id: str, current_user=Depends(get_current_user)):
    job = next((row for row in jobs_for(str(current_user["_id"]), 50) if row["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return {"job": job, "credits": balance(str(current_user["_id"]))}


@router.put("/marketplace/tags")
def save_tags(payload: TagsIn, current_user=Depends(get_current_user)):
    tags = contact_finder.clean_tags(payload.tags)
    save_search_tags(str(current_user["_id"]), tags)
    return {"tags": tags}


@router.post("/marketplace/database")
def buy_database_contacts(payload: DatabasePackIn, current_user=Depends(get_current_user)):
    """Buy recruiters from our database. Credits are charged only for contacts actually delivered."""
    _require_buyer(current_user)
    user_id = str(current_user["_id"])
    price = pricing()["contact_credits"]["database"]
    keywords = contact_finder.clean_tags(payload.keywords)
    try:
        job = create_job(user_id, "database", payload.count, payload.count * price, {"tags": keywords})
    except MarketplaceError as exc:
        raise _http(exc) from exc
    try:
        added = take_database_contacts(user_id, str(job["_id"]), payload.count, price, keywords)
        if added:
            marketplaceJobs.update_one({"_id": job["_id"]}, {"$inc": {"delivered": added, "spent": added * price, "from_database": added}})
        message = (f"Added {added} contacts." if added == payload.count
                   else f"Added {added} of {payload.count}: that's every matching contact you don't already have. Unused credits were returned."
                   if added else "No new matching contacts right now. Your credits were returned.")
        done = finish_job(job["_id"], "completed" if added == payload.count else "partial" if added else "failed", message)
    except Exception:
        finish_job(job["_id"], "failed", "Something went wrong. Unused credits were returned.")
        raise
    return {"added": added, "message": message, "refunded": done["refunded"], "credits": balance(user_id)}


@router.post("/marketplace/search")
def start_search(payload: SearchIn, current_user=Depends(get_current_user)):
    """Find new contacts on the web for the user's tags. Runs in the background; poll the job."""
    _require_buyer(current_user)
    tags = contact_finder.clean_tags(payload.tags)
    save_search_tags(str(current_user["_id"]), tags)
    try:
        job = contact_finder.start_job(current_user, tags, payload.count, pricing()["contact_credits"])
    except MarketplaceError as exc:
        raise _http(exc) from exc
    return {"job_id": str(job["_id"]), "reserved": job["reserved"], "credits": balance(str(current_user["_id"]))}


# ---------- Buying credits (Razorpay) ----------

@router.get("/credits/ledger")
def credit_history(current_user=Depends(get_current_user)):
    return {"credits": balance(str(current_user["_id"])), "entries": ledger(str(current_user["_id"]))}


@router.post("/credits/orders")
def create_credit_order(payload: OrderIn, current_user=Depends(get_current_user)):
    require_signed(current_user)
    pack = pack_by_id(payload.pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That credit pack isn't available")
    amount = int(round(pack["price"] * 100))
    order = _razorpay_order(amount, {"user_id": str(current_user["_id"]), "pack_id": pack["id"], "credits": str(pack["credits"])})
    create_order_record(str(current_user["_id"]), order["id"], pack, amount)
    return {"order_id": order["id"], "amount": amount, "currency": "INR", "key_id": razorpay_client.key_id(),
            "credits": pack["credits"], "email": current_user["email"], "name": (current_user.get("profile") or {}).get("full_name", "")}


def _razorpay_order(amount: int, notes: dict[str, str]) -> dict:
    try:
        return razorpay_client.create_order(amount, f"mz-{uuid.uuid4().hex[:20]}", notes)
    except razorpay_client.PaymentsNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except razorpay_client.PaymentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/plans/orders")
def create_plan_order(payload: PlanOrderIn, current_user=Depends(get_current_user)):
    """Start buying Pro or Premium. The price comes from the server's pricing settings."""
    require_signed(current_user)
    prices = pricing()
    price = prices[payload.plan]["price"]
    if price <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This plan can't be bought right now.")
    if payload.plan == "pro" and plan_of(current_user) == "premium":
        until = as_utc(current_user.get("plan_until"))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"You're on Premium until {until:%d %b %Y}, which already includes everything in Pro. Renew Premium to add more days.")
    amount = int(round(price * 100))
    order = _razorpay_order(amount, {"user_id": str(current_user["_id"]), "plan": payload.plan, "days": str(PLAN_DAYS)})
    create_plan_order_record(str(current_user["_id"]), order["id"], payload.plan, PLAN_DAYS, amount,
                             {"pro": prices["pro"]["price"], "premium": prices["premium"]["price"]})
    return {"order_id": order["id"], "amount": amount, "currency": "INR", "key_id": razorpay_client.key_id(),
            "plan": payload.plan, "days": PLAN_DAYS, "email": current_user["email"],
            "name": (current_user.get("profile") or {}).get("full_name", "")}


@router.post("/credits/verify")
def verify_credit_payment(payload: VerifyIn, current_user=Depends(get_current_user)):
    """Called by the browser after Razorpay Checkout succeeds. The webhook gives the same credits if this never arrives."""
    order = get_order(payload.razorpay_order_id)
    if not order or order["user_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if not razorpay_client.checkout_signature_valid(payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment couldn't be verified")
    try:
        payment = razorpay_client.fetch_payment(payload.razorpay_payment_id)
        if payment.get("order_id") != order["order_id"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment doesn't match this order")
        if payment.get("status") == "authorized":
            payment = razorpay_client.capture_payment(payload.razorpay_payment_id, order["amount"])
    except razorpay_client.PaymentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if payment.get("status") != "captured":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The payment wasn't completed")
    result = fulfill_order(order["order_id"], payment["id"], int(payment.get("amount") or 0))
    if result not in ("credited", "already"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This payment couldn't be matched to your order. Contact support.")
    user = get_user_by_id(str(current_user["_id"])) or current_user
    return {"result": result, "credits": balance(str(current_user["_id"])), "kind": order.get("kind") or "credits",
            "plan": plan_of(user), "plan_until": user.get("plan_until")}


@router.post("/razorpay/webhook", include_in_schema=False)
async def razorpay_webhook(request: Request):
    """Razorpay calls this for every payment, so credits arrive even if the user closes the tab after paying."""
    raw = await request.body()
    if not razorpay_client.webhook_signature_valid(raw, request.headers.get("X-Razorpay-Signature", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")
    event = json.loads(raw or b"{}")
    payment = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if event.get("event") in ("payment.captured", "order.paid") and payment.get("order_id") and payment.get("status") == "captured":
        await run_in_threadpool(fulfill_order, payment["order_id"], payment["id"], int(payment.get("amount") or 0))
    return {"ok": True}
