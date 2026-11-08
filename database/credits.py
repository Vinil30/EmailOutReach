"""Credits: a balance on the user document plus an append-only ledger of every change.

Spending is a single conditional update (never below zero, safe under parallel requests). Additions that
must happen at most once (a payment, a refund for a job, a migration) carry an idempotency key with a unique
index, so a replayed webhook or a retried request can never add credits twice."""
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.fxns import _now, _serialize_many, db, users

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
        "order_id": order_id, "user_id": str(user_id), "pack_id": pack["id"], "credits": int(pack["credits"]),
        "amount": int(amount_paise), "currency": "INR", "status": "created", "created_at": _now(),
    })


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
    # Always attempted: the idempotency key makes a replay a no-op, and it heals a crash between the two writes.
    added = add_credits(order["user_id"], order["credits"], "purchase", f"Bought {order['credits']} credits",
                        idem=f"purchase:{order_id}", ref=payment_id)
    return "credited" if added else "already"


def recent_orders(limit: int = 30) -> list[dict[str, Any]]:
    return _serialize_many(creditOrders.find().sort("created_at", -1).limit(limit))
