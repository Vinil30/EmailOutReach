"""Credits and plan purchases.

Credits: a balance on the user document plus an append-only ledger of every change.

Spending is a single conditional update (never below zero, safe under parallel requests). Additions that
must happen at most once (a payment, a refund for a job, a migration) carry an idempotency key with a unique
index, so a replayed webhook or a retried request can never add credits twice.

Plans (Pro, Premium) are paid through the same Razorpay orders. A paid plan order is applied to the user
document in one conditional write that also records the order id, so it extends the plan exactly once."""
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.fxns import PAID_PLANS, _now, _serialize_many, as_utc, db, premiumGrants, users

creditLedger = db["creditLedger"]
creditOrders = db["creditOrders"]


def ensure_credit_indexes() -> None:
    creditLedger.create_index([("user_id", 1), ("created_at", -1)])
    creditLedger.create_index("idem", unique=True, sparse=True)
    creditLedger.create_index("applied", partialFilterExpression={"applied": False})
    creditOrders.create_index("order_id", unique=True)
    creditOrders.create_index([("user_id", 1), ("created_at", -1)])


def balance(user_id: str) -> int:
    user = users.find_one({"_id": ObjectId(user_id)}, {"credits": 1}) if ObjectId.is_valid(user_id) else None
    return int((user or {}).get("credits") or 0)


def add_credits(user_id: str, amount: int, kind: str, note: str = "", idem: str | None = None, ref: str | None = None) -> bool:
    """Add (or with a negative amount, remove) credits. Returns False when this idempotency key was already applied."""
    amount = int(amount)
    if not amount or not ObjectId.is_valid(user_id):
        return False
    entry = {"user_id": str(user_id), "delta": amount, "kind": kind, "note": note, "ref": ref, "applied": False, "created_at": _now()}
    if idem:
        entry["idem"] = idem
    try:
        inserted = creditLedger.insert_one(entry)
    except DuplicateKeyError:
        return False
    _apply(inserted.inserted_id, user_id, amount)
    return True


def _apply(entry_id: ObjectId, user_id: str, amount: int) -> None:
    # The user document remembers its last applied entries, so the balance changes once per entry even if this
    # runs twice (a retry, or settle_unapplied after a crash between the two writes below).
    updated = users.find_one_and_update(
        {"_id": ObjectId(user_id), "credit_ops": {"$ne": entry_id}},
        {"$inc": {"credits": amount}, "$push": {"credit_ops": {"$each": [entry_id], "$slice": -200}}},
        {"credits": 1}, return_document=ReturnDocument.AFTER,
    ) or users.find_one({"_id": ObjectId(user_id)}, {"credits": 1})
    creditLedger.update_one({"_id": entry_id, "applied": False},
                            {"$set": {"applied": True, "balance_after": int((updated or {}).get("credits") or 0)}})


def settle_unapplied() -> int:
    """At startup: finish any addition interrupted between writing the ledger row and updating the balance."""
    count = 0
    for entry in creditLedger.find({"applied": False}):
        _apply(entry["_id"], entry["user_id"], int(entry["delta"]))
        count += 1
    return count


def spend_credits(user_id: str, amount: int, kind: str, note: str = "", ref: str | None = None) -> bool:
    """Take credits only if the balance covers them, atomically. Returns False (and changes nothing) otherwise."""
    amount = int(amount)
    if amount <= 0 or not ObjectId.is_valid(user_id):
        return False
    updated = users.find_one_and_update(
        {"_id": ObjectId(user_id), "credits": {"$gte": amount}},
        {"$inc": {"credits": -amount}},
        {"credits": 1},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        return False
    creditLedger.insert_one({"user_id": str(user_id), "delta": -amount, "kind": kind, "note": note, "ref": ref, "applied": True,
                             "balance_after": int(updated.get("credits") or 0), "created_at": _now()})
    return True


def ledger(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = _serialize_many(creditLedger.find({"user_id": str(user_id)}).sort("created_at", -1).limit(limit))
    for row in rows:
        row.pop("idem", None)
    return rows


# ---------- Payment orders ----------

def create_order_record(user_id: str, order_id: str, pack: dict[str, Any], amount_paise: int) -> None:
    creditOrders.insert_one({
        "order_id": order_id, "user_id": str(user_id), "kind": "credits", "pack_id": pack["id"], "credits": int(pack["credits"]),
        "amount": int(amount_paise), "currency": "INR", "status": "created", "created_at": _now(),
    })


def create_plan_order_record(user_id: str, order_id: str, plan: str, days: int, amount_paise: int, prices: dict[str, float]) -> None:
    """Prices of both plans are kept with the order, so a switch is valued at what was shown when buying."""
    creditOrders.insert_one({
        "order_id": order_id, "user_id": str(user_id), "kind": "plan", "plan": plan, "days": int(days), "credits": 0,
        "prices": {name: float(prices[name]) for name in PAID_PLANS}, "amount": int(amount_paise), "currency": "INR",
        "status": "created", "created_at": _now(),
    })


def plan_after_purchase(current_plan: str, current_until, plan: str, days: int, prices: dict[str, float], now) -> tuple[str, Any]:
    """Where a purchase leaves the account. Time already paid for is never lost:
    - same plan: the new days go on top of what's left;
    - Pro -> Premium: the Pro days left are converted to Premium days at their value, then the new days added;
    - buying Pro while on Premium: the account stays on Premium, extended by the Pro days' value in Premium time;
    - otherwise the plan starts now."""
    active = current_plan in PAID_PLANS and current_until and current_until > now
    period = timedelta(days=days)
    ratio = (prices.get("pro") or 0) / prices["premium"] if prices.get("premium") else 1.0
    if not active:
        return plan, now + period
    remaining = current_until - now
    if current_plan == plan:
        return plan, current_until + period
    if current_plan == "pro" and plan == "premium":
        return "premium", now + remaining * ratio + period
    return "premium", current_until + period * ratio


def _apply_plan_order(order: dict[str, Any], payment_id: str) -> bool:
    """Apply a paid plan order once. Returns False if it was applied before."""
    user_id = ObjectId(order["user_id"])
    for _ in range(8):
        user = users.find_one({"_id": user_id}, {"plan": 1, "plan_until": 1, "plan_orders": 1, "email": 1})
        if not user:
            return False
        if order["order_id"] in (user.get("plan_orders") or []):
            return False
        now = _now()
        plan, until = plan_after_purchase(user.get("plan"), as_utc(user.get("plan_until")), order["plan"], order["days"], order["prices"], now)
        # Only write if nothing changed since we read it; otherwise read again.
        updated = users.update_one(
            {"_id": user_id, "plan": user.get("plan"), "plan_until": user.get("plan_until"), "plan_orders": {"$ne": order["order_id"]}},
            {"$set": {"plan": plan, "plan_until": until}, "$push": {"plan_orders": {"$each": [order["order_id"]], "$slice": -50}}},
        )
        if updated.modified_count:
            premiumGrants.update_one({"order_id": order["order_id"]}, {"$setOnInsert": {
                "email": user["email"], "plan": plan, "days": order["days"], "until": until, "pending": False,
                "granted_by": "razorpay", "note": f"Paid online · {payment_id}", "order_id": order["order_id"], "created_at": now,
            }}, upsert=True)
            return True
    raise RuntimeError("Couldn't apply the plan purchase; it will be retried.")


def get_order(order_id: str) -> dict[str, Any] | None:
    return creditOrders.find_one({"order_id": order_id})


def fulfill_order(order_id: str, payment_id: str, amount_paid: int) -> str:
    """Give the credits for a paid order exactly once. Returns "credited", "already" or a reason it wasn't credited."""
    order = creditOrders.find_one({"order_id": order_id})
    if not order:
        return "unknown_order"
    if int(amount_paid) != int(order["amount"]):
        creditOrders.update_one({"_id": order["_id"]}, {"$set": {"status": "amount_mismatch", "payment_id": payment_id, "updated_at": _now()}})
        return "amount_mismatch"
    creditOrders.update_one({"_id": order["_id"], "status": {"$ne": "paid"}},
                            {"$set": {"status": "paid", "payment_id": payment_id, "paid_at": _now()}})
    if order.get("kind") == "plan":
        return "credited" if _apply_plan_order(order, payment_id) else "already"
    # Always attempted: the idempotency key makes a replay a no-op, and it heals a crash between the two writes.
    added = add_credits(order["user_id"], order["credits"], "purchase", f"Bought {order['credits']} credits",
                        idem=f"purchase:{order_id}", ref=payment_id)
    return "credited" if added else "already"


def recent_orders(limit: int = 30) -> list[dict[str, Any]]:
    return _serialize_many(creditOrders.find().sort("created_at", -1).limit(limit))
